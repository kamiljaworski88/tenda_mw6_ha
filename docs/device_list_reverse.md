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
                                             ucloud/cloud-info
```

This model is evidence-based but the exact channel names and serialized payload format still need to be recovered.

## Why this matters for Home Assistant

The most promising non-cloud route is no longer to guess TCP/9000 command IDs. We should identify the internal message published by `do_upload_client_list()` / `do_upload_one_client()` and determine whether an authenticated read-only TCP/9000 operation used by the official app exposes the same structure.

A second path is passive capture: trigger the official app's device-list screen while capturing TCP/9000. That can reveal the exact module/command and payload without probing unknown commands.

## Safety

Do not invoke unknown `M_CLOUD_INFO` commands against a production mesh merely because their names contain `DEV_UPLOAD`. Upload/status commands may have side effects or may be router-to-cloud notifications rather than client GET operations.
