# Run 177 — no existing shell listener and no remote process-status API

## Live observation

The read-only shell-surface probe against `192.168.0.1` performed TCP connect
and banner-read attempts only. It sent no credentials and no commands.

| Port | Expected service | Result |
| ---: | --- | --- |
| 22 | SSH | timeout |
| 23 | Telnet | timeout |

Classification: `NO_EXISTING_SHELL_LISTENER`.

## Static follow-up

Run 176 scanned the firmware for callers of local process inspection helpers
and for process/status diagnostics in network-facing binaries and web/config
assets. The helpers exist in `libcommon.so` and are used by internal processes,
but no read-only HTTP, TCP/9000, or web-UI process-status endpoint was found.

`netctrl` contains a Telnet service-control path. Using it would alter router
state, so it is deliberately excluded from the passive diagnostic plan.

## Consequence

The fault is still bounded to the gateway-local
`timer → device_list → cmd_pub` chain, with these unresolved branches:

1. `timer` or `/var/tm_socket` unavailable;
2. timer IDs 3/4 not registered or not restored after restart;
3. timer event ID 4 not delivered to `device_list`;
4. `do_upload_client_list` or `cmd_pub` failing before publication.

The confirmed remote read-only interfaces cannot distinguish those branches.
Further live isolation needs a separately authorized local/physical diagnostic
channel or a vendor-supported read-only log export. Enabling a shell solely for
this investigation is not justified.
