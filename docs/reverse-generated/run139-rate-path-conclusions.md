# Run 139 — consolidated per-client rate pipeline

This document is the current source of truth for MW6 per-client traffic rates
after Runs 37 and 123–138.

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

- vendor skb direction bit `0x2` at skb offset `+0x78`,
- a valid unicast IPv4 address.

`check_ip_addr` rejects:

- address zero,
- first IPv4 octet >= 224.

Thus normal LAN addresses such as `192.168.5.x` are accepted.

Concrete bit-0x2 producers found in the kernel:

- `rtl_netif_rx`: `skb+0x78 |= 0x2`
- `interrupt_dsr_rx`: `skb+0x78 |= 0x2`

The exact source of complementary bit `0x1` remains unresolved.

## 6. Packet accounting

`nos.ko::tbq_timer_func` is the confirmed writer of per-client traffic
counters.

It obtains the connection's attached `online_ip` pointer and adds packet
length according to direction flags.

Kernel record counters:

| Kernel offset | Meaning |
| --- | --- |
| `+0x50/+0x54` | current TX/upload bytes |
| `+0x58/+0x5c` | previous TX/upload snapshot |
| `+0x60/+0x64` | current RX/download bytes |
| `+0x68/+0x6c` | previous RX/download snapshot |

The same function also updates global `wan_tx_bytes` / `wan_rx_bytes`.

## 7. Kernel → userspace counter mapping

`get_online_ip_info` repacks the counters:

| Kernel | 232-byte userspace record |
| --- | --- |
| `+0x50/+0x54` | `+0x18` current upload |
| `+0x58/+0x5c` | `+0x20` previous upload |
| `+0x60/+0x64` | `+0x28` current download |
| `+0x68/+0x6c` | `+0x30` previous download |

During serialization the current values are copied into previous-snapshot
slots, which provides the sampling baseline for the next request.

## 8. Rate calculation

The userspace helper samples statistics, measures elapsed microseconds and
calculates deltas.

The final conversion is:

`delta_bytes / elapsed_seconds / 1024`

Therefore:

- `uprate` = upload rate in KiB/s,
- `downrate` = download rate in KiB/s.

## 9. What zero rates now mean

If an online client has valid IP/MAC but `uprate == downrate == 0` under
known traffic, the already-resolved layers are:

- protobuf field mapping,
- TCP/9000 MESH_HOSTS/GetHostList routing,
- rate-helper invocation,
- rate units,
- strict identity matcher,
- userspace netlink request format.

The unresolved runtime fault domain is now narrow:

1. no online-ip record is created/returned for that flow,
2. the flow is attached to online-ip but bypasses NOS/TBQ byte accounting,
3. HW NAT / Realtek fastpath / bridge shortcut bypasses the expected slow path,
4. HostInfo IP/MAC does not equal the online-ip record at sampling time.

## 10. Next reverse target

Resolve the origin and semantics of skb direction bit `0x1`, then determine
whether HW NAT / fastpath can bypass:

`direction mark → nf_conntrack_in → online_ip → NOS/TBQ accounting`.

Only after that should a live test be added, and it should distinguish:

- no online-ip record,
- record with static counters,
- record with moving counters but failed HostInfo match.
