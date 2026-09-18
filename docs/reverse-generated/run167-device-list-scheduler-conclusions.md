# Run 167 — device-list scheduler conclusions

Run 162 proved live that the selected client remains in the central offline
inventory state even while the router sees WAN traffic. Runs 163–168 trace the
producer side far enough to define the next runtime split without returning to
the rate-accounting path.

## Confirmed scheduler

`start_device_list_timer` registers two repeating timer events:

- ID 3: 10,000 ms, client timeout/maintenance;
- ID 4: 20,000 ms, client-list upload.

The event dispatcher switches on IDs 3 and 4. Run 168 resolves the ID-4 GOT
targets directly as `g_client_hs_list`, `g_client_hs_list_num`, and
`do_upload_client_list`. The branch calls
`do_upload_client_list(g_client_hs_list, g_client_hs_list_num)` and then rearms
timer 4 for another 20 seconds.

The timer worker is monitored by `timer_check_ok_and_wait`; the main process
restarts the device-list timers when the worker is unavailable.

## Confirmed publication

`do_upload_client_list` builds:

```text
32-byte reporting-node identity
+ N * 124-byte client records
```

and publishes it through `cmd_pub` under `device_list_upload`.

The central handler consumes this exact shape, merges by client MAC, refreshes
`last_seen`, sets `online=1`, and exports the reporting node as
`HostInfo.assoc_sn`.

## Consequence for the live failure

The 20-second publication interval is comfortably shorter than the 45-second
central offline watchdog. A client that remains offline for the whole
65-second diagnostic cannot be explained by the nominal timer cadence.

The remaining high-value distinction is:

- all records associated with the same `NODE_SN` are stale: node-wide local
  collection, `cmd_pub`, or delivery/merge failure;
- another record associated with the same `NODE_SN` is refreshed: the node's
  reports arrive, so focus on target enumeration, its ARP resolution, local
  list membership, or a stale target `assoc_sn`;
- no peer exists for the same `NODE_SN`: one more control client on that node
  is required.

The read-only `--diagnose-inventory` mode now performs this comparison for at
least 45 seconds and prints a deterministic classification.
