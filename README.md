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

Firmware strings from `onhosts.pb-c.c` and live captures map the HostInfo fields as follows:

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

### Per-client rate pipeline

Static firmware analysis now resolves the complete rate path:

- `online != 0` is the gate before rate calculation,
- the client is matched to `g_ip_info` by strict MAC **and** IPv4,
- upload counters are read from the record group at `+0x18/+0x20`,
- download counters are read from `+0x28/+0x30`,
- two snapshots are taken roughly 500 ms apart,
- byte deltas are divided by elapsed seconds and by `1024`,
- exposed `uprate` / `downrate` values are integer KiB/s.

The remaining runtime issue is that some live HostLists responses still return zero `online/uprate/downrate` values. The most likely failure point is now the live population/matching of the strict IP+MAC pair in `g_ip_info`, not the protobuf schema, direction mapping or unit.

## Differential runtime probe

`tools/mw6_compare_host_sources.py` compares the same clients through both confirmed local paths:

1. authenticated TCP/9000 `M_MESH_HOSTS/GET`,
2. TCP/12598 `cmdsrv -> confsrv -> GetHostList`.

This test is specifically intended to tell us whether `online/uprate/downrate` are being lost on only one API path or are already zero in the shared runtime data.

Example:

```powershell
python .\tools\mw6_compare_host_sources.py `
  --pcap .\PCAPdroid_16_wrz_11_20_35.pcap `
  --host 192.168.5.1 `
  --count 5 `
  --interval 3
```

While it runs, generate traffic on one known client. The script prints paired `9000` and `12598` rows by MAC and marks fields that differ. The captured LOGIN payload is never printed.

## Home Assistant integration status

A HACS-compatible custom integration exists in:

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
- raw `online/uprate/downrate` values kept only as diagnostic attributes until live runtime behavior is reliable.

The integration intentionally does not depend on Tenda cloud services.

## Current research target

The remaining blocker for the original project goal is reliable per-client traffic. The next decision depends on the differential probe:

- if TCP/12598 has valid online/rates while TCP/9000 remains zero, move the HA coordinator to the cmdsrv/confsrv backend;
- if both paths return zero, investigate runtime `g_ip_info` population and the strict IP+MAC matcher;
- only after non-zero live rates are reproducible should upload/download sensors and daily/monthly integration be enabled in HA.

## Safety rule

Development probes issue only confirmed read-only operations. Unknown SET commands are not used against the production mesh.
