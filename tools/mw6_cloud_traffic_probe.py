#!/usr/bin/env python3
"""Minimal diagnostic for Tenda MW6 TCP/9000 cloud-traffic namespace.

This sends an empty payload only. It does not upload client records or change
router configuration; the purpose is only to verify whether module 0x08 /
command 0x0c is exposed on the local TCP/9000 protocol.
"""
import argparse
import socket

from mw6_probe import (
    AUTH_GET_STA,
    AUTH_LOGIN,
    AUTH_MODULE,
    HOST_DEFAULT,
    PORT_DEFAULT,
    build_request,
    extract_successful_login_payload,
    recv_frame,
    request_hosts,
    show,
)

CLOUD_INFO_MODULE = 0x08
DEV_TRAFFIC_UPLOAD = 0x0C


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pcap", required=True)
    ap.add_argument("--host", default=HOST_DEFAULT)
    ap.add_argument("--port", type=int, default=PORT_DEFAULT)
    args = ap.parse_args()

    login_payload = extract_successful_login_payload(args.pcap)
    print(f"Found successful LOGIN payload ({len(login_payload)} B); content is intentionally hidden.")

    with socket.create_connection((args.host, args.port), timeout=4) as s:
        s.settimeout(4)
        tid = 0xA0

        s.sendall(build_request(tid, AUTH_MODULE, AUTH_GET_STA))
        show("AUTH GET_STA", recv_frame(s))

        tid += 1
        s.sendall(build_request(tid, AUTH_MODULE, AUTH_LOGIN, login_payload))
        login = recv_frame(s)
        show("AUTH LOGIN", login)
        if login["raw"][-4:] != b"\x00\x00\x00\x00":
            raise SystemExit("LOGIN rejected; stopping before diagnostic command.")

        tid += 1
        print("\nSending empty-payload diagnostic for module=0x08 cmd=0x0c...")
        print("No client traffic records are included; this only tests local namespace exposure.")
        response = request_hosts(
            s,
            tid,
            CLOUD_INFO_MODULE,
            DEV_TRAFFIC_UPLOAD,
            diagnostic=True,
        )
        if response is None:
            return
        show("M_CLOUD_INFO / DEV_TRAFFIC_UPLOAD diagnostic response", response, dump_hex=True)


if __name__ == "__main__":
    main()
