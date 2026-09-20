# Run 47 B3 — runtime-id source

Confirmed from confcli main and GOT mapping:

- main uses GOT slot `0x4544e4` immediately before building `%s@%s` / `confctl_cli`.
- `0x4544e4` contains `0x004317a0`.
- symbol `0x004317a0` is imported `GetValue`.

Therefore the `<runtime-id>` in `confctl_cli@<runtime-id>` is read from Tenda configuration via `GetValue(key, outbuf)`, not generated randomly and not read directly from the interface MAC helper.

The exact configuration key passed in `a0` is at VA `0x432314`; resolving that key is the next micro-step.
