# MW6 protocol notes

## TCP/9000

This document records only behavior confirmed from packet capture and read-only tests against an MW6 running `V1.0.0.32(9821)`.

### Frame

Requests observed from the official application use a 16-byte header followed by an optional payload.

```text
24 00 07 TT 00 d5 LL LL MM CC 00 00 01 00 00 00 [payload]
```

Where `TT` is transaction ID, `LL LL` is big-endian payload length, `MM` is module and `CC` is command. Responses use `0x06` instead of request byte `0x07`.

### Authentication

Module `0x18` is `M_MESH_AUTH`: command `0x00` is `GET_STA`, command `0x01` is `LOGIN`.

Observed `GET_STA` response payload:

```text
00 00 00 00 08 02
```

A successful LOGIN response contains:

```text
00 00 00 00
```

The login credential/token is intentionally not stored in this repository.

### Login-token stability

Two independent PCAPdroid captures (`10:19:32` and `10:31:43`) contain the same two 36-byte LOGIN request payloads, including the payload that succeeds. This is important evidence that the successful credential payload is stable across those app sessions rather than a per-TCP-session challenge response. No secret/token bytes are stored here.

### M_MESH_ADVANCE

Module `0x17` is `M_MESH_ADVANCE`.

#### QOS_GET = command 0x08

Observed response:

```text
00 00 00 00 08 01 10 80 c0 3e 18 80 c0 3e 20 00
```

The response appears protobuf-like after the four-byte result/status prefix. Both `80 c0 3e` varints decode to `1,024,000`. This operation is therefore treated as global QoS configuration, not a client traffic list.

#### HIGH_DEVICE_GET = command 0x0f

Observed response:

```text
00 00 00 00 08 01
```

This is not a client list.

## Other exposed TCP services

- `5500/tcp`: UPnP/IGD; aggregate WAN information, not per-client traffic.
- `9000/tcp`: proprietary application protocol.
- `12598/tcp`: accepts TCP but does not speak Redis RESP directly; a Redis `PING` caused the service to close without a response.

## Firmware device-list evidence

Public MW6 reverse engineering contains the actual executable `RootFS-unpacked/bin/device_list` (72,264 bytes) and boot logs showing the process being started. The firmware log also contains `fill_cloud_info_device_lists_rate` and a `g_ip_info` pointer/state, directly linking cloud-info generation to a per-device rate data structure.

The ucloud command registry includes module `M_CLOUD_INFO[8]` and named commands:

- `CMD_CLOUD_INFO_MESH_NODE_A[14]`
- `CMD_CLOUD_INFO_DEV_UPLOAD_DEVIC[18]`
- `CMD_CLOUD_INFO_DEV_UPLOAD_STATU[20]`

These are stronger candidates for understanding the device inventory/traffic pipeline than blindly probing `M_MESH_ADVANCE` command IDs. Their names alone do not prove that they are safe client-initiated GET operations, so they must not be sent to a production router until direction and payload semantics are established.

## Research rule

Do not brute-force command IDs. Map a named, confirmed read-only operation or passively capture the official application's request before adding a new active probe.
