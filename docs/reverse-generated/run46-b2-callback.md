# Run 46 B2 — confcli subscription callback

Scope: identify only the callback passed to the two `cmd_sub` calls in `confcli` main.

## Result

`confcli` uses the same callback for both subscriptions. In `main`, both `cmd_sub` calls load the callback pointer from GOT offset `-32688(gp)`.

For `main`:

- `gp = 0x45c140`
- `gp - 32688 = 0x454190`
- GOT word at `0x454190` = `0x00407210`
- symbol at `0x00407210` = `conf_msg_hander`

Therefore the callback for both subscriptions is:

`conf_msg_hander` (`0x00407210`)

This closes only the callback part of B2. The runtime identifier used to build `confctl_cli@<id>` is intentionally left for the next micro-step.
