# Run 139 — consolidated per-client rate pipeline

This document is the current source of truth for MW6 per-client traffic rates
after Runs 37 and 123–144.

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

TCP/12598 cmdsrv remains useful for its supported command/Redis transport, but
`GetHostList` does not provide a usable response path there. Per-client
HostList work stays on authenticated TCP/9000.

## 2. GetHostList executes the rate helper

`confctl_get_host_list` builds the host list and calls the local helper at
`0x434258`.

Run 134 resolves that helper's important imports:

- `netlink_get_statistic_info`
- `inet_addr`
- `ifaddrs_ethaddr_aton`
- `g_ip_info`
- `host_lists__get_packed_size`
- `host_lists__pack`

Fields 7/8 are therefore active rate fields, not unused protobuf members.

## 3. HostInfo rate gate and matching

The per-host gate is `HostInfo.online != 0`, not `condtion_time`.

For online clients the helper parses both IP and MAC and performs a strict
match against `g_ip_info`:

- IPv4 equality,
- 6-byte MAC equality,
- 232-byte online-ip record stride.

There is no IP-only or MAC-only fallback.

## 4. Userspace statistics transport

`netlink_get_statistic_info` lives in `libcommon.so`.

It:

1. opens `AF_NETLINK / SOCK_DGRAM / protocol 31`,
2. sends netlink message type `17`,
3. receives the kernel statistics reply,
4. reads the online-ip record count,
5. if `count > 0`, allocates `count * 232` bytes and fills `g_ip_info`,
6. if `count == 0`, leaves `g_ip_info == NULL`.

A NULL `g_ip_info` is therefore primarily evidence of an empty kernel
online-ip snapshot, not a protobuf/API failure.

## 5. Kernel online_ip lifecycle

Netlink message type 17 reaches `get_online_ip_info`, which serializes records
already present in `online_ip_hash`; it does not create clients.

Creation is performed by `add_online_ip`. The only direct caller found in
this firmware is `nf_conntrack_in`.

The creation path requires:

- vendor skb direction/accounting bit `0x2` at `skb+0x78`,
- a valid unicast IPv4 address.

`check_ip_addr` rejects only address zero and first IPv4 octet >= 224, so
normal LAN addresses such as `192.168.5.x` pass.

## 6. MW6 sk_buff direction metadata

Runs 140–141 resolve this neighborhood in the actual MW6 Linux 3.10.90 /
RTL8197F kernel:

| skb offset | Meaning |
| --- | --- |
| `+0x70` | `skb_iif` |
| `+0x74` | Tenda/Realtek private 32-bit field A |
| `+0x78` | Tenda/Realtek private 32-bit direction/accounting field B |
| `+0x7c` | `rxhash` |
| `+0x80` | `vlan_proto` |
| `+0x82` | `vlan_tci` |
| `+0x84` | `tc_index` |

`__alloc_skb` zeroes the two private words and `__copy_skb_header` copies
both, so they are persistent packet metadata.

## 7. Direction bits and producers

`nos.ko` proves:

- bit `0x2` = WAN TX / client upload / LAN → WAN,
- bit `0x1` = WAN RX / client download / WAN → LAN.

LAN/Wi-Fi receive paths set `skb+0x78 |= 0x2`.

Run 142 resolves the WAN receive branch too. Ethernet RX checks the first
32-bit member of the selected Realtek `struct dev_priv`. The public Realtek
SDK defines this member as `u32 id`, with:

- `RTL_WANVLANID = 8`
- `RTL_LANVLANID = 9`

When `dev_priv.id == 8`, MW6 executes `skb+0x78 |= 0x5`. Since `0x5`
contains bit `0x1` and not bit `0x2`, NOS classifies it as WAN
RX/download. Bit `0x4` has an additional vendor meaning that is not required
for direction accounting.

## 8. Packet accounting and software FastPath

`nos.ko::tbq_timer_func` is one confirmed writer of per-client traffic
counters.

Runs 143–144 resolve a second, more important packet-accounting path. During
module initialization, `nos.ko` writes its callback at `.text+0x5e9c` into
the exported kernel callback pointer `nos_tbq_enqueue`.

Run 144 resolves:

- `__ksymtab_nos_tbq_enqueue` at `0x80547fd8`,
- exported callback-pointer variable at `0x81a1b8b8`,
- exactly two kernel call sites:
  - `fastpath_xmit_prerouting_hook` at `0x80389730`,
  - `dev_queue_xmit` at `0x8038e1dc`.

Both call the installed NOS callback when present.

The callback:

- receives the skb,
- follows the skb conntrack pointer,
- follows the conntrack online-ip association,
- tests `skb+0x78` bits 0x2/0x1,
- updates per-client TX/RX byte and packet counters,
- updates global `wan_tx_bytes` / `wan_rx_bytes`,
- participates in TBQ filter/queue decisions,
- marks a processed skb with byte `skb+0x47 = 16`.

The two kernel call sites skip the callback when that processed marker is
already present, avoiding double accounting when a FastPath packet later
reaches `dev_queue_xmit`.

**Conclusion:** software Realtek FastPath does not bypass Tenda per-client
NOS/TBQ accounting. It explicitly invokes it.

## 9. HW NAT state

The reference boot log for the same firmware family shows HW NAT initially
reaching `/proc/hw_nat = 1`, but WAN/TBQ configuration later changes it to
`0`. In the captured TBQ-enabled operating state, repeated
`cat /proc/hw_nat` output is `0`.

Therefore HW NAT is not the leading explanation for zero per-client rates in
the known firmware state. A live router could still be checked later if needed,
but the static/reference evidence now points elsewhere.

## 10. online_ip counters

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

## 11. Kernel → userspace counter mapping

`get_online_ip_info` repacks the byte counters:

| Kernel | 232-byte userspace record |
| --- | --- |
| `+0x50/+0x54` | `+0x18` current upload |
| `+0x58/+0x5c` | `+0x20` previous upload |
| `+0x60/+0x64` | `+0x28` current download |
| `+0x68/+0x6c` | `+0x30` previous download |

The userspace helper then computes
`delta_bytes / elapsed_seconds / 1024`.

Therefore:

- `uprate` = upload rate in KiB/s,
- `downrate` = download rate in KiB/s.

## 12. What zero rates now mean

For an online client with valid IP/MAC but zero `uprate/downrate` during
known traffic, the following layers are already resolved:

- protobuf schema,
- TCP/9000 GetHostList routing,
- rate-helper invocation,
- units,
- strict IP+MAC matcher,
- netlink transport,
- TX/RX direction metadata,
- LAN/WAN direction producers,
- software FastPath accounting.

The highest-value unresolved fault domain is now:

1. `online_ip` record is not created for the client/flow,
2. conntrack exists but its online-ip association remains NULL/stale,
3. online-ip identity differs from HostInfo IP/MAC at sampling time,
4. online-ip record lifetime/timeout removes the record before sampling.

## 13. Next reverse target

Trace the exact `nf_conntrack_in → find_online_ip/add_online_ip → ct online_ip`
attachment path, especially the conntrack member used by NOS at `ct+0x8c`.

Resolve:

- every write/read of `ct+0x8c`,
- when the association can remain NULL,
- online-ip IP/MAC identity offsets and source,
- timeout/removal behavior,
- whether an existing conntrack can outlive or miss its online-ip record.

Only after this static path is exhausted should a live test distinguish
missing online-ip, static counters, and HostInfo identity mismatch.
