# Run 47 B4 — exact runtime-id config key

Micro-step result: the string at virtual address `0x432314`, used as the configuration key in the `GetValue` call that feeds the `%s@%s` construction for `confctl_cli@<runtime-id>`, is:

`serial.number`

Evidence from `confcli` `.rodata`:

- `0x432300`: `/mib.mem`
- `0x43230c`: `role`
- `0x432314`: `serial.number`
- `0x432324`: `%s%s`
- nearby: `node.location@`, `sys.model`

Conclusion: the dynamic subscription channel is built from the device serial number, i.e. effectively `confctl_cli@<serial.number>`.

This closes the identity portion of the native confcli subscription path. The next implementation step is to reproduce this channel naming in the Python client without guessing a random runtime identifier.
