#!/usr/bin/env python3
"""Read-only Tenda MW6 TCP/9000 probe reconstructed from official-app traffic and firmware."""
import argparse
import socket
import struct
import sys

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
# Firmware boot.log confirms the app-facing registry IDs:
# M_MESH_HOSTS[20] and CMD_MESH_HOSTS_GET[0].
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


def show(label, fr):
    print(f"\n=== {label} ===")
    print(f"TID=0x{fr['tid']:02x} module=0x{fr['module']:02x} cmd=0x{fr['command']:02x} payload={fr['payload_len']} B")
    print("HEX payload:", fr["payload"].hex(" "))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pcap", required=True)
    ap.add_argument("--host", default=HOST_DEFAULT)
    ap.add_argument("--port", type=int, default=PORT_DEFAULT)
    ap.add_argument("--high-device", action="store_true")
    ap.add_argument("--clients", action="store_true", help="read-only firmware-confirmed M_MESH_HOSTS/CMD_MESH_HOSTS_GET")
    args = ap.parse_args()
    login_payload = extract_successful_login_payload(args.pcap)
    print(f"Found successful LOGIN payload ({len(login_payload)} B); content is intentionally hidden.")
    with socket.create_connection((args.host, args.port), timeout=4) as s:
        s.settimeout(4)
        tid = 0xA0
        s.sendall(build_request(tid, AUTH_MODULE, AUTH_GET_STA)); show("AUTH GET_STA", recv_frame(s))
        tid += 1
        s.sendall(build_request(tid, AUTH_MODULE, AUTH_LOGIN, login_payload)); r = recv_frame(s); show("AUTH LOGIN", r)
        if r["raw"][-4:] != b"\x00\x00\x00\x00":
            print("LOGIN rejected; stopping before further commands."); sys.exit(2)
        if args.clients:
            tid += 1
            print("\nSending read-only firmware-confirmed MESH_HOSTS_GET (module=0x14, cmd=0x00, empty payload)...")
            s.sendall(build_request(tid, MESH_HOSTS_MODULE, MESH_HOSTS_GET))
            show("M_MESH_HOSTS / MESH_HOSTS_GET", recv_frame(s))
            return
        tid += 1
        s.sendall(build_request(tid, ADV_MODULE, QOS_GET)); show("M_MESH_ADVANCE / QOS_GET", recv_frame(s))
        if args.high_device:
            tid += 1
            s.sendall(build_request(tid, ADV_MODULE, HIGH_DEVICE_GET)); show("M_MESH_ADVANCE / HIGH_DEVICE_GET", recv_frame(s))


if __name__ == "__main__":
    main()