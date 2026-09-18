# Run 139 — consolidated per-client rate pipeline

This document is the current source of truth for MW6 per-client traffic rates
after Runs 37 and 123–146.

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

Runs 145–146 narrow the kernel-side fault domain further.

### Conntrack attachment

For normal LAN-originated IPv4 traffic, `nf_conntrack_in` enters the
online-ip creation/attachment path only when the upload marker
`skb+0x78 & 0x2` is present.

- `ct+0x8c` is the stored `online_ip *`.
- If already non-NULL, firmware marks `online_ip+0x40 = 1` (active).
- Otherwise `find_online_ip(client_ipv4)` searches by IPv4.
- If absent, `add_online_ip` creates the record.
- Firmware stores `ct+0x8c = online_ip`, increments
  `online_ip+0x08`, and links `ct+0x90/+0x94` into the record's
  conntrack list at `online_ip+0x38`.

### MAC source

`add_online_ip` copies six bytes into `online_ip+0x2c` from
`skb_mac_header(skb)+6`, i.e. the source MAC of the reconstructed Ethernet
frame.

The close RTL8197F/MW5 source confirms that 802.11s receive processing calls
`skb_p80211_to_ether` before `rtl_netif_rx`. For a six-address mesh frame
that conversion explicitly builds the Ethernet source address from
`mesh_header.SrcMACAddr`, not the intermediate mesh-neighbor MAC. A simple
satellite/backhaul MAC substitution is therefore not a likely reason for the
strict HostInfo-vs-online_ip MAC match to fail.

### Lifetime

The firmware reports HZ=100. `online_ip_timeout` runs every 6000 jiffies,
therefore every 60 seconds.

A timeout frees a record only when all of these are true:

- active flag `online_ip+0x40 == 0`,
- conntrack refcount `online_ip+0x08 == 0`,
- conntrack list at `online_ip+0x38` is empty,
- byte flag `online_ip+0x99 == 0`.

If the active flag or any reference is present, the record is retained and the
timer is rearmed for another 60 seconds.

Run 146 confirms the inverse path in `destroy_conntrack`: if `ct+0x8c`
is set, firmware atomically decrements `online_ip+0x08`, unlinks
`ct+0x90/+0x94` from the online-ip list, and clears `ct+0x8c`.

Therefore an online-ip record cannot age out while a referenced active
conntrack remains attached. Plain timeout/lifetime is no longer a leading
explanation for zero rates during active transfer.

The highest-value unresolved fault domain is now above that layer:

1. `HostInfo.online` is zero/stale, so the rate helper skips the client
   before matching `g_ip_info`,
2. the client never creates a qualifying LAN→WAN IPv4 conntrack/online-ip
   association,
3. HostInfo IP/MAC is stale or otherwise differs from the reconstructed
   Ethernet identity in `online_ip`.

## 13. Next reverse target

The kernel attachment, MAC source and lifetime path are now resolved. The next
target moves back to userspace inventory state:

`device_list client status → fill_host_info_from_client_status → HostInfo.online`.

Resolve the exact source field and offline/aging logic for HostInfo.online,
because a false zero there prevents `fill_host_lists_rate` from attempting
the otherwise-correct online-ip match.

After that static path is exhausted, one live read-only test should distinguish
a stale HostInfo.online value from missing online-ip counters or an identity
mismatch.
