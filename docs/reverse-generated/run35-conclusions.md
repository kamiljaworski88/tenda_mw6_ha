# Run 35 conclusions — per-client traffic path

Run 35 completed successfully and narrows the MW6 per-client traffic path enough to move from broad firmware exploration to implementation/testing.

## Confirmed

- `GetHostList` invokes the local host-rate helper at `0x434258`.
- That helper invokes `netlink_get_statistic_info()` twice and computes deltas from 64-bit counters.
- The two samples are separated inside firmware by the delay path identified in run 34; the caller does not need to take two separate `GetHostList` samples just to make the firmware calculate a rate.
- Per-host statistics are matched against the online-IP/statistics structure before rate values are produced.
- Two independent 64-bit counter-delta paths are converted to rate values.
- The resulting two per-host values are stored in the HostInfo working structure at offsets `+36` and `+40`.
- A parallel runtime/device-client path writes the corresponding rate values into offsets `+0x98` and `+0x9c`, with presence flags `0x4` and `0x8`.
- The firmware/protobuf strings explicitly contain `uprate` and `downrate`, so the two values are upload/download rates rather than unrelated counters.
- The entire calculation is local; Tenda cloud is not required for the rate calculation itself.

## Still requiring live confirmation

Static analysis does not yet justify assigning `+36` vs `+40` (or `+0x98` vs `+0x9c`) to upload/download with 100% confidence. The protobuf descriptor field numbers and display units also still need to be tied to a known live transfer direction.

The earlier live test where GetHostList rate fields stayed zero under heavy traffic therefore points to the host-to-`g_ip_info` matching/eligibility path, not to missing sampling in the client program.

## Implementation decision

Do not add another generic command scanner. The next useful step is a dedicated read-only `clients` implementation that:

1. sends the already-recovered GetHostList request,
2. decodes HostLists/HostInfo,
3. exposes both raw rate candidates without prematurely swapping labels,
4. prints MAC/IP/name/node/online information alongside the two rate fields,
5. allows one controlled live transfer test to establish direction and unit,
6. then freezes the mapping for the Home Assistant integration.

After that validation the Home Assistant component can poll locally every 5–10 seconds and derive daily/monthly totals in HA if the firmware does not expose reliable cumulative per-client counters.
