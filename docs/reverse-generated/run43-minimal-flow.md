# Run 43 — minimal libcmdctl request/reply flow

## Scope
Small, focused conclusion from `cmdrpc-request-wire.txt` only. Goal: decide whether `T.54` is a hidden `cmdrpc@...` request/reply protocol that should replace the current `SUBSCRIBE + PUBLISH` implementation of `clients`.

## Confirmed

1. `cmd_pub`, `cmd_set`, and `cmd_get` are thin wrappers around the same internal helper `T.54` at `0x1868`.
2. `T.54` manually constructs a normal Redis RESP request. The disassembly shows literal `*` (`0x2a`), `$` (`0x24`) and CR/LF bytes, and switches between a 2-argument and 3-argument command form.
3. The helper sends the request through the existing `cm_io` connection and parses a normal Redis reply. This is the same command path used by the ordinary wrappers, not evidence of a separate wire protocol.
4. `cmdsh_random_key()` is real and generates a `cmdrpc@...` string from 24 bytes read from `/dev/urandom` and Base64 encoding.
5. Run 43 does **not** show `T.54` calling `cmdsh_random_key()` while executing ordinary `cmd_pub` / `cmd_get` / `cmd_set`. Therefore we should not yet implement `clients` by inventing a `cmdrpc@...` exchange.
6. The current Python `clients` failure remains explained by combining a subscription connection with a second command connection through `cmdsrv`; the correct request/reply mechanism for `GetHostList` must be recovered from the `confcli`/confsrv application layer, not guessed from `cmdsh_random_key()` alone.

## Decision
Do not modify production `clients` to a speculative `cmdrpc@...` protocol yet.

## Next focused task
Trace the exact response path used by `confcli` after publishing a `GetHostList` envelope: identify where its reply is stored/read and whether the reply is delivered through a unique key, fixed channel, or a local callback on the same command connection. Only after that should `mw6_cmd_client.py` be changed.
