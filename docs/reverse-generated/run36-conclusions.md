# Run 36 — resolved HostInfo schema

Firmware `libpb.so` / `onhosts.pb-c.c` exposes the HostInfo field names in descriptor order:

1. `ipaddr`
2. `ethaddr`
3. `access`
4. `assoc_sn`
5. `condtion_time` (firmware spelling)
6. `online`
7. `uprate`
8. `downrate`
9. `signal`
10. `name`

This resolves the previously neutral live fields `f7` and `f8`: they are respectively `uprate` and `downrate`. It also confirms that `f9` is RSSI/signal and `f10` is the client name.

The decoder implementation now lives in `tools/mw6_hostinfo.py`. It also provides normalized aliases intended for the future Home Assistant coordinator:

- `ip`
- `mac`
- `node_serial`
- `is_online`
- `upload_rate_raw`
- `download_rate_raw`

Rate *semantics* are now named, but rate *units* still require one controlled live transfer validation before exposing HA sensors with a unit. Existing firmware analysis shows rates are calculated from two kernel statistics snapshots separated by about 500 ms.

Next implementation target: wire this decoder into `mw6_cmd_client.py clients`, validate the exact command-bus response path on the router, then build the HA coordinator only after local GetHostList is reliably decoded.