# Run 139 — consolidated per-client rate pipeline

This document is the current source of truth for MW6 per-client traffic rates
after Runs 37 and 123–141.

## 1. Local API surface

Authenticated TCP/9000:

- module `M_MESH_HOSTS = 0x14`
- command `CMD_MESH_HOSTS_GET = 0x00`
- firmware command name: `GetHostList`
- response: protobuf `HostLists`

`HostInfo` fields:

1. `ipaddr`
2. `ethaddr`
3. `access`
4. `assoc_sn`
5. `condtion_time`
6. `online`
7. `uprate`
8. `downrate`
9. `signal`
10. `name`

TCP/12598 cmdsrv is useful for its supported command/Redis transport, but
`GetHostList` is not a valid pub/sub reply path there. Per-client HostList
work therefore stays on authenticated TCP/9000.

## 2. GetHostList really executes the rate helper

`confctl_get_host_list` builds the host list and calls the local helper at
`0x434258`.

Run 134 resolves that helper's important imports, including:

- `netlink_get_statistic_info`
- `inet_addr`
- `ifaddrs_ethaddr_aton`
- `g_ip_info`
- `host_lists__get_packed_size`
- `host_lists__pack`

Therefore fields 7/8 are not unused schema members: the local GetHostList path
actively tries to populate them.

## 3. HostInfo rate gate and matching

The per-host gate is:

`HostInfo.online != 0`

It is **not** `condtion_time`.

For online clients the helper parses both IP and MAC and performs a strict
match against `g_ip_info` using:

- IPv4 equality,
- 6-byte MAC equality,
- 232-byte online-ip record stride.

No IP-only or MAC-only fallback is used.

## 4. Userspace statistics transport

`netlink_get_statistic_info` lives in `libcommon.so`.

It:

1. opens `AF_NETLINK / SOCK_DGRAM / protocol 31`,
2. sends netlink message type `17`,
3. receives the kernel statistics reply,
4. reads the online-ip record count,
5. if `count > 0`, allocates `count * 232` bytes and copies records to
   `g_ip_info`,
6. if `count == 0`, leaves `g_ip_info == NULL`.

So a NULL `g_ip_info` is primarily evidence of an empty kernel online-ip
snapshot, not a protobuf/API failure.

## 5. Kernel online_ip lifecycle

Netlink message type 17 reaches `get_online_ip_info`.

That function serializes records already present in `online_ip_hash`; it does
not create clients.

Creation is performed by `add_online_ip`, whose only direct caller found in
this firmware is `nf_conntrack_in`.

The creation path requires:

- vendor skb direction/accounting bit `0x2` at skb offset `+0x78`,
- a valid unicast IPv4 address.

`check_ip_addr` rejects:

- address zero,
- first IPv4 octet >= 224.

Thus normal LAN addresses such as `192.168.5.x` are accepted.

Concrete bit-0x2 producers found in the kernel:

- `rtl_netif_rx`: `skb+0x78 |= 0x2`
- `interrupt_dsr_rx`: `skb+0x78 |= 0x2`

## 6. MW6 sk_buff layout around the direction field

Runs 140–141 resolve the relevant neighborhood in the actual MW6 Linux
3.10.90 / RTL8197F kernel:

| skb offset | Meaning |
| --- | --- |
| `+0x70` | `skb_iif` |
| `+0x74` | Tenda/Realtek private 32-bit field A |
| `+0x78` | Tenda/Realtek private 32-bit direction/accounting field B |
| `+0x7c` | `rxhash` |
| `+0x80` | `vlan_proto` |
| `+0x82` | `vlan_tci` |
| `+0x84` | `tc_index` |

The earlier hypothesis that `+0x78` could be `rxhash` is disproved:
`__skb_get_rxhash` writes `rxhash` at exactly `+0x7c`.

The `skb_iif` identity is independently confirmed by
`__netif_receive_skb_core`, where the assembly corresponding to
`skb->skb_iif = skb->dev->ifindex` stores at `+0x70`.

Both private fields `+0x74` and `+0x78` are:

- zeroed by `__alloc_skb`,
- explicitly copied by `__copy_skb_header`.

Therefore field B is persistent packet metadata, not temporary driver scratch
space.

The exact C member name of field B is still unknown because the closest public
Realtek SDK v3.4.11C source does not contain these two extra words.

## 7. Direction bits are now resolved

`nos.ko::tbq_timer_func` tests the private word at `skb+0x78`:

- `field & 0x2` takes the TX branch,
- otherwise `field & 0x1` takes the RX branch.

The TX branch:

- adds `skb->len` to the online-ip TX byte counter,
- increments the online-ip TX packet counter,
- adds `skb->len` to global `wan_tx_bytes`.

The RX branch:

- adds `skb->len` to the online-ip RX byte counter,
- increments the online-ip RX packet counter,
- adds `skb->len` to global `wan_rx_bytes`.

Therefore the semantics are proven:

- **bit `0x2` = WAN TX / client upload / LAN → WAN**
- **bit `0x1` = WAN RX / client download / WAN → LAN**

This also explains why Wi-Fi/LAN receive functions set bit `0x2`: a packet
received by the router from a LAN client is traffic that will be transmitted
toward WAN.

Run 142 resolves the complementary RX producer as well. In the Ethernet RX
path, firmware normally applies `skb+0x78 |= 0x2`. Before that write it checks
the selected interface private data. When the first 32-bit field equals `8`,
it instead executes:

```text
skb+0x78 |= 0x5
```

The public Realtek SDK defines the first member of `struct dev_priv` as
`u32 id` (the VLAN/interface ID), and defines:

- `RTL_WANVLANID = 8`
- `RTL_LANVLANID = 9`

Therefore this branch is the WAN receive branch:

- LAN/Wi-Fi RX → `field |= 0x2` → upload,
- WAN Ethernet RX (`dev_priv.id == 8`) → `field |= 0x5`.

`0x5` contains bit `0x1` and does not contain bit `0x2`, so
`tbq_timer_func` takes its WAN-RX/download accounting branch. Bit `0x4`
has an additional vendor meaning that is not yet required to distinguish
upload from download.

## 8. Packet accounting

`nos.ko::tbq_timer_func` is the confirmed writer of per-client traffic
counters.

Kernel online-ip record:

| Kernel offset | Meaning |
| --- | --- |
| `+0x50/+0x54` | current TX/upload bytes |
| `+0x58/+0x5c` | previous TX/upload snapshot |
| `+0x60/+0x64` | current RX/download bytes |
| `+0x68/+0x6c` | previous RX/download snapshot |
| `+0x70/+0x74` | TX/upload packet count |
| `+0x78/+0x7c` | RX/download packet count |

The online-ip record offsets above are unrelated to the identically numbered
offsets in `struct sk_buff`.

## 9. Kernel → userspace counter mapping

`get_online_ip_info` repacks the byte counters:

| Kernel | 232-byte userspace record |
| --- | --- |
| `+0x50/+0x54` | `+0x18` current upload |
| `+0x58/+0x5c` | `+0x20` previous upload |
| `+0x60/+0x64` | `+0x28` current download |
| `+0x68/+0x6c` | `+0x30` previous download |

During serialization the current values are copied into previous-snapshot
slots, which provides the sampling baseline for the next request.

## 10. Rate calculation

The userspace helper samples statistics, measures elapsed microseconds and
calculates deltas.

The final conversion is:

`delta_bytes / elapsed_seconds / 1024`

Therefore:

- `uprate` = upload rate in KiB/s,
- `downrate` = download rate in KiB/s.

## 11. What zero rates now mean

If an online client has valid IP/MAC but `uprate == downrate == 0` under
known traffic, the already-resolved layers are:

- protobuf field mapping,
- TCP/9000 MESH_HOSTS/GetHostList routing,
- rate-helper invocation,
- rate units,
- strict identity matcher,
- userspace netlink request format,
- TX/RX direction-bit semantics.

The unresolved runtime fault domain is now narrow:

1. no online-ip record is created/returned for that flow,
2. the flow is attached to online-ip but bypasses NOS/TBQ byte accounting,
3. HW NAT / Realtek fastpath / bridge shortcut bypasses the expected slow path,
4. HostInfo IP/MAC does not equal the online-ip record at sampling time.

## 12. Next reverse target

The direction-bit producers are now resolved. The next target is whether HW
NAT / Realtek FastPath can bypass or short-circuit:

`direction mark → nf_conntrack_in → online_ip → NOS/TBQ accounting`.

In particular, determine whether established accelerated flows continue to
feed `tbq_timer_func` / online-ip counters or only their initial slow-path
packets are accounted.

Only after that should a live test be added, and it should distinguish:

- no online-ip record,
- record with static counters,
- record with moving counters but failed HostInfo match.
