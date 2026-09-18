#!/usr/bin/env python3
"""Read-only Tenda MW6 TCP/9000 probe reconstructed from official-app traffic and firmware."""
import argparse
import socket
import struct
import sys
import time

HOST_DEFAULT = "192.168.5.1"
PORT_DEFAULT = 9000
MAGIC = b"\x24\x00"
REQ_KIND = 0x07
RESP_KIND = 0x06
FIXED = b"\x00\xd5"
AUTH_MODULE = 0x18
AUTH_GET_STA = 0x00
AUTH_LOGIN = 0x01
ADV_MODULE = 0x17
QOS_GET = 0x08
HIGH_DEVICE_GET = 0x0F
# Firmware confirms legacy online-hosts API in the internal ucapi namespace:
# M_OL_HOSTS == module 10 (0x0a), CMD_OL_HOSTS_GET == command 0.
# Whether this namespace is exposed 1:1 on TCP/9000 is being verified live.
OL_HOSTS_MODULE = 0x0A
OL_HOSTS_GET = 0x00
# Firmware boot.log and live wire test confirm:
# M_MESH_HOSTS[20] == TCP/9000 module 0x14 and CMD_MESH_HOSTS_GET[0] == 0x00.
MESH_HOSTS_MODULE = 0x14
MESH_HOSTS_GET = 0x00
# Firmware + protobuf descriptors confirm GetTrafficInfo:
# M_MESH_WAN[18] / CMD_MESH_WAN_TRAFFIC[8] -> WanRate{repeated WanPortRate}.
MESH_WAN_MODULE = 0x12
MESH_WAN_TRAFFIC = 0x08


def pcap_tcp_payloads(path, port=9000):
    with open(path, "rb") as f:
        gh = f.read(24)
        if len(gh) != 24:
            raise ValueError("Invalid PCAP")
        magic = gh[:4]
        if magic == b"\xd4\xc3\xb2\xa1": endian = "<"
        elif magic == b"\xa1\xb2\xc3\xd4": endian = ">"
        else: raise ValueError("Classic PCAP required (not PCAPNG)")
        linktype = struct.unpack(endian + "I", gh[20:24])[0]
        if linktype != 101: raise ValueError(f"Expected DLT_RAW=101, got {linktype}")
        while True:
            ph = f.read(16)
            if not ph or len(ph) != 16: break
            _, _, incl_len, _ = struct.unpack(endian + "IIII", ph)
            pkt = f.read(incl_len)
            if len(pkt) < 40 or pkt[0] >> 4 != 4 or pkt[9] != 6: continue
            ihl = (pkt[0] & 0x0F) * 4
            sport, dport = struct.unpack("!HH", pkt[ihl:ihl + 4])
            doff = ((pkt[ihl + 12] >> 4) & 0x0F) * 4
            payload = pkt[ihl + doff:]
            if payload and (sport == port or dport == port): yield sport, dport, payload


def parse_frame(data):
    if len(data) < 16 or data[:2] != MAGIC: return None
    n = int.from_bytes(data[6:8], "big")
    return {"kind": data[2], "tid": data[3], "payload_len": n,
            "module": data[8], "command": data[9],
            "payload": data[16:16+n], "raw": data[:16+n]}


def extract_successful_login_payload(pcap):
    candidates = {}
    for sport, dport, raw in pcap_tcp_payloads(pcap):
        fr = parse_frame(raw)
        if not fr: continue
        if dport == 9000 and fr["kind"] == REQ_KIND and fr["module"] == AUTH_MODULE and fr["command"] == AUTH_LOGIN:
            candidates[fr["tid"]] = fr["payload"]
        elif sport == 9000 and fr["kind"] == RESP_KIND and fr["module"] == AUTH_MODULE and fr["command"] == AUTH_LOGIN:
            if fr["raw"][-4:] == b"\x00\x00\x00\x00" and fr["tid"] in candidates:
                return candidates[fr["tid"]]
    raise RuntimeError("No successful LOGIN found in PCAP")


def build_request(tid, module, command, payload=b""):
    return (MAGIC + bytes([REQ_KIND, tid & 0xFF]) + FIXED + len(payload).to_bytes(2, "big")
            + bytes([module, command, 0, 0]) + b"\x01\x00\x00\x00" + payload)


def recv_frame(sock):
    hdr = b""
    while len(hdr) < 16:
        chunk = sock.recv(16-len(hdr))
        if not chunk: raise ConnectionError("Router closed connection")
        hdr += chunk
    n = int.from_bytes(hdr[6:8], "big")
    payload = b""
    while len(payload) < n:
        chunk = sock.recv(n-len(payload))
        if not chunk: raise ConnectionError("Connection interrupted")
        payload += chunk
    return parse_frame(hdr + payload)


def show(label, fr, dump_hex=True):
    print(f"\n=== {label} ===")
    print(f"TID=0x{fr['tid']:02x} kind=0x{fr['kind']:02x} module=0x{fr['module']:02x} cmd=0x{fr['command']:02x} payload={fr['payload_len']} B")
    if dump_hex:
        print("HEX payload:", fr["payload"].hex(" "))
        if len(fr["payload"]) >= 4:
            print("payload[0:4] as LE signed status:", int.from_bytes(fr["payload"][:4], "little", signed=True))


def _varint(buf, pos):
    value = 0; shift = 0
    while pos < len(buf) and shift < 70:
        b = buf[pos]; pos += 1
        value |= (b & 0x7f) << shift
        if not (b & 0x80): return value, pos
        shift += 7
    raise ValueError("invalid protobuf varint")


def _protobuf_fields(buf):
    pos = 0; out = []
    while pos < len(buf):
        key, pos = _varint(buf, pos); field, wire = key >> 3, key & 7
        if wire == 0: value, pos = _varint(buf, pos)
        elif wire == 2:
            n, pos = _varint(buf, pos); value = buf[pos:pos+n]; pos += n
        elif wire == 1: value = buf[pos:pos+8]; pos += 8
        elif wire == 5: value = buf[pos:pos+4]; pos += 4
        else: raise ValueError(f"unsupported protobuf wire type {wire}")
        out.append((field, wire, value))
    return out


def _signed64(v):
    return v - (1 << 64) if v >= (1 << 63) else v


def decode_mesh_hosts(payload):
    """Decode HostLists/HostInfo using field order recovered from onhosts.pb-c.c.

    HostInfo schema: 1 ipaddr, 2 ethaddr, 3 access, 4 assoc_sn,
    5 condtion_time, 6 online, 7 uprate, 8 downrate, 9 signal, 10 name.
    """
    if len(payload) < 4: raise ValueError("hosts response too short")
    status = int.from_bytes(payload[:4], "little", signed=True)
    records = []
    for field, wire, value in _protobuf_fields(payload[4:]):
        if field != 1 or wire != 2: continue
        raw = {}
        for f, w, v in _protobuf_fields(value):
            if w == 2:
                try: raw[f] = v.decode("utf-8")
                except UnicodeDecodeError: raw[f] = v.hex()
            elif w == 0: raw[f] = _signed64(v) if f == 9 else v
            else: raw[f] = v.hex()
        records.append({
            "ip": raw.get(1, ""), "mac": raw.get(2, ""), "access": raw.get(3),
            "node_sn": raw.get(4, ""), "condition_time": raw.get(5),
            "online": raw.get(6), "uprate": raw.get(7), "downrate": raw.get(8),
            "signal": raw.get(9), "name": raw.get(10, ""), "raw": raw,
        })
    return status, records


def decode_wan_traffic(payload):
    """Decode WanRate / WanPortRate.

    WanPortRate schema recovered from libpb.so:
      1 idx, 2 uprate, 3 downrate, 4 total_up, 5 total_down.
    The diagnostic only needs non-zero WAN rate as an independent traffic
    control; it deliberately does not assign a display unit here.
    """
    if len(payload) < 4:
        raise ValueError("WAN traffic response too short")
    status = int.from_bytes(payload[:4], "little", signed=True)
    ports = []
    for field, wire, value in _protobuf_fields(payload[4:]):
        if field != 1 or wire != 2:
            continue
        raw = {f: v for f, w, v in _protobuf_fields(value) if w == 0}
        ports.append({
            "idx": raw.get(1),
            "uprate": int(raw.get(2, 0)),
            "downrate": int(raw.get(3, 0)),
            "total_up": raw.get(4),
            "total_down": raw.get(5),
        })
    return status, ports


def show_clients(fr):
    status, clients = decode_mesh_hosts(fr["payload"])
    print(f"Status={status}; hosts={len(clients)}")
    print("#   IP               MAC                A ON  SIGNAL   UP      DOWN    NODE_SN             NAME")
    print("--  ---------------  -----------------  - --  ------  ------  ------  ------------------  ------------------------------")
    for i, c in enumerate(clients, 1):
        sig = "" if c["signal"] is None else str(c["signal"])
        acc = "" if c["access"] is None else str(c["access"])
        on = "" if c["online"] is None else str(c["online"])
        up = "" if c["uprate"] is None else str(c["uprate"])
        down = "" if c["downrate"] is None else str(c["downrate"])
        print(f"{i:>2}  {c['ip']:<15}  {c['mac']:<17}  {acc:<1} {on:>2}  {sig:>6}  {up:>6}  {down:>6}  {c['node_sn']:<18}  {c['name']}")
    return clients


def request_hosts(sock, tid, module, command, diagnostic=False):
    sock.sendall(build_request(tid, module, command))
    max_frames = 4 if diagnostic else 1
    for idx in range(1, max_frames + 1):
        try:
            fr = recv_frame(sock)
        except socket.timeout:
            if diagnostic:
                print(f"No matching response after {idx-1} frame(s); socket timed out.")
                return None
            raise
        if fr["module"] == module and fr["command"] == command:
            return fr
        if not diagnostic:
            raise RuntimeError(f"unexpected response module/cmd {fr['module']:02x}/{fr['command']:02x}")
        show(f"unexpected/interleaved frame {idx}", fr, dump_hex=True)
    print(f"No matching module/cmd 0x{module:02x}/0x{command:02x} in first {max_frames} response frames.")
    return None


def request_clients(sock, tid):
    return request_hosts(sock, tid, MESH_HOSTS_MODULE, MESH_HOSTS_GET)


def request_wan_traffic(sock, tid):
    return request_hosts(sock, tid, MESH_WAN_MODULE, MESH_WAN_TRAFFIC)


def _match_clients(clients, selector):
    needle = selector.strip().lower()
    return [
        c for c in clients
        if needle == (c["ip"] or "").lower()
        or needle == (c["mac"] or "").lower()
        or needle in (c["name"] or "").lower()
    ]


def watch_client_rates(sock, tid, selector, interval, count):
    print(f"\nWatching client {selector!r}; interval={interval:g}s; samples={count if count else 'continuous'}")
    print("TIME      IP               MAC                ONLINE  UP      DOWN    SIGNAL  NAME")
    n = 0
    while not count or n < count:
        tid = (tid + 1) & 0xff
        fr = request_clients(sock, tid)
        status, clients = decode_mesh_hosts(fr["payload"])
        if status != 0: raise RuntimeError(f"MESH_HOSTS status={status}")
        matches = _match_clients(clients, selector)
        stamp = time.strftime("%H:%M:%S")
        if not matches:
            print(f"{stamp}  client not found: {selector}")
        for c in matches:
            print(f"{stamp}  {c['ip']:<15}  {c['mac']:<17}  {str(c['online']):>6}  {str(c['uprate']):>6}  {str(c['downrate']):>6}  {str(c['signal']):>6}  {c['name']}")
        n += 1
        if not count or n < count: time.sleep(interval)
    return tid


def diagnose_client_rates(sock, tid, selector, interval, duration):
    """Observe one HostInfo across the 45 s inventory watchdog with WAN control."""
    print(
        f"\nDiagnosing client {selector!r}; interval={interval:g}s; "
        f"duration={duration:g}s (firmware inventory watchdog: 45s)"
    )
    print(
        "TIME      ONLINE  COND_S    UP   DOWN  WAN_UP WAN_DN  SIGNAL  "
        "NODE_SN                           IP               MAC                NAME"
    )

    deadline = time.monotonic() + duration
    selected_mac = None
    samples = []
    wan_samples = []
    missing_samples = 0

    while True:
        tid = (tid + 1) & 0xff
        fr = request_clients(sock, tid)
        status, clients = decode_mesh_hosts(fr["payload"])
        if status != 0:
            raise RuntimeError(f"MESH_HOSTS status={status}")

        # Independent control: router-wide GetTrafficInfo is a separate,
        # firmware-confirmed read-only API. It proves whether WAN traffic was
        # visible to the router in the same observation window.
        tid = (tid + 1) & 0xff
        wan_fr = request_wan_traffic(sock, tid)
        wan_status, wan_ports = decode_wan_traffic(wan_fr["payload"])
        if wan_status != 0:
            raise RuntimeError(f"MESH_WAN_TRAFFIC status={wan_status}")
        wan_up = sum(int(p.get("uprate") or 0) for p in wan_ports)
        wan_down = sum(int(p.get("downrate") or 0) for p in wan_ports)
        wan_samples.append((wan_up, wan_down))

        if selected_mac:
            matches = [c for c in clients if (c["mac"] or "").lower() == selected_mac]
        else:
            matches = _match_clients(clients, selector)
            if len(matches) > 1:
                exact = [
                    c for c in matches
                    if selector.strip().lower() in {
                        (c["ip"] or "").lower(),
                        (c["mac"] or "").lower(),
                        (c["name"] or "").lower(),
                    }
                ]
                if len(exact) == 1:
                    matches = exact
                else:
                    choices = ", ".join(
                        f"{c['name'] or '?'} [{c['ip'] or '?'} / {c['mac'] or '?'}]"
                        for c in matches
                    )
                    raise RuntimeError(
                        f"selector {selector!r} matches multiple clients: {choices}. "
                        "Use exact IP or MAC."
                    )

        stamp = time.strftime("%H:%M:%S")
        if not matches:
            missing_samples += 1
            print(
                f"{stamp}  MISSING  WAN_UP={wan_up} WAN_DN={wan_down}  "
                "client not present in HostLists"
            )
        else:
            client = matches[0]
            if selected_mac is None:
                selected_mac = (client["mac"] or "").lower()
            sample = {
                "online": int(client["online"] or 0),
                "condition_time": client["condition_time"],
                "uprate": int(client["uprate"] or 0),
                "downrate": int(client["downrate"] or 0),
                "signal": client["signal"],
                "node_sn": client["node_sn"] or "",
                "ip": client["ip"] or "",
                "mac": client["mac"] or "",
                "name": client["name"] or "",
            }
            samples.append(sample)
            print(
                f"{stamp}  {sample['online']:>6}  {str(sample['condition_time']):>6}  "
                f"{sample['uprate']:>4}  {sample['downrate']:>5}  "
                f"{wan_up:>6} {wan_down:>6}  "
                f"{str(sample['signal']):>6}  {sample['node_sn']:<32}  "
                f"{sample['ip']:<15}  {sample['mac']:<17}  {sample['name']}"
            )

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(interval, remaining))

    print("\n=== DIAGNOSTIC SUMMARY ===")
    print(f"selector: {selector}")
    print(f"samples_present: {len(samples)}")
    print(f"samples_missing: {missing_samples}")

    max_wan_up = max((u for u, d in wan_samples), default=0)
    max_wan_down = max((d for u, d in wan_samples), default=0)
    wan_nonzero = sum(1 for u, d in wan_samples if u > 0 or d > 0)
    print(f"max_wan_uprate_raw: {max_wan_up}")
    print(f"max_wan_downrate_raw: {max_wan_down}")
    print(f"wan_nonzero_samples: {wan_nonzero}")

    if not samples:
        print("classification: CLIENT_NOT_FOUND")
        print("meaning: the selected client was not returned in HostLists during the observation window.")
        return tid

    online_values = [s["online"] for s in samples]
    max_up = max(s["uprate"] for s in samples)
    max_down = max(s["downrate"] for s in samples)
    nodes = sorted({s["node_sn"] for s in samples if s["node_sn"]})
    ips = sorted({s["ip"] for s in samples if s["ip"]})
    cond_values = [
        s["condition_time"]
        for s in samples
        if isinstance(s["condition_time"], int)
    ]

    transitions = sum(
        1 for prev, cur in zip(online_values, online_values[1:]) if prev != cur
    )
    print(f"online_values: {sorted(set(online_values))}")
    print(f"online_transitions: {transitions}")
    print(f"max_uprate_kib_s: {max_up}")
    print(f"max_downrate_kib_s: {max_down}")
    print(f"node_sn_values: {nodes}")
    print(f"ip_values: {ips}")
    if cond_values:
        print(f"condition_time_range: {min(cond_values)}..{max(cond_values)}")

    if any(v == 0 for v in online_values):
        print("classification: INVENTORY_ONLINE_DROPPED")
        print(
            "meaning: HostInfo.online became/stayed 0. The rate helper skips such a client, "
            "so investigate device_list reporting / the 45 s last_seen watchdog first."
        )
    elif max_up == 0 and max_down == 0 and wan_nonzero:
        print("classification: ONLINE_CLIENT_ZERO_WITH_WAN_TRAFFIC")
        print(
            "meaning: inventory stayed online and the router independently reported WAN traffic, "
            "but this client's firmware rates stayed zero. Focus directly on per-client "
            "g_ip_info / online_ip matching or counters."
        )
    elif max_up == 0 and max_down == 0:
        print("classification: ONLINE_BUT_NO_RATE_EVIDENCE")
        print(
            "meaning: inventory stayed online, but neither client nor WAN control showed a "
            "non-zero rate. This run did not prove sustained forwarded traffic."
        )
    else:
        print("classification: RATE_PIPELINE_ACTIVE")
        print(
            "meaning: at least one non-zero firmware per-client rate was observed. "
            "The local GetHostList traffic pipeline is working for this client."
        )
    return tid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pcap", required=True)
    ap.add_argument("--host", default=HOST_DEFAULT)
    ap.add_argument("--port", type=int, default=PORT_DEFAULT)
    ap.add_argument("--high-device", action="store_true")
    ap.add_argument("--ol-hosts", action="store_true", help="diagnose legacy M_OL_HOSTS/CMD_OL_HOSTS_GET")
    ap.add_argument("--clients", action="store_true", help="read-only M_MESH_HOSTS/CMD_MESH_HOSTS_GET")
    ap.add_argument("--raw-hex", action="store_true", help="also print full MESH_HOSTS payload as hex")
    ap.add_argument("--watch-client", metavar="NAME_IP_OR_MAC", help="poll one client and show firmware uprate/downrate")
    ap.add_argument(
        "--diagnose-rates",
        metavar="NAME_IP_OR_MAC",
        help="observe one client across the 45 s inventory watchdog and classify zero-rate cause",
    )
    ap.add_argument("--interval", type=float, default=3.0, help="watch polling interval in seconds (default: 3)")
    ap.add_argument("--count", type=int, default=10, help="watch sample count; 0 = continuous (default: 10)")
    ap.add_argument(
        "--duration",
        type=float,
        default=65.0,
        help="diagnostic observation window in seconds (default: 65; must be >= 45)",
    )
    args = ap.parse_args()
    if args.interval < 1: ap.error("--interval must be >= 1 second")
    if args.count < 0: ap.error("--count must be >= 0")
    if args.diagnose_rates and args.duration < 45:
        ap.error("--duration must be >= 45 seconds with --diagnose-rates")
    login_payload = extract_successful_login_payload(args.pcap)
    print(f"Found successful LOGIN payload ({len(login_payload)} B); content is intentionally hidden.")
    with socket.create_connection((args.host, args.port), timeout=4) as s:
        s.settimeout(4); tid = 0xA0
        s.sendall(build_request(tid, AUTH_MODULE, AUTH_GET_STA)); show("AUTH GET_STA", recv_frame(s))
        tid += 1
        s.sendall(build_request(tid, AUTH_MODULE, AUTH_LOGIN, login_payload)); r = recv_frame(s); show("AUTH LOGIN", r)
        if r["raw"][-4:] != b"\x00\x00\x00\x00":
            print("LOGIN rejected; stopping before further commands."); sys.exit(2)
        if args.ol_hosts:
            tid += 1
            print("\nSending diagnostic OL_HOSTS_GET candidate (internal ucapi module=0x0a, cmd=0x00, empty payload)...")
            print("Note: this test now captures unexpected/interleaved TCP/9000 frames instead of aborting on the first one.")
            r = request_hosts(s, tid, OL_HOSTS_MODULE, OL_HOSTS_GET, diagnostic=True)
            if r is None:
                return
            show("M_OL_HOSTS / OL_HOSTS_GET", r, dump_hex=True)
            try:
                show_clients(r)
            except Exception as exc:
                print(f"HostLists decode failed: {exc}")
            return
        if args.diagnose_rates:
            diagnose_client_rates(s, tid, args.diagnose_rates, args.interval, args.duration); return
        if args.watch_client:
            watch_client_rates(s, tid, args.watch_client, args.interval, args.count); return
        if args.clients:
            tid += 1
            print("\nSending read-only firmware-confirmed MESH_HOSTS_GET (module=0x14, cmd=0x00, empty payload)...")
            r = request_clients(s, tid); show("M_MESH_HOSTS / MESH_HOSTS_GET", r, dump_hex=args.raw_hex); show_clients(r); return
        tid += 1
        s.sendall(build_request(tid, ADV_MODULE, QOS_GET)); show("M_MESH_ADVANCE / QOS_GET", recv_frame(s))
        if args.high_device:
            tid += 1; s.sendall(build_request(tid, ADV_MODULE, HIGH_DEVICE_GET)); show("M_MESH_ADVANCE / HIGH_DEVICE_GET", recv_frame(s))


if __name__ == "__main__": main()
