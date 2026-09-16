# `device_list` reverse-engineering notes

Source binary examined: `latonita/tenda-reverse/RootFS-unpacked/bin/device_list` from the public MW6 HW2.1 firmware dump.

## Binary metadata

- ELF executable, MIPS/Linux
- size in the public firmware tree: 72,264 bytes
- dynamically linked

The binary's dynamic strings/symbol table gives substantially stronger evidence about the client inventory pipeline than the boot log alone.

## Relevant linked libraries / APIs

Observed strings include:

```text
libapmib.so
librtlWifiSrc.so
libcommonprod.so
libcm.so
libredis.so
libcmdctl.so
```

Relevant imported/runtime symbols include:

```text
cmd_pub
cmd_sub
cmd_init
cm_init
cm_run
cm_poll_start
cm_poll_stop
redis_option_new
init_unix_socket_server
netlink_usr_socket_init
netlink_sock_deinit
ugw_accept_client
ugw_proc_recv_msg
```

This strongly suggests `device_list` is event driven and exchanges data through internal command/pub-sub infrastructure; `libredis.so` is linked, but this does not imply that the externally exposed TCP/12598 service speaks raw Redis RESP.

## Client-list symbols

The binary exposes highly relevant symbol names:

```text
g_device_list_debug_en
g_mac_hdr
find_in_client_mac_list
alloc_client_mac
g_client_hs_list
find_in_client_hs_list
alloc_device_client_info
g_client_hs_list_num
add_to_client_hs_list
do_upload_one_client
convert_conn_type_from_ifname
del_from_client_hs_list
free_client_hs_list
free_lan_ifname_list
print_lan_ifnames_list
check_in_wifi_client_lists
g_node_sn
init_conn_type_list_hdr
do_client_timeout_check
do_upload_client_list
lan_ifnames_change_handle
del_client_belong_ifname
dhcp_nl_event_handle
init_lan_ifnames
init_client_hs_list
init_device_node_sn
wifi_get_vap_client_lists
ifaddrs_ethaddr_ntoa
find_in_conn_type_list
update_new_mac_list
print_wifi_client_lists
update_to_roam_list
get_all_wireless_client
del_roam_not_in_wifi_client_lists
print_all_wifi_client_lists
get_each_conn_type_list_hdr
print_one_conn_type_list
```

## Current model of the firmware pipeline

The symbols support the following working model:

```text
DHCP/netlink events -----------+
                               |
Wi-Fi VAP client lists --------+--> client MAC / host-state lists
                               |        |
LAN interface changes ---------+        +--> connection type / roaming state
                                        |
                                        +--> do_upload_one_client()
                                        +--> do_upload_client_list()
                                                   |
                                             cmd_pub / libredis
                                                   |
                                             cloud-info / ucloud
```

This model is evidence-based but the exact internal channel name and serialized payload format still need to be recovered.

## Cloud-info correlation

A repository-wide search of the same firmware boot log confirms two separately registered commands in module `M_CLOUD_INFO[8]`:

```text
CMD_CLOUD_INFO_DEV_UPLOAD_DEVIC[18]
CMD_CLOUD_INFO_DEV_UPLOAD_STATU[20]
```

The boot log also emits:

```text
[fill_cloud_info_device_lists_rate][2600][luminais] NULL == g_ip_info
```

This is an important correlation: the cloud-info implementation contains an explicit `device_lists_rate` path and a global `g_ip_info`, while `device_list` independently maintains client/MAC/connection-state lists and has upload functions. It strengthens the hypothesis that per-client rate information is assembled for cloud-info rather than being part of the already-tested `M_MESH_ADVANCE/QOS_GET` response.

What is *not* proven yet: command 18 or 20 is not known to be a safe client GET. Their names and registration indicate upload/status semantics and they must not be sent speculatively to the live router.

## Library triage

Firmware-tree inspection identifies the cloud-side libraries/processes around this path, including `libcloud.so`, `libucapi.so`, `libcmdctl.so`, `libredis.so`, and the `ucloud` process. Dynamic-symbol inspection of `device_list` already proves its dependency on `cmd_pub`/`cmd_sub` and Redis-related infrastructure.

The next reverse-engineering target is therefore the internal message boundary rather than random TCP/9000 command IDs:

1. recover the arguments/call site of `do_upload_client_list()` and `do_upload_one_client()`;
2. identify the `cmd_pub()` module/command or topic used by those functions;
3. map the serialized client structure, especially IP/MAC, online state, connection type/node and upload/download rate;
4. correlate that structure with a passive official-app TCP/9000 capture;
5. only after a read-only request is positively identified, implement it in the Home Assistant client.

## Why this matters for Home Assistant

The most promising non-cloud route is no longer to guess TCP/9000 command IDs. We should identify the internal message published by `do_upload_client_list()` / `do_upload_one_client()` and determine whether an authenticated read-only TCP/9000 operation used by the official app exposes the same structure.

A second path is passive capture: trigger the official app's device-list screen while capturing TCP/9000. That can reveal the exact module/command and payload without probing unknown commands.

## Safety

Do not invoke unknown `M_CLOUD_INFO` commands against a production mesh merely because their names contain `DEV_UPLOAD`. Upload/status commands may have side effects or may be router-to-cloud notifications rather than client GET operations.
