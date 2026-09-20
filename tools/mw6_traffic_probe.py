#!/usr/bin/env python3
"""Read-only MW6 WAN traffic probe.

Firmware boot.log confirms M_MESH_WAN[18] / CMD_MESH_WAN_TRAFFIC[8].
The response is status(int32 LE) + protobuf WanRate containing repeated
WanPortRate records. Firmware descriptors resolve WanPortRate fields as:
idx, uprate, downrate, total_up, total_down.
"""
import argparse
import socket
import time
from mw6_probe import (
    AUTH_GET_STA, AUTH_LOGIN, AUTH_MODULE, build_request,
    extract_successful_login_payload, recv_frame, show, _protobuf_fields,
)

MESH_WAN_MODULE = 0x12
MESH_WAN_TRAFFIC = 0x08


def decode_wan_traffic(payload):
    if len(payload) < 4:
        raise ValueError("GetTrafficInfo payload too short")
    status = int.from_bytes(payload[:4], "little", signed=True)
    records = []
    for field, wire, value in _protobuf_fields(payload[4:]):
        if field != 1 or wire != 2:
            continue
        raw = {f: v for f, w, v in _protobuf_fields(value) if w == 0}
        records.append({
            "idx": raw.get(1),
            "uprate": int(raw.get(2, 0)),
            "downrate": int(raw.get(3, 0)),
            "total_up": raw.get(4),
            "total_down": raw.get(5),
        })
    return status, records


def request_traffic(sock, tid):
    sock.sendall(build_request(tid, MESH_WAN_MODULE, MESH_WAN_TRAFFIC))
    r = recv_frame(sock)
    if r["module"] != MESH_WAN_MODULE or r["command"] != MESH_WAN_TRAFFIC:
        raise RuntimeError(f"unexpected response {r['module']:02x}/{r['command']:02x}")
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pcap", required=True)
    ap.add_argument("--host", default="192.168.0.1")
    ap.add_argument("--port", type=int, default=9000)
    ap.add_argument("--watch", action="store_true", help="poll GetTrafficInfo repeatedly")
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--count", type=int, default=15, help="0 = continuous")
    args = ap.parse_args()
    if args.interval < 1:
        ap.error("--interval must be >= 1 second")
    if args.count < 0:
        ap.error("--count must be >= 0")

    login = extract_successful_login_payload(args.pcap)
    print(f"Found successful LOGIN payload ({len(login)} B); content is intentionally hidden.")
    with socket.create_connection((args.host, args.port), timeout=4) as s:
        s.settimeout(4)
        tid = 0xA0
        s.sendall(build_request(tid, AUTH_MODULE, AUTH_GET_STA))
        show("AUTH GET_STA", recv_frame(s))
        tid += 1
        s.sendall(build_request(tid, AUTH_MODULE, AUTH_LOGIN, login))
        r = recv_frame(s)
        show("AUTH LOGIN", r)
        if r["raw"][-4:] != b"\x00\x00\x00\x00":
            raise SystemExit("LOGIN rejected")

        print("\nFirmware-confirmed GetTrafficInfo: M_MESH_WAN[18] / CMD_MESH_WAN_TRAFFIC[8]")
        n = 0
        while True:
            tid = (tid + 1) & 0xff
            r = request_traffic(s, tid)
            status, records = decode_wan_traffic(r["payload"])
            print(f"{time.strftime('%H:%M:%S')} status={status} records={records} raw={r['payload'].hex(' ')}")
            n += 1
            if not args.watch or (args.count and n >= args.count):
                break
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
