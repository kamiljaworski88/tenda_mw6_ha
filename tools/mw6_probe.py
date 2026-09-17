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
# Firmware confirms legacy online-hosts API:
# M_OL_HOSTS == module 10 (0x0a), CMD_OL_HOSTS_GET == command 0.
OL_HOSTS_MODULE = 0x0A
OL_HOSTS_GET = 0x00
# Firmware boot.log and live wire test confirm:
# M_MESH_HOSTS[20] == TCP/9000 module 0x14 and CMD_MESH_HOSTS_GET[0] == 0x00.
MESH_HOSTS_MODULE = 0x14
MESH_HOSTS_GET = 0x00


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
    print(f"TID=0x{fr['tid']:02x} module=0x{fr['module']:02x} cmd=0x{fr['command']:02x} payload={fr['payload_len']} B")
    if dump_hex:
        print("HEX payload:", fr["payload"].hex(" "))


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


def request_hosts(sock, tid, module, command):
    sock.sendall(build_request(tid, module, command))
    fr = recv_frame(sock)
    if fr["module"] != module or fr["command"] != command:
        raise RuntimeError(f"unexpected response module/cmd {fr['module']:02x}/{fr['command']:02x}")
    return fr


def request_clients(sock, tid):
    return request_hosts(sock, tid, MESH_HOSTS_MODULE, MESH_HOSTS_GET)


def watch_client_rates(sock, tid, selector, interval, count):
    print(f"\nWatching client {selector!r}; interval={interval:g}s; samples={count if count else 'continuous'}")
    print("TIME      IP               MAC                ONLINE  UP      DOWN    SIGNAL  NAME")
    n = 0
    while not count or n < count:
        tid = (tid + 1) & 0xff
        fr = request_clients(sock, tid)
        status, clients = decode_mesh_hosts(fr["payload"])
        if status != 0: raise RuntimeError(f"MESH_HOSTS status={status}")
        needle = selector.lower()
        matches = [c for c in clients if needle in (c["name"] or "").lower() or needle == c["ip"].lower() or needle == c["mac"].lower()]
        stamp = time.strftime("%H:%M:%S")
        if not matches:
            print(f"{stamp}  client not found: {selector}")
        for c in matches:
            print(f"{stamp}  {c['ip']:<15}  {c['mac']:<17}  {str(c['online']):>6}  {str(c['uprate']):>6}  {str(c['downrate']):>6}  {str(c['signal']):>6}  {c['name']}")
        n += 1
        if not count or n < count: time.sleep(interval)
    return tid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pcap", required=True)
    ap.add_argument("--host", default=HOST_DEFAULT)
    ap.add_argument("--port", type=int, default=PORT_DEFAULT)
    ap.add_argument("--high-device", action="store_true")
    ap.add_argument("--ol-hosts", action="store_true", help="read-only legacy M_OL_HOSTS/CMD_OL_HOSTS_GET")
    ap.add_argument("--clients", action="store_true", help="read-only M_MESH_HOSTS/CMD_MESH_HOSTS_GET")
    ap.add_argument("--raw-hex", action="store_true", help="also print full MESH_HOSTS payload as hex")
    ap.add_argument("--watch-client", metavar="NAME_IP_OR_MAC", help="poll one client and show firmware uprate/downrate")
    ap.add_argument("--interval", type=float, default=3.0, help="watch polling interval in seconds (default: 3)")
    ap.add_argument("--count", type=int, default=10, help="watch sample count; 0 = continuous (default: 10)")
    args = ap.parse_args()
    if args.interval < 1: ap.error("--interval must be >= 1 second")
    if args.count < 0: ap.error("--count must be >= 0")
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
            print("\nSending read-only firmware-confirmed OL_HOSTS_GET (module=0x0a, cmd=0x00, empty payload)...")
            r = request_hosts(s, tid, OL_HOSTS_MODULE, OL_HOSTS_GET)
            show("M_OL_HOSTS / OL_HOSTS_GET", r, dump_hex=True)
            try:
                show_clients(r)
            except Exception as exc:
                print(f"HostLists decode failed: {exc}")
            return
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
