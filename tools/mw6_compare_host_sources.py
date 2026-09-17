#!/usr/bin/env python3
"""Compare MW6 client data from the two confirmed local HostList paths.

Read-only diagnostic tool. It compares:
  1. authenticated TCP/9000 M_MESH_HOSTS/GET,
  2. local cmdsrv/confsrv GetHostList over TCP/12598.

The goal is to isolate why live per-client online/uprate/downrate values can be
zero on one path even though firmware contains a fully resolved rate pipeline.
The successful LOGIN payload is extracted from a supplied PCAP and is never
printed.
"""
from __future__ import annotations

import argparse
import socket
import time

from mw6_cmd_client import get_clients as get_cmdsrv_clients
from mw6_probe import (
    AUTH_GET_STA,
    AUTH_LOGIN,
    AUTH_MODULE,
    MESH_HOSTS_GET,
    MESH_HOSTS_MODULE,
    build_request,
    decode_mesh_hosts,
    extract_successful_login_payload,
    recv_frame,
)


def get_tcp9000_clients(host: str, port: int, login_payload: bytes) -> list[dict]:
    with socket.create_connection((host, port), timeout=4) as sock:
        sock.settimeout(4)
        tid = 0xA0

        sock.sendall(build_request(tid, AUTH_MODULE, AUTH_GET_STA))
        recv_frame(sock)

        tid = (tid + 1) & 0xFF
        sock.sendall(build_request(tid, AUTH_MODULE, AUTH_LOGIN, login_payload))
        login = recv_frame(sock)
        if login["raw"][-4:] != b"\x00\x00\x00\x00":
            raise RuntimeError("TCP/9000 LOGIN rejected")

        tid = (tid + 1) & 0xFF
        sock.sendall(build_request(tid, MESH_HOSTS_MODULE, MESH_HOSTS_GET))
        response = recv_frame(sock)
        if response["module"] != MESH_HOSTS_MODULE or response["command"] != MESH_HOSTS_GET:
            raise RuntimeError(
                f"unexpected TCP/9000 response {response['module']:02x}/{response['command']:02x}"
            )
        status, clients = decode_mesh_hosts(response["payload"])
        if status != 0:
            raise RuntimeError(f"MESH_HOSTS status={status}")
        return clients


def normalize_tcp9000(client: dict) -> dict:
    return {
        "ip": client.get("ip") or "",
        "mac": (client.get("mac") or "").lower(),
        "name": client.get("name") or "",
        "node": client.get("node_sn") or "",
        "online": client.get("online"),
        "uprate": client.get("uprate"),
        "downrate": client.get("downrate"),
        "signal": client.get("signal"),
    }


def normalize_cmdsrv(client: dict) -> dict:
    return {
        "ip": client.get("ipaddr") or client.get("ip") or "",
        "mac": (client.get("ethaddr") or client.get("mac") or "").lower(),
        "name": client.get("name") or "",
        "node": client.get("assoc_sn") or client.get("node_serial") or "",
        "online": client.get("online"),
        "uprate": client.get("uprate"),
        "downrate": client.get("downrate"),
        "signal": client.get("signal"),
    }


def fmt(value) -> str:
    return "-" if value is None else str(value)


def print_comparison(tcp_clients: list[dict], cmd_clients: list[dict], selector: str | None) -> None:
    a = {c["mac"]: c for c in map(normalize_tcp9000, tcp_clients) if c["mac"]}
    b = {c["mac"]: c for c in map(normalize_cmdsrv, cmd_clients) if c["mac"]}
    macs = sorted(set(a) | set(b))

    if selector:
        needle = selector.lower()
        macs = [
            mac
            for mac in macs
            if needle in mac
            or needle in (a.get(mac, {}).get("ip", "")).lower()
            or needle in (b.get(mac, {}).get("ip", "")).lower()
            or needle in (a.get(mac, {}).get("name", "")).lower()
            or needle in (b.get(mac, {}).get("name", "")).lower()
        ]

    print("MAC                SOURCE   IP               ON   UP KiB/s  DOWN KiB/s  SIGNAL  NODE                 NAME")
    print("-----------------  -------  ---------------  ---  --------  ----------  ------  -------------------  ------------------------")
    for mac in macs:
        for label, row in (("9000", a.get(mac)), ("12598", b.get(mac))):
            if row is None:
                continue
            print(
                f"{mac:<17}  {label:<7}  {row['ip']:<15}  {fmt(row['online']):>3}  "
                f"{fmt(row['uprate']):>8}  {fmt(row['downrate']):>10}  {fmt(row['signal']):>6}  "
                f"{row['node']:<19}  {row['name']}"
            )
        if mac in a and mac in b:
            diffs = [
                key
                for key in ("ip", "online", "uprate", "downrate", "signal", "node")
                if a[mac].get(key) != b[mac].get(key)
            ]
            if diffs:
                print(" " * 20 + "DIFF: " + ", ".join(diffs))

    only_9000 = sorted(set(a) - set(b))
    only_12598 = sorted(set(b) - set(a))
    print(
        f"\nsummary: tcp9000={len(a)} cmdsrv12598={len(b)} "
        f"only9000={len(only_9000)} only12598={len(only_12598)}"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pcap", required=True, help="classic PCAP containing one successful TCP/9000 LOGIN")
    ap.add_argument("--host", default="192.168.5.1")
    ap.add_argument("--port9000", type=int, default=9000)
    ap.add_argument("--port12598", type=int, default=12598)
    ap.add_argument("--selector", help="optional client name, IP or MAC filter")
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--interval", type=float, default=3.0)
    ap.add_argument("--cmd-timeout", type=float, default=8.0)
    args = ap.parse_args()

    if args.count < 1:
        ap.error("--count must be >= 1")
    if args.interval < 1:
        ap.error("--interval must be >= 1 second")

    login_payload = extract_successful_login_payload(args.pcap)
    print(f"Found successful LOGIN payload ({len(login_payload)} B); content intentionally hidden.")

    for sample in range(1, args.count + 1):
        print(f"\n=== sample {sample}/{args.count} {time.strftime('%H:%M:%S')} ===")
        tcp_clients = get_tcp9000_clients(args.host, args.port9000, login_payload)
        cmd_clients, _raw = get_cmdsrv_clients(args.host, args.port12598, args.cmd_timeout)
        print_comparison(tcp_clients, cmd_clients, args.selector)
        if sample < args.count:
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
