#!/usr/bin/env python3
"""Diagnostic read-only probe for one MW6 client.

Uses the existing TCP/9000 login and MESH_HOSTS_GET implementation from
mw6_probe.py, then prints only raw protobuf fields that change between polls.
Useful for verifying whether any per-client counters move during a transfer.
"""

from __future__ import annotations

import argparse
import socket
import time

import mw6_probe


def select_client(clients, selector: str):
    needle = selector.lower()
    matches = [
        c for c in clients
        if needle == (c.get("ip") or "").lower()
        or needle == (c.get("mac") or "").lower()
        or needle in (c.get("name") or "").lower()
    ]
    return matches


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pcap", required=True)
    ap.add_argument("--client", required=True, help="name, IP or MAC")
    ap.add_argument("--host", default=mw6_probe.HOST_DEFAULT)
    ap.add_argument("--port", type=int, default=mw6_probe.PORT_DEFAULT)
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--count", type=int, default=30)
    args = ap.parse_args()

    if args.interval < 1:
        ap.error("--interval must be >= 1 second")
    if args.count < 1:
        ap.error("--count must be >= 1")

    login_payload = mw6_probe.extract_successful_login_payload(args.pcap)
    print(f"Found successful LOGIN payload ({len(login_payload)} B); content is intentionally hidden.")

    with socket.create_connection((args.host, args.port), timeout=4) as s:
        s.settimeout(4)
        tid = 0xA0

        s.sendall(mw6_probe.build_request(tid, mw6_probe.AUTH_MODULE, mw6_probe.AUTH_GET_STA))
        mw6_probe.recv_frame(s)

        tid = (tid + 1) & 0xFF
        s.sendall(mw6_probe.build_request(tid, mw6_probe.AUTH_MODULE, mw6_probe.AUTH_LOGIN, login_payload))
        login = mw6_probe.recv_frame(s)
        if login["raw"][-4:] != b"\x00\x00\x00\x00":
            raise SystemExit("LOGIN rejected")

        print(f"Watching raw fields for {args.client!r}; interval={args.interval:g}s; samples={args.count}")
        previous = None

        for sample in range(1, args.count + 1):
            tid = (tid + 1) & 0xFF
            fr = mw6_probe.request_clients(s, tid)
            status, clients = mw6_probe.decode_mesh_hosts(fr["payload"])
            if status != 0:
                raise RuntimeError(f"MESH_HOSTS status={status}")

            matches = select_client(clients, args.client)
            stamp = time.strftime("%H:%M:%S")
            if not matches:
                print(f"{stamp} sample={sample:02d} client not found")
            else:
                c = matches[0]
                raw = c.get("raw", {})
                if previous is None:
                    print(f"{stamp} sample={sample:02d} initial raw={raw}")
                else:
                    changed = {
                        key: (previous.get(key), raw.get(key))
                        for key in sorted(set(previous) | set(raw))
                        if previous.get(key) != raw.get(key)
                    }
                    print(f"{stamp} sample={sample:02d} changed={changed or '{}'}")
                previous = dict(raw)

            if sample < args.count:
                time.sleep(args.interval)


if __name__ == "__main__":
    main()
