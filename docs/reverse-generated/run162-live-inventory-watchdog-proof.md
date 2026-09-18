# Run 162 — live proof: inventory gate blocks per-client rates

Live test on client `192.168.5.47` (`Kamil-Dell`) used the read-only
TCP/9000 diagnostic for 65 seconds, deliberately longer than the firmware's
45-second inventory watchdog.

Observed stable client identity:

- IP: `192.168.5.47`
- MAC: `90:61:AE:6F:AD:D3`
- node serial: `E85920101213014563`
- signal: `-55`
- HostInfo.online: always `0`
- HostInfo.uprate/downrate: always `0/0`

The independent WAN control was non-zero on every sample:

- `wan_nonzero_samples = 14/14`
- maximum WAN upload raw rate: `14278`
- maximum WAN download raw rate: `26733`

`condition_time` increased monotonically from `156226` to `156291`
seconds, confirming that the client remained in the same offline inventory
state throughout the run.

Final classification:

`INVENTORY_ONLINE_DROPPED`

## Static + live interpretation

Runs 149–151 proved:

```text
HostInfo.online = client_status[+0x84]
```

and:

- fresh add/update reports set or refresh the client record,
- an existing offline client receiving a fresh report is explicitly returned
  to `online=1`,
- `client_status+0x88` is refreshed as last-seen,
- the watchdog clears `online` after 45 seconds without refresh.

Therefore this live result is stronger than merely observing zero rates:

**during the 65-second test, confsrv did not process any fresh device_list
report for this MAC that reached update_client_info_to_hash_table().**

If such a report had been processed, the existing offline record would have
been switched back to `online=1` immediately.

The rate helper is therefore behaving exactly as reverse engineered:

```text
HostInfo.online == 0
    -> fill_host_lists_rate skips client
    -> uprate/downrate remain 0
```

This run moves the root-cause investigation upstream from rate accounting to
the device inventory reporting pipeline.

## Next target

Trace the producer and scheduler of `device_list_upload` / client-list
publication:

- periodic timer vs event-driven trigger,
- local master vs satellite behavior,
- report cadence,
- conditions suppressing upload,
- command/Redis channel used to reach `confctl_device_list_upload`.

The rate/g_ip_info path should not be the primary target again until fresh
inventory reporting is restored or bypassed.
