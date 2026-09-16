# Tenda MW6 Home Assistant

Reverse engineering and Home Assistant integration for Tenda Nova MW6.

## Confirmed test environment

- Router: Tenda Nova MW6
- LAN gateway: `192.168.5.1`
- Firmware observed: `V1.0.0.32(9821)`
- Local proprietary API: TCP `9000`
- UPnP/IGD: TCP `5500`
- Additional service: TCP `12598`

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

Confirmed commands:

| Module | Command | Name | Result |
|---|---:|---|---|
| `0x18` (24) | `0x00` | `M_MESH_AUTH / GET_STA` | works |
| `0x18` (24) | `0x01` | `M_MESH_AUTH / LOGIN` | works |
| `0x17` (23) | `0x08` | `M_MESH_ADVANCE / QOS_GET` | global QoS config, not client list |
| `0x17` (23) | `0x0f` | `M_MESH_ADVANCE / HIGH_DEVICE_GET` | high-priority-device state, not client list |

Successful `QOS_GET` response payload observed after authentication:

```text
00 00 00 00 08 01 10 80 c0 3e 18 80 c0 3e 20 00
```

The two protobuf-like varints `80 c0 3e` decode to `1,024,000`, consistent with QoS bandwidth configuration rather than per-client traffic.

`HIGH_DEVICE_GET` response:

```text
00 00 00 00 08 01
```

## Current research target

Do **not** brute-force command IDs. The current target is the firmware's device inventory/traffic path.

Firmware reverse-engineering evidence shows separate processes/services including:

- `device_list`
- `ucloud`
- `redis-server`
- `cmdsrv -l tcp://0.0.0.0:12598 -R tcp://127.0.0.1:6379`

Known cloud-info command names include device upload/status operations. The goal is to identify the read-only internal command/data structure that exposes connected clients and, if available:

- hostname
- IP address
- MAC address
- online state
- mesh node
- upload rate
- download rate
- cumulative traffic

## Safety rule

Development probes should issue only confirmed read-only GET operations. Do not probe unknown command numbers or send SET operations to a production mesh.

## Planned Home Assistant integration

Target structure:

```text
custom_components/tenda_mw6/
  __init__.py
  manifest.json
  config_flow.py
  const.py
  coordinator.py
  sensor.py
```

The integration should use local polling only and should not depend on Tenda cloud services.
