# Run 179 — log export safety conclusion

## Finding

Run 178 found `DiagLogUpload` / `CMD_MESH_BASIC_UPLOAD_LOG` in the firmware,
but no local read-only log-download API.

The associated `log_upload` binary assembles diagnostic files under
`/tmp/log`, copies system and PPPoE logs, collects WLAN/crash material, sends a
bundle to Tenda's cloud route `/route/upload_logfile/v1?sn=...&mesh=...`, and
removes temporary material afterward.

## Decision

The command is not invoked because it has both local side effects and external
data transfer. It cannot be used as a passive replacement for shell access.

## Remaining boundary

The remotely confirmed read-only interfaces cannot distinguish whether the
missing periodic `device_list_upload` is caused by timer availability,
registration/re-registration, event delivery, or failure inside
`do_upload_client_list` / `cmd_pub`. Further live isolation requires a
separately authorized local or physical diagnostic channel.
