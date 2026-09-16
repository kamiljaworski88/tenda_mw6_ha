# `cmdsrv` / `cmdctl_test` / `libcmdctl.so` binary notes

Firmware reference: public MW6 HW2.1 dump in `latonita/tenda-reverse`.

## Confirmed binary locations

```text
RootFS-unpacked/sbin/cmdsrv
RootFS-unpacked/sbin/cmdcli
RootFS-unpacked/sbin/cmdctl_test
RootFS-unpacked/lib/libcmdctl.so
```

All inspected files are MIPS ELF binaries.

## `cmdsrv`

The dynamic symbol/string table exposes both the generic socket/event layer and Redis protocol implementation:

```text
cm_io_listen
cm_io_accept
cm_io_read
cm_io_write
cm_io_close
redis_client_init
redis_client_execute
redis_client_try_execute
redisReaderInit
redisReaderFeed
redisReaderGetReply
subscribe_new
subscribe_register
subscribe_unregister
```

Together with the boot command:

```text
cmdsrv -l tcp://0.0.0.0:12598 -R tcp://127.0.0.1:6379
```

this establishes that 12598 terminates a Tenda command-service protocol and `cmdsrv` talks to the loopback Redis backend itself. It is not a raw Redis proxy.

## `cmdctl_test`

The test executable imports:

```text
cmd_init
cmd_sub
cmd_pub
cmd_set
cmd_get
redis_option_new
redis_client_init
redis_client_execute
```

It also contains JSON/cJSON support. This makes it a useful reference implementation for the public surface of `libcmdctl`.

## `libcmdctl.so`

Direct ELF inspection confirms the library exports/contains the command API and its transport handlers:

```text
cmd_init
cmd_sub
cmd_unsub
cmd_pub
cmd_set
cmd_get
cmd_on_connect
cmd_on_close
cmdsh_random_key
```

It imports Redis reader/writer operations, `subscribe_new/register/unregister`, and `cm_io_connect/read/write/close`.

A particularly useful finding is `cmdsh_random_key`: the command layer has an explicit request-correlation/key mechanism rather than being a thin text passthrough. This is another reason not to guess packets for TCP/12598.

## What this proves

The local IPC path can now be stated more precisely:

```text
application process
  cmd_get / cmd_set / cmd_pub / cmd_sub
              |
         libcmdctl.so
     correlation + framing
              |
        Redis semantics
              |
  local Redis / cmdsrv bridge
```

`device_list` imports the same `cmd_init/cmd_pub/cmd_sub` family. Therefore the next useful artifact is not another live port probe: it is the call-site argument layout around `cmd_pub()` inside `device_list`, compared with `cmd_get/cmd_sub` examples in `cmdctl_test`.

## Safety / implementation rule

For the Home Assistant integration we only want a read-only GET or passive SUB path. `cmd_set`, cloud upload commands and guessed write requests remain out of scope until their semantics are fully decoded.

## Next decode target

1. Materialize the four ELF files locally.
2. Run MIPS-aware `readelf`/`objdump` (or Ghidra/rizin) on `cmdctl_test` and `device_list`.
3. Locate PLT/GOT calls to `cmd_get`, `cmd_sub`, and `cmd_pub`.
4. Recover MIPS ABI arguments (`$a0`..`$a3`, plus stack arguments) at each call site.
5. Identify constant strings/IDs passed to those functions.
6. Build a read-only Python client only after the wire format/topic is known.
