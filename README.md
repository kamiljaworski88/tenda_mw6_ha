# Tenda MW6 Home Assistant

Reverse engineering and Home Assistant integration for Tenda Nova MW6.

## Confirmed test environment

- Router: Tenda Nova MW6
- LAN gateway: `192.168.5.1`
- Firmware observed: `V1.0.0.32(9821)`
- Kernel family: Linux 3.10.90 / RTL8197F / Realtek SDK v3.4.11B
- Local proprietary API: TCP `9000`
- UPnP/IGD: TCP `5500`
- Internal cmdsrv bridge: TCP `12598`

## Confirmed local HostList path

The official Tenda application uses the proprietary TCP/9000 protocol with a
16-byte header. The confirmed per-client command is:

| Module | Command | Name | Result |
|---|---:|---|---|
| `0x18` | `0x00` | `M_MESH_AUTH / GET_STA` | works |
| `0x18` | `0x01` | `M_MESH_AUTH / LOGIN` | works |
| `0x14` | `0x00` | `M_MESH_HOSTS / GET` / `GetHostList` | works; returns `HostLists` |
| `0x17` | `0x08` | `M_MESH_ADVANCE / QOS_GET` | global QoS config |
| `0x17` | `0x0f` | `M_MESH_ADVANCE / HIGH_DEVICE_GET` | high-priority-device state |
| `0x12` | `0x08` | `M_MESH_WAN / GetTrafficInfo` | aggregate WAN traffic |

TCP/12598 is a confirmed local `cmdsrv` transport for supported
Redis-backed commands, but **GetHostList does not provide a usable response
path through 12598**. Per-client HostList/rate work therefore stays on
authenticated TCP/9000.

## HostInfo schema

`HostInfo` protobuf fields are:

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

The local response already provides IP, MAC, client name, associated mesh-node
serial, online state and Wi-Fi signal.

## Per-client rate pipeline

Firmware analysis now resolves the end-to-end rate path:

`GetHostList → netlink_get_statistic_info → kernel online_ip → strict IP+MAC match → uprate/downrate`.

Confirmed details:

- `online != 0` is the HostInfo gate,
- matching against `g_ip_info` requires both IPv4 and MAC,
- kernel online-ip records carry upload/download byte counters,
- userspace takes two samples and computes byte deltas,
- `uprate` / `downrate` are integer KiB/s.

Packet direction metadata is also resolved:

- private skb bit `0x2` = client upload / LAN→WAN,
- private skb bit `0x1` = client download / WAN→LAN,
- LAN/Wi-Fi ingress sets upload,
- Realtek WAN VLAN id 8 sets the WAN-RX/download marker.

### FastPath accounting

Runs 143–144 prove that Tenda explicitly integrates NOS/TBQ with Realtek
software FastPath.

`nos.ko` installs a callback into the exported kernel pointer
`nos_tbq_enqueue`. The kernel calls that callback from:

- `fastpath_xmit_prerouting_hook`,
- `dev_queue_xmit`.

The callback updates the same per-client `online_ip` counters and global
WAN counters. A processed-skb marker prevents double counting.

Therefore software FastPath is **not** the leading explanation for zero
per-client rates.

The reference firmware boot log also shows HW NAT disabled (`/proc/hw_nat=0`)
once TBQ/WAN setup settles.

## Runtime probe

The current read-only per-client test uses TCP/9000:

```powershell
python .\tools\mw6_probe.py `
  --pcap .\PCAPdroid_16_wrz_11_20_35.pcap `
  --host 192.168.5.1 `
  --clients
```

To watch one client while generating traffic:

```powershell
python .\tools\mw6_probe.py `
  --pcap .\PCAPdroid_16_wrz_11_20_35.pcap `
  --host 192.168.5.1 `
  --watch-client "CLIENT_NAME_IP_OR_MAC" `
  --interval 2 `
  --count 10
```

The successful LOGIN payload is extracted from the capture and intentionally
never printed.

## Home Assistant integration status

A HACS-compatible custom integration exists in:

```text
custom_components/tenda_mw6/
```

Current behavior:

- local-only TCP/9000 communication,
- 10-second coordinator polling,
- authentication from a previously captured successful LOGIN payload,
- one HA device per discovered client MAC,
- signal sensor,
- IP diagnostic sensor,
- associated mesh-node serial diagnostic sensor,
- automatic entity creation for newly discovered clients,
- raw online/rate values retained diagnostically until runtime per-client rate
  behavior is fully validated.

The integration intentionally does not depend on Tenda cloud services.

## Current research target

The main blocker is now narrowly defined: reliable runtime population and
attachment of kernel `online_ip` records.

Static analysis has already ruled out:

- wrong HostInfo field mapping,
- wrong rate units,
- missing GetHostList rate helper,
- direction-bit confusion,
- software FastPath bypass.

The current target is:

`nf_conntrack_in → find/add online_ip → conntrack online_ip association → NOS accounting → g_ip_info`.

Only after non-zero live rates are reproducible should upload/download sensors
and daily/monthly transfer entities be enabled in Home Assistant.

## Safety rule

Development probes issue only confirmed read-only operations. Unknown SET
commands are not used against the production mesh.
