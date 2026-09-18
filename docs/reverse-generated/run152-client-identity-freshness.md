# Run 152 — client identity freshness: raw device_list → client hash → HostInfo

This note resolves whether stale HostInfo IP/MAC can explain zero per-client
rates when the kernel `online_ip` record is otherwise valid.

## Source records

`confctl_device_list_upload` receives:

```text
32-byte reporting-node identity
+ N * 124-byte raw client records
```

The merge function at `0x4320f0` finds existing clients by MAC and dispatches
to:

- `add_new_client_to_hash_table(raw_client, reporter)`
- `update_client_info_to_hash_table(existing, raw_client, reporter)`

The central client-status object is 148 bytes.

## Identity mapping

### New client

`add_new_client_to_hash_table` performs these relevant copies:

```text
raw_client +0x10  --64 B--> client_status +0x0c
raw_client +0x50  -- 4 B--> client_status +0x4c
raw_client +0x54  -- 6 B--> client_status +0x50
reporter   +0x00  --32 B--> client_status +0x60
```

The mapper `fill_host_info_from_client_status` later exposes:

```text
client_status +0x4c -> HostInfo.ipaddr
client_status +0x50 -> HostInfo.ethaddr
client_status +0x60 -> HostInfo.assoc_sn
```

Thus the initial HostInfo identity is copied directly from the raw
`device_list` client record.

### Existing client update

`update_client_info_to_hash_table` repeatedly performs:

```text
raw_client +0x50  --4 B--> client_status +0x4c
```

on its normal update branches.

Therefore the client's IPv4 address is refreshed from every accepted
`device_list` report and does not remain frozen at first discovery.

The function does not normally rewrite `client_status+0x50` (MAC), because
the existing record was already selected by MAC identity. This is consistent
with MAC being the key of the client hash/merge path.

If a device changes its MAC, it no longer matches the existing client key and
is treated as a different/new client rather than silently keeping the old MAC
with a new device identity.

The 32-byte reporting-node identity is refreshed into
`client_status+0x60`, which later becomes `HostInfo.assoc_sn`.

## Consequence for strict g_ip_info matching

The userspace rate helper requires strict:

```text
HostInfo.ipaddr == online_ip.ip
AND
HostInfo.ethaddr == online_ip.mac
```

Run 152 substantially weakens a generic stale-HostInfo-identity explanation:

- IP is actively refreshed on client reports,
- MAC is the merge key and remains stable for the lifetime of that client
  record,
- a changed/randomized MAC becomes a new client record rather than an update
  of the old key,
- assoc_sn is also refreshed from the latest reporting mesh node.

A strict-match failure is still possible at runtime, but it would now require a
more specific discrepancy, for example:

- kernel online_ip MAC extraction differs from device_list's client MAC for a
  particular traffic path,
- the device_list report itself contains a different current identity,
- timing/race between a DHCP/IP change and the next device_list report.

It is no longer reasonable to assume that HostInfo simply keeps a permanently
stale IP from initial discovery.

## Current diagnostic priority

The highest-value live distinction remains:

1. `HostInfo.online` drops due to the 45-second device-list watchdog,
2. `HostInfo.online` stays 1 but firmware rates remain zero,
3. at least one non-zero firmware rate is observed.

`tools/mw6_probe.py --diagnose-rates` captures IP and assoc_sn across the
same >45-second window, so an IP or node transition will also be visible in a
single run.
