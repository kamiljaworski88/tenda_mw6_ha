#!/usr/bin/env python3
"""Watch live MW6 HostInfo online/uprate/downrate through local cmdsrv/12598.

Read-only runtime probe. No Tenda cloud and no TCP/9000 login payload are used.
The firmware schema resolves uprate/downrate as integer KiB/s.
"""
from __future__ import annotations

import argparse
import time

from mw6_cmd_client import get_clients


def matches(client: dict, selector: str | None) -> bool:
    if not selector:
        return True
    needle = selector.casefold()
    return any(
        needle in str(client.get(key) or "").casefold()
        for key in ("ipaddr", "ethaddr", "name", "assoc_sn")
    )


def val(value) -> str:
    return "-" if value is None else str(value)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="192.168.0.1")
    ap.add_argument("--port", type=int, default=12598)
    ap.add_argument("--timeout", type=float, default=8.0)
    ap.add_argument("--selector", help="client name, IP, MAC or mesh-node serial substring")
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--interval", type=float, default=2.0)
    args = ap.parse_args()

    if args.count < 1:
        ap.error("--count must be >= 1")
    if args.interval < 0.5:
        ap.error("--interval must be >= 0.5 seconds")

    saw_client = False
    saw_online = False
    saw_nonzero_rate = False

    print("TIME      IP               MAC                ON  UP KiB/s  DOWN KiB/s  SIGNAL  NODE                 NAME")
    print("--------  ---------------  -----------------  --  --------  ----------  ------  -------------------  ------------------------")

    for sample in range(args.count):
        clients, _raw = get_clients(args.host, args.port, args.timeout)
        selected = [client for client in clients if matches(client, args.selector)]

        if not selected:
            print(f"{time.strftime('%H:%M:%S')}  no matching client")
        else:
            saw_client = True
            for client in selected:
                online = client.get("online")
                up = client.get("uprate")
                down = client.get("downrate")
                saw_online = saw_online or bool(online)
                saw_nonzero_rate = saw_nonzero_rate or bool(up) or bool(down)
                print(
                    f"{time.strftime('%H:%M:%S')}  "
                    f"{str(client.get('ipaddr') or ''):<15}  "
                    f"{str(client.get('ethaddr') or ''):<17}  "
                    f"{val(online):>2}  {val(up):>8}  {val(down):>10}  "
                    f"{val(client.get('signal')):>6}  "
                    f"{str(client.get('assoc_sn') or ''):<19}  "
                    f"{str(client.get('name') or '')}"
                )

        if sample + 1 < args.count:
            time.sleep(args.interval)

    print()
    if not saw_client:
        print("result: no matching client was returned by GetHostList")
    elif saw_nonzero_rate:
        print("result: PASS — cmdsrv/12598 returned a non-zero per-client rate")
    elif saw_online:
        print("result: online is non-zero, but all observed rates stayed at 0; investigate strict IP+MAC match to g_ip_info")
    else:
        print("result: online and both rates stayed at 0; compare with TCP/9000 for the same client")


if __name__ == "__main__":
    main()
