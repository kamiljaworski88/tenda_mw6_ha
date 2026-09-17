# Run 37 — GetHostList RPC and rate-gate conclusions

## RPC transport

`GetHostList` does **not** use the random `cmdrpc@...` reply channel mechanism from `libcmdctl`'s synchronous `cmd_get` helper.

The request is published to:

- `confctl_srv_key`

Native `confcli` actually subscribes to two channels:

- fixed `confctl_cli_key`
- per-instance `confctl_cli@<serial.number>`

Later reverse-engineering resolved the dynamic suffix source as the `serial.number` configuration value. This does not invalidate the fixed-channel GetHostList client: the GetHostList request envelope is only the 32-byte command name, uint32 payload length and payload, and for this request the payload is empty. It carries no caller-specific reply key. The fixed `confctl_cli_key` remains the relevant shared reply/event bus for this request path; the per-instance subscription is also used by native confcli for directed events/messages.

The read-only Python sequence remains:

1. `SUBSCRIBE confctl_cli_key`
2. `PUBLISH confctl_srv_key <GetHostList envelope>`
3. wait for a `GetHostList` envelope

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

## Corrected rate processing gate

The rate helper checks runtime `HostInfo+0x20`. The exact 32-bit protobuf-c layout proves this is the `online` field, not `condtion_time`.

Equivalent firmware logic:

```c
if (!host->online)
    continue;
```

For an online host, firmware parses IP and MAC and performs a strict match against `g_ip_info`: MAC must equal the six bytes at record `+0x04` **and** IPv4 must equal the value at record `+0x00`. The record stride is `0xE8` bytes. A missing/stale pair skips rate calculation.

## Rate semantics

Subsequent reverse-engineering also resolves:

- `uprate` = upload rate
- `downrate` = download rate
- source counters are byte counters (`up_bytes` / `down_bytes`)
- elapsed microseconds are divided by `1,000,000`
- final byte/second result is divided by `1024`

Therefore `uprate` and `downrate` are integer **KiB/s** values (the original UI may label them KB/s).

## Safe live diagnostic

```powershell
python .\tools\mw6_cmd_client.py --host 192.168.5.1 clients --pretty --diagnose-rates --raw-out gethostlist.bin
```

This performs only the dedicated read-only GetHostList operation.
