# Tenda MW6 Home Assistant

Reverse engineering and Home Assistant integration for Tenda Nova MW6.

## Confirmed test environment

- Router: Tenda Nova MW6
- LAN gateway: `192.168.5.1`
- Firmware observed: `V1.0.0.32(9821)`
- Local proprietary API: TCP `9000`
- UPnP/IGD: TCP `5500`
- Additional internal bridge: TCP `12598`

## Confirmed TCP/9000 protocol

The official Tenda application uses a binary protocol with a 16-byte header.

Observed header layout:

- byte 0: `0x24`
- byte 2: `0x07` request / `0x06` response
- byte 3: transaction ID
- bytes 4-5: `00 d5`
- bytes 6-7: payload length, big endian
- byte 8: module
- byte 9: command

Confirmed read-only commands:

| Module | Command | Name | Result |
|---|---:|---|---|
| `0x18` (24) | `0x00` | `M_MESH_AUTH / GET_STA` | works |
| `0x18` (24) | `0x01` | `M_MESH_AUTH / LOGIN` | works |
| `0x14` (20) | `0x00` | `M_MESH_HOSTS / GET` (`GetHostList`) | works; returns HostLists |
| `0x17` (23) | `0x08` | `M_MESH_ADVANCE / QOS_GET` | global QoS config |
| `0x17` (23) | `0x0f` | `M_MESH_ADVANCE / HIGH_DEVICE_GET` | high-priority-device state |
| `0x12` (18) | `0x08` | `M_MESH_WAN / GetTrafficInfo` | aggregate WAN traffic |

## Confirmed HostInfo protobuf schema

Firmware strings from `onhosts.pb-c.c` and live TCP/9000 captures map the HostInfo fields as follows:

| Field | Name |
|---:|---|
| 1 | `ipaddr` |
| 2 | `ethaddr` |
| 3 | `access` |
| 4 | `assoc_sn` |
| 5 | `condtion_time` |
| 6 | `online` |
| 7 | `uprate` |
| 8 | `downrate` |
| 9 | `signal` |
| 10 | `name` |

The local HostLists response therefore already gives the integration a stable source for IP, MAC, client name, associated mesh-node serial and Wi-Fi signal.

### Important rate caveat

On the tested MW6 firmware, fields `online`, `uprate` and `downrate` were observed as zero even while the client was active and generating heavy traffic. Firmware disassembly proves that rate calculation exists internally and uses two snapshots of kernel per-client counters, but the live path still needs one more reverse-engineering step before these values can be exposed as trustworthy Home Assistant entities.

## Home Assistant integration status

A HACS-compatible custom integration now exists in:

```text
custom_components/tenda_mw6/
```

Current behavior:

- local-only communication with the MW6 master on TCP/9000,
- 10-second coordinator polling,
- authentication using a previously captured successful LOGIN payload,
- one HA device per discovered client MAC,
- signal sensor,
- IP-address diagnostic sensor,
- associated mesh-node serial diagnostic sensor,
- automatic creation of entities for clients discovered after integration startup,
- raw `online/uprate/downrate` values kept only as diagnostic attributes until live semantics are reliable.

The integration intentionally does not depend on Tenda cloud services.

## Current research target

The remaining blocker for the original project goal is reliable per-client traffic. Firmware reverse engineering has already identified:

- `device_list`, `confsrv`, `libcommon` and kernel online-IP statistics,
- `fill_host_lists_rate`,
- `netlink_get_statistic_info`,
- 232-byte online-IP records,
- two-snapshot rate calculation with a ~500 ms interval,
- writes into the internal HostInfo `uprate/downrate` fields.

Next work should focus on why the live HostLists path does not receive the populated rate values, not on brute-forcing unrelated command IDs.

## Safety rule

Development probes issue only confirmed read-only operations. Unknown SET commands are not used against the production mesh.
