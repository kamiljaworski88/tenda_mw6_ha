# MW6 protocol notes

## TCP/9000

This document records only behavior confirmed from packet capture and read-only tests against an MW6 running `V1.0.0.32(9821)`.

### Frame

Requests observed from the official application use a 16-byte header followed by an optional payload.

```text
24 00 07 TT 00 d5 LL LL MM CC 00 00 01 00 00 00 [payload]
```

Where:

- `TT` = transaction ID
- `LL LL` = payload length, big endian
- `MM` = module
- `CC` = command

Responses use `0x06` instead of request byte `0x07`.

### Authentication

Module `0x18` is `M_MESH_AUTH`.

- command `0x00`: `GET_STA`
- command `0x01`: `LOGIN`

Observed `GET_STA` response payload:

```text
00 00 00 00 08 02
```

A successful LOGIN response contains a four-byte zero result payload:

```text
00 00 00 00
```

The login credential/token is intentionally not stored in this repository.

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

Observed on the tested MW6 gateway:

- `5500/tcp`: UPnP/IGD. Useful for aggregate WAN information, not per-client traffic.
- `9000/tcp`: proprietary application protocol.
- `12598/tcp`: accepts TCP but does not speak Redis RESP directly. A Redis `PING` caused the service to close without a response.

## Firmware research direction

Public reverse engineering of the MW6 firmware shows a separate `device_list` process and cloud/device upload logic. That path is a stronger candidate for the connected-client inventory than `M_MESH_ADVANCE/QOS_GET`.

Research should map a named, confirmed read-only command before any additional active probing.
