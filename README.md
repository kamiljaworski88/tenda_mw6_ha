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
- exact formula is
  `trunc(delta_bytes / (elapsed_us / 1_000_000) / 1024)`,
- `uprate` / `downrate` are integer KiB/s; sub-1-KiB/s traffic truncates to
  zero.

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

The current read-only per-client test uses TCP/9000. On Windows, locate the
known capture by wildcard so its directory and extension do not need to be
guessed:

```powershell
$pcap = Get-ChildItem -Path C:\Users\Dell -Recurse -File -Filter 'PCAPdroid_16_wrz_10_31_43*' -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName; if (-not $pcap) { throw 'Capture PCAPdroid_16_wrz_10_31_43* not found under C:\Users\Dell' }; python .\tools\mw6_probe.py --pcap $pcap --host 192.168.5.1 --clients
```

To watch one client while generating traffic:

```powershell
python .\tools\mw6_probe.py `
  --pcap $pcap `
  --host 192.168.5.1 `
  --watch-client "CLIENT_NAME_IP_OR_MAC" `
  --interval 2 `
  --count 10
```

For the current zero-rate investigation, use the 65-second diagnostic. It
intentionally crosses the firmware's 45-second inventory watchdog:

```powershell
python .\tools\mw6_probe.py `
  --pcap $pcap `
  --host 192.168.5.1 `
  --diagnose-rates "CLIENT_NAME_IP_OR_MAC" `
  --interval 5 `
  --duration 65
```

Each diagnostic sample now shows the selected client's rate and the independent
router-wide WAN control (`WAN_UP/WAN_DN`) from `GetTrafficInfo`.

The summary classifies the result as:

- `INVENTORY_ONLINE_DROPPED` — HostInfo inventory state is stale/offline,
- `ONLINE_CLIENT_ZERO_WITH_WAN_TRAFFIC` — inventory stayed online and the
  router independently saw WAN traffic, but this client remained at 0/0;
  continue directly at per-client `g_ip_info` / `online_ip`,
- `ONLINE_BUT_NO_RATE_EVIDENCE` — neither client nor WAN control proved
  active forwarded traffic,
- `RATE_PIPELINE_ACTIVE` — non-zero per-client firmware rate was observed.

Run 162 produced `INVENTORY_ONLINE_DROPPED` for `192.168.5.47`. Static
analysis then confirmed that the reporting process publishes its local client
list every 20 seconds, which should beat the 45-second central watchdog. Run
168 directly resolves the timer branch to `g_client_hs_list`,
`g_client_hs_list_num`, and `do_upload_client_list`.

Use the node/peer diagnostic to distinguish a node-wide reporting failure from
a target-only enumeration problem:

```powershell
python .\tools\mw6_probe.py `
  --pcap $pcap `
  --host 192.168.5.1 `
  --diagnose-inventory "192.168.5.47" `
  --interval 5 `
  --duration 65
```

Its classifications are `TARGET_INVENTORY_REFRESHED`, `TARGET_ONLY_STALE`,
`NODE_REPORTING_STALE`, `STALE_TARGET_NODE_INCONCLUSIVE`, and
`TARGET_NOT_FOUND`.

The live node/peer run returned 0 online clients out of 9 on the selected node
and 0 out of 30 across the complete HostLists in every snapshot. This is a
global central-inventory failure, not an isolated client or satellite issue.

The next boundary test passively monitors the confirmed local pub/sub channel
without printing or saving any payload contents:

```powershell
python .\tools\mw6_cmd_client.py `
  --host 192.168.5.1 `
  monitor-device-list `
  --duration 65
```

The summary distinguishes local `device_list_upload` publication from producer
silence or an unconfirmed subscription.

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

The complete static pipeline is now resolved through both inventory and kernel
accounting.

Runs 149–151 prove:

- `HostInfo.online = client_status+0x84`,
- client reports refresh `last_seen`,
- a 45-second watchdog marks stale inventory offline,
- the reporting MW6 identity becomes `HostInfo.assoc_sn`,
- each device-list upload is merged by client MAC into the central client hash.

The current live result is stronger than `INVENTORY_ONLINE_DROPPED`: all 30
central records remained offline for the entire 65-second run. Runs 163–170
prove that the normal producer path should fire every 20 seconds and publish
`device_list_upload`. The next blocker is therefore this distinction:

```text
device_list visible on confctl_srv_key -> consumption/merge or relay failure
        vs
channel active without device_list -> producer/list path failure
        vs
confirmed subscription but silent channel -> timer/cmd_pub failure
```

Use `monitor-device-list` before returning to rate accounting or enabling
production upload/download and daily/monthly transfer entities in Home
Assistant.

## Safety rule

Development probes issue only confirmed read-only operations. Unknown SET
commands are not used against the production mesh.
