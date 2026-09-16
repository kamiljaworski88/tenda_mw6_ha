# MW6 internal IPC / rate-data reverse engineering

This note tracks the local path behind TCP/12598, `cmdsrv`, `confsrv`, `device_list`, and per-client rate data in the public MW6 HW2.1 firmware dump.

## TCP/12598 transport — confirmed

The firmware starts:

```text
redis-server /etc_ro/redis.conf
cmdsrv -l tcp://0.0.0.0:12598 -R tcp://127.0.0.1:6379
```

Redis itself is loopback-only (`127.0.0.1:6379`). Port 12598 is the Tenda `cmdsrv` frontend.

Static reverse engineering of `libredis.so` recovered the framing used on the `-l` listener. It is not cryptographic encryption. A frame is:

```text
u32le frame_len = compressed_len + 8
u32le xxh32(compressed_lz4_block, seed=0)
u32le uncompressed_len
bytes  compressed_lz4_block
```

The decompressed block is:

```text
RESP payload || f7 c6 89 be
```

`redis_reader_feed()` performs the inverse checks/decompression. This framing is implemented by `tools/mw6_cmd_client.py`; a live `PING` through TCP/12598 returned `+PONG`, validating the reconstruction.

## Internal command bus

Processes use `libcmdctl.so` (`cmd_get`, `cmd_set`, `cmd_pub`, `cmd_sub`) on top of Redis semantics. `device_list` publishes client inventory to `confctl_srv_key`; its upload message is named `device_list_upload`.

The client upload accepted by `confsrv` is a 32-byte message header followed by N client records of 124 bytes. The `device_list` subscriber channel is formatted as `device_list@%s`; its callback handles `rsp_client_hostname`, so subscribing to `confctl_srv_key` does not itself request a fresh client list.

## Local GetHostList path — confirmed

`confsrv` registers a command named exactly:

```text
GetHostList
```

with handler:

```text
confctl_get_host_list
```

The handler constructs `HostLists` / repeated `HostInfo` protobuf data and returns a packed response through the command framework. Its output path uses the protobuf symbols:

```text
host_info__init
host_lists__descriptor
host_lists__get_packed_size
host_lists__pack
```

The handler allocates an array based on the current client count and a per-host working structure of 56 bytes (`count * 56`) before filling the protobuf representation.

The firmware debug strings for the host model explicitly expose:

```text
ipaddr
ethaddr
name
assoc_sn
condition_time
access
signal
uprate
downrate
upload_type
up_time
interface_name
host_name
```

This is the strongest local API target for the Home Assistant integration.

## Per-client rate source — confirmed path

The rate path is local and originates from the firmware traffic statistics layer:

```text
netlink_get_statistic_info()
        |
     g_ip_info
        |
find_client_in_online_ip_info()
        |
fill_host_lists_rate()
        |
HostInfo.uprate / HostInfo.downrate
```

The kernel also exposes `/proc/net/online_ip` (used by firmware diagnostics), while `netlink_get_statistic_info()` supplies the runtime structure consumed by `confsrv`.

Earlier disassembly shows 232-byte online-IP statistic records. Rate calculation uses pairs of 64-bit counters and elapsed time, then writes the two directional rates into the host representation. The exact numeric unit still needs live validation; field names `uprate` and `downrate` are confirmed by firmware strings.

## Secondary OL_HOSTS API

`libucapi.so` exports `uc_api_lib_ol_hosts_get_hdl_reg`, and the cloud/protobuf stack contains `ol_host_info`, `host_info_msg`, and `host_info_single_msg`. This provides a second reference for decoding the same online-host model, but the preferred HA route remains the local `confsrv` `GetHostList` request rather than Tenda cloud.

## Current implementation rule

The production mesh must only receive a request after the exact read-only command-bus request shape has been reconstructed. Unknown command IDs, SET operations, cloud upload operations and arbitrary publishes are not used.

## Current research priority

1. Trace `confcli` and `cmdctl_test` to recover the exact `cmd_get` argument layout and destination key for `GetHostList`.
2. Decode the request/reply correlation key used by `libcmdctl`.
3. Reconstruct `HostLists` / `HostInfo` protobuf field numbers.
4. Add a read-only `clients` operation to `tools/mw6_cmd_client.py`.
5. Validate once against the live MW6, then use the result as the data source for `custom_components/tenda_mw6`.
