# Run 37 — GetHostList RPC and rate-gate conclusions

## RPC transport

`GetHostList` does **not** use the random `cmdrpc@...` reply channel mechanism from `libcmdctl`'s synchronous `cmd_get` helper.

The `confcli`/`confsrv` path uses the fixed command bus:

- request channel: `confctl_srv_key`
- reply/event channel: `confctl_cli_key`
- envelope: 32-byte NUL-padded command name + little-endian uint32 payload length + payload

For the read-only client the correct sequence is therefore:

1. `SUBSCRIBE confctl_cli_key`
2. `PUBLISH confctl_srv_key <GetHostList envelope>`
3. wait for a `GetHostList` envelope on `confctl_cli_key`

Subscribing before publishing avoids losing a fast response.

## Resolved HostInfo fields

The active decoder is `tools/mw6_hostinfo.py`:

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

`tools/mw6_cmd_client.py clients` now imports this decoder instead of maintaining a second unresolved protobuf decoder.

## Rate processing gate

The rate helper checks runtime HostInfo offset `+0x20` before processing a client. A zero value skips the rate path for that client.

The current reverse mapping associates this slot with the condition-time/runtime eligibility path represented by `condtion_time` in HostInfo. The live diagnostic therefore reports whether that value is non-zero, but does not claim that this alone proves rate calculation will succeed.

If `condtion_time` is non-zero and `uprate/downrate` still remain zero under known traffic, the next target is the lookup/matching step against `g_ip_info` / `/proc/net/online_ip` (IP/MAC identity and interface-specific conditions).

## Safe live diagnostic

Use:

```powershell
python .\tools\mw6_cmd_client.py --host 192.168.5.1 clients --pretty --diagnose-rates --raw-out gethostlist.bin
```

This performs only the dedicated read-only GetHostList operation.
