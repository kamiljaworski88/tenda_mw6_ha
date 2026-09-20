# Run 116 conclusions — per-client traffic source

## Result

The separate cloud `DEV_TRAFFIC` path is not a useful alternate source for the Home Assistant integration on the analysed MW6 firmware.

Run 114 resolved `cmd_cloud_info_dev_traffic_upload` in `libcloud.so` as a registered cloud command handler. The function mainly packages data already supplied by its caller through `dev_traffic_upload_json_packer` and forwards the packed command. It does not calculate per-client rates itself.

Run 115 resolved `uc_api_m_cloud_info_send_dev_traffic` in `libucapi.so` as a small wrapper around the generic UC API sender for module 8 / command 12.

Run 116 scanned every ELF in the unpacked root filesystem for `uc_api_m_cloud_info_send_dev_traffic`. The only dynamic-symbol hit is the definition inside `libucapi.so`; no other ELF imports it and there are no string-only references elsewhere. Therefore there is no statically linked runtime caller to follow on this firmware.

By contrast, `confsrv` does import and call `uc_api_m_cloud_info_send_dev_device`, including from `send_all_client_status_list`. This matches the already recovered path in which `confsrv` builds the client list, enriches it with `fill_host_lists_rate`, and sends device status.

## Project decision

Stop spending reverse-engineering time on the unused separate cloud `DEV_TRAFFIC` wrapper. It does not bypass the current local-rate problem.

The remaining useful path for the Home Assistant goal is still:

`GetHostList -> HostInfo online/IP/MAC -> strict match against g_ip_info/online_ip -> two rate snapshots -> uprate/downrate`

The next runtime test must distinguish whether the zero values are specific to one exposed API path or already present in the shared runtime data. Use `tools/mw6_compare_host_sources.py` to compare TCP/9000 and cmdsrv/12598 for the same MAC while that client generates traffic.

If both paths stay zero, the next reverse target is runtime population/matching of `g_ip_info`, not cloud transport.