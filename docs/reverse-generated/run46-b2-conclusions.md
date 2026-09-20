# Run 46 — B2 conclusions

Scope: resolve the callback used by the two `cmd_sub` calls in `confcli` and narrow the dynamic subscription key construction.

## Confirmed

- `confcli` performs two `cmd_sub` calls in `main`.
- The callback argument loaded immediately before the first subscription comes from GOT slot `gp-32688`.
- Using the already established `confcli` GP (`0x45c140`), that slot is `0x454190`.
- The GOT contents at `0x454190` are `0x00407210`.
- Symbol `0x00407210` is `conf_msg_hander`.

Therefore both subscription paths are dispatched through `conf_msg_hander`.

## Dynamic key path

The first subscription key is constructed in the stack buffer at `sp+32` immediately before `cmd_sub`. The nearby format string is `%s@%s`, and the binary contains the string `confctl_cli`, so the dynamic subscription has the form `confctl_cli@<runtime-id>`.

Run 46 did not yet identify `<runtime-id>` with enough confidence. The next narrow step is to resolve the function called at GOT `gp-31836` and the constant string at virtual address `0x432314`, which feed the buffer used by the formatter before `cmd_init/cmd_sub`.

No router probe or Python behavior change is justified until that identifier source is resolved.