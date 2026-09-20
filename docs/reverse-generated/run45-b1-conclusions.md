# Run 45 / B1 conclusions

Scope: only the `confcli` receive/dispatch path for configuration replies.

## Proven

- `confcli` imports `cmd_init`, `cmd_sub` and `cmd_pub`.
- `cmd_sub` takes `(channel, callback, arg)`; libcmdctl stores callback at offset +16 and arg at +20 in its subscription record before registering the subscription.
- `confcli` calls `cmd_sub` twice from `main`, with the same callback and `arg = NULL`.
- First subscription channel is built in a stack buffer from format `%s@%s`, literal `confctl_cli`, and a runtime identifier. Therefore this is a per-instance channel of the form `confctl_cli@<runtime-id>`.
- Second subscription channel is the fixed literal `confctl_cli_key`.
- Both subscriptions use the same callback pointer loaded from the same GOT slot.
- Incoming conf messages are dispatched by the generic `conf_msg_hander`, which parses the 36-byte command envelope and invokes a registered command callback.

## Important correction for the Python client

The current external design that subscribes only to fixed `confctl_cli_key` is incomplete: the native `confcli` process subscribes to *two* reply channels, including a generated per-instance channel.

## Still unresolved

The exact target of the shared callback GOT slot used by both `cmd_sub` calls has not yet been proven by address. It is very likely the generic conf-message subscription callback that leads into `conf_msg_hander`, but B1 does not promote that inference to fact.

The runtime identifier used in `confctl_cli@<runtime-id>` also needs exact identification before changing the Python request flow.
