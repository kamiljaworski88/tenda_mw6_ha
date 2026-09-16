# `device_list` reverse-engineering notes

Source binary examined: `latonita/tenda-reverse/RootFS-unpacked/bin/device_list` from the public MW6 HW2.1 firmware dump.

## Binary metadata

- ELF executable, MIPS/Linux
- size: 72,264 bytes
- dynamically linked
- full MIPS disassembly produced by the repository GitHub Actions workflow on 2026-09-16

## Relevant linked APIs

`device_list` imports `cmd_init`, `cmd_pub`, `cmd_sub`, Redis/CM infrastructure and the DHCP/Wi-Fi/netlink helpers described below. This confirms an event-driven client inventory process using Tenda's internal command bus.

## Decoded `cmd_pub()` call sites

The MIPS disassembly removes an important uncertainty. `cmd_pub` is called with the standard three-argument shape:

```c
cmd_pub(key, buffer, length)
```

The client-upload path resolves the first argument to the firmware string:

```text
confctl_srv_key
```

Both `do_upload_client_list()` and `do_upload_one_client()` publish to this key.

### `do_upload_client_list()`

The function receives a client-array pointer and count. Its size arithmetic contains:

```text
count * 124 + 68
```

and it copies exactly `124` bytes for each client record into the outgoing message. Immediately before `cmd_pub()` it prepares the message length and calls:

```text
cmd_pub("confctl_srv_key", message, message_length)
```

This is now directly recovered from the call site rather than inferred from strings.

### `do_upload_one_client()`

The single-client function allocates `192` bytes, copies one client structure of exactly `124` bytes, sets the outgoing message length to `156`, and publishes it through the same `confctl_srv_key`.

Several 32-bit fields in the copied record are converted with `htonl`, proving the message is a binary network-order structure rather than JSON/protobuf at this boundary.

Observed client-record offsets touched near publication include `+92`, `+96`, and `+100`. Importantly, `+100` is transformed using the current time and `+96` is subsequently set to `1` in the source record. This means those fields must not yet be labelled as upload/download rate without stronger evidence.

## Subscription side

`device_list` also calls `cmd_sub()` during initialization. The subscriber name is formatted from the visible firmware string:

```text
device_list@%s
```

The callback is `device_list_cmd_sub`. This gives us both sides of the internal bus: a named subscriber/callback and a concrete publication key.

## Client-list symbols / sources

Relevant symbols include:

```text
find_in_client_mac_list
alloc_device_client_info
g_client_hs_list
do_upload_one_client
do_upload_client_list
dhcp_nl_event_handle
wifi_get_vap_client_lists
get_all_wireless_client
update_to_roam_list
init_device_node_sn
convert_conn_type_from_ifname
```

Firmware scripts additionally expose `/proc/wlan*/sta_info`, mesh association/routing procfs files, DHCP leases and conntrack. This matches the binary's client identity/node pipeline.

## Critical conclusion about rates

The 124-byte `device_list` record is now real and its transport is understood, but the disassembly does **not** justify treating fields `+92/+96/+100` as download/upload rates. The code around `+100` behaves like time/age state, and `+96` behaves like a flag.

That pushes the project's rate target back to the separate cloud-info/BM path, for which the firmware logs contain:

```text
fill_cloud_info_device_lists_rate
NULL == g_ip_info
```

and the kernel initializes an `online_ip` hash table/proc file through the BM subsystem.

Current best model:

```text
DHCP/Wi-Fi/netlink -> device_list -> 124-byte identity/state record
                              |
                       confctl_srv_key
                              |
                        cloud-info
                              +---- BM online_ip / g_ip_info
                                         |
                                  per-client rates
```

This explains why the official app can receive richer device data than the base `device_list` record alone.

## Cloud-info correlation

The same firmware registers:

```text
M_CLOUD_INFO[8]
CMD_CLOUD_INFO_DEV_UPLOAD_DEVIC[18]
CMD_CLOUD_INFO_DEV_UPLOAD_STATU[20]
```

These remain upload-side/cloud semantics and are **not** candidates for speculative live GET requests.

## Next target for the Home Assistant goal

1. Locate the code/library containing `fill_cloud_info_device_lists_rate()` and recover the `g_ip_info` structure.
2. Recover the exact procfs interface created by `bm_online_ip` and determine whether it exposes per-IP byte/rate counters locally.
3. Prefer that local read-only source for HA; use `device_list`/DHCP/Wi-Fi data for client identity and mesh-node mapping.
4. Only after download/upload values are positively mapped, implement `custom_components/tenda_mw6`.

## Safety

No unknown `M_CLOUD_INFO` upload command or router SET operation is sent during this research. The target is a read-only local data path suitable for Home Assistant.
