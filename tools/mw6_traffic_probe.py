#!/usr/bin/env python3
"""Read-only MW6 traffic probe.

Firmware boot.log confirms M_MESH_WAN[18] / CMD_MESH_WAN_TRAFFIC[8].
This command is expected to be WAN traffic, not yet per-client traffic; the
purpose of this probe is to decode its live response and separate it from the
HostInfo rate path.
"""
import argparse
import socket
from mw6_probe import (
    AUTH_GET_STA, AUTH_LOGIN, AUTH_MODULE, build_request,
    extract_successful_login_payload, recv_frame, show,
)

MESH_WAN_MODULE = 0x12
MESH_WAN_TRAFFIC = 0x08


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pcap", required=True)
    ap.add_argument("--host", default="192.168.5.1")
    ap.add_argument("--port", type=int, default=9000)
    args = ap.parse_args()

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

        tid += 1
        print("\nSending firmware-confirmed GetTrafficInfo: M_MESH_WAN[18] / CMD_MESH_WAN_TRAFFIC[8]...")
        s.sendall(build_request(tid, MESH_WAN_MODULE, MESH_WAN_TRAFFIC))
        r = recv_frame(s)
        show("M_MESH_WAN / GetTrafficInfo", r)
        print("NOTE: this endpoint is classified by firmware as WAN traffic; response decoding comes next.")


if __name__ == "__main__":
    main()
