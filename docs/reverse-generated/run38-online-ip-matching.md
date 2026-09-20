# Run 38 — HostInfo → online_ip matching path

> Updated after Runs 37, 134–138. This note originally associated the rate
> gate with `condtion_time`; later descriptor/layout analysis proved that
> interpretation was wrong. The authoritative gate is `HostInfo.online`.

## Preconditions

For every runtime `HostInfo`, the rate helper first tests the scalar at
`HostInfo + 0x20`.

Later protobuf-c layout reconstruction proves this slot is `online`, not
`condtion_time`.

Therefore:

- `online == 0` skips rate lookup,
- `condtion_time` is not the rate gate,
- an online HostInfo continues to IP/MAC parsing and matching.

## Matching inputs

The helper then prepares both identity fields:

1. `HostInfo.ipaddr` is converted to IPv4.
2. `HostInfo.ethaddr` is parsed to a 6-byte MAC using the
   `ifaddrs_ethaddr_aton`-style helper.
3. A malformed/unparseable MAC skips rate lookup for that HostInfo.
4. The matcher receives:
   - parsed IPv4,
   - parsed 6-byte MAC,
   - `g_ip_info`,
   - the number of online-ip records.

Later disassembly resolves the predicate: matching is strict **IP AND MAC**,
not a fallback between them. The list uses a **232-byte record stride**.

## Source of g_ip_info

Runs 134–135 resolve the complete userspace path:

`confctl_get_host_list`
→ local rate helper at `0x434258`
→ `netlink_get_statistic_info`
→ AF_NETLINK/SOCK_DGRAM protocol 31, message type 17
→ kernel `get_online_ip_info`
→ `g_ip_info`.

The response contains a record count and then 232-byte records. If the kernel
returns a count of zero, userspace does not allocate `g_ip_info`; it remains
NULL.

Thus `g_ip_info == NULL` normally means that no kernel `online_ip` records
were returned for that snapshot. Allocation failure is another possible but
less likely cause.

## Kernel record creation

Run 136 resolves the creation path.

`get_online_ip_info` only serializes records already present in
`online_ip_hash`; it does not create them.

`add_online_ip` has one direct caller in this firmware:
`nf_conntrack_in`.

For the creation path:

- `nf_conntrack_in` requires direction bit `0x2` in the vendor skb field at
  offset `+0x78`,
- `check_ip_addr` rejects only zero and multicast/reserved first octets
  (`>= 224`),
- normal LAN addresses such as `192.168.5.x` pass,
- an existing online-ip record is reused; otherwise `add_online_ip` creates
  the record.

Run 137/138 finds a concrete producer of the required bit:
`rtl_netif_rx` performs `skb+0x78 |= 0x2` before the packet enters the
normal networking path. A second Ethernet RX routine,
`interrupt_dsr_rx`, also sets bit `0x2`.

The exact setter for the complementary `0x1` direction is still unresolved;
the broad scans did not find a trustworthy symmetric simple OR operation.

## Counters and rates

`nos.ko::tbq_timer_func` is the confirmed packet-accounting writer. It follows
the connection to its attached `online_ip` record and adds packet length to
64-bit counters.

Kernel online-ip record:

- `+0x50/+0x54` — current TX/upload bytes,
- `+0x58/+0x5c` — previous TX/upload snapshot,
- `+0x60/+0x64` — current RX/download bytes,
- `+0x68/+0x6c` — previous RX/download snapshot.

`get_online_ip_info` repacks them to the userspace 232-byte record:

- `+0x18` — current upload,
- `+0x20` — previous upload,
- `+0x28` — current download,
- `+0x30` — previous download.

The userspace rate helper takes two snapshots, calculates byte deltas over
elapsed microseconds and converts bytes/s to KiB/s before storing:

- protobuf field 7 = `uprate`,
- protobuf field 8 = `downrate`.

## Current diagnostic interpretation

If a TCP/9000 `MESH_HOSTS_GET` client is online but reports
`uprate=0` and `downrate=0` during known traffic, do not revisit protobuf
decoding or cmdsrv response routing first.

The remaining high-value suspects are:

1. no matching runtime record in kernel `online_ip_hash`,
2. `online_ip` record exists but NOS/TBQ accounting is not seeing the flow,
3. fastpath/HW-NAT/bridge shortcut bypasses part of the normal accounting path,
4. IP/MAC identity changes between HostInfo and the strict `g_ip_info` match.

The obsolete hypothesis that `condtion_time == 0` blocks rate processing is
retired.
