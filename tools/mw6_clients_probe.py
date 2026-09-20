#!/usr/bin/env python3
"""Read-only diagnostic for local MW6 GetHostList over cmdsrv/12598.

This probe tests whether cmdsrv keeps separate Redis command contexts per TCP
frontend when both sockets are established before entering SUBSCRIBE mode.
It sends only PING, SUBSCRIBE and the fixed GetHostList PUBLISH.
"""
from __future__ import annotations

import argparse
import json
import socket
from pathlib import Path

from mw6_cmd_client import (
    CONFCTL_CLIENT_CHANNEL,
    CONFCTL_SERVER_CHANNEL,
    GET_HOST_LIST,
    conf_envelope,
    decode_host_lists,
    frame,
    parse_conf_envelope,
    parse_resp,
    recv_frame,
    resp_bytes,
)


def run(host: str, port: int, timeout: float):
    request = conf_envelope(GET_HOST_LIST)

    # Important difference from the first implementation:
    # establish and warm the command socket BEFORE the subscriber socket enters
    # Redis pub/sub mode. This tells us whether cmdsrv allocates separate backend
    # contexts lazily per accepted frontend connection.
    pub_sock = socket.create_connection((host, port), 3)
    sub_sock = socket.create_connection((host, port), 3)
    try:
        pub_sock.settimeout(timeout)
        sub_sock.settimeout(timeout)

        pub_sock.sendall(frame(resp_bytes(b"PING")))
        pong = parse_resp(recv_frame(pub_sock))
        print("command socket preflight:", pong)
        if pong != "PONG":
            raise RuntimeError(f"unexpected PING result on command socket: {pong!r}")

        sub_sock.sendall(frame(resp_bytes(b"SUBSCRIBE", CONFCTL_CLIENT_CHANNEL)))
        ack = parse_resp(recv_frame(sub_sock))
        print("subscribe ACK:", ack)
        if not (isinstance(ack, list) and len(ack) >= 3 and ack[0] == b"subscribe"):
            raise RuntimeError(f"unexpected subscribe ACK: {ack!r}")

        pub_sock.sendall(frame(resp_bytes(b"PUBLISH", CONFCTL_SERVER_CHANNEL, request)))
        try:
            published = parse_resp(recv_frame(pub_sock))
        except RuntimeError as exc:
            print("PUBLISH failed:", exc)
            print("diagnostic: cmdsrv appears to share one subscribed Redis backend context across frontends")
            return None, None

        print("PUBLISH subscribers:", published)
        if not isinstance(published, int) or published < 1:
            raise RuntimeError(f"confsrv did not receive GetHostList request: {published!r}")

        while True:
            msg = parse_resp(recv_frame(sub_sock))
            if not (isinstance(msg, list) and len(msg) >= 3 and msg[0] == b"message"):
                print("ignoring pubsub message:", msg)
                continue
            body = msg[2]
            if not isinstance(body, bytes):
                continue
            command, payload = parse_conf_envelope(body)
            print("reply command:", command, "payload:", len(payload), "B")
            if command != "GetHostList":
                continue
            return decode_host_lists(payload), payload
    finally:
        sub_sock.close()
        pub_sock.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="192.168.0.1")
    ap.add_argument("--port", type=int, default=12598)
    ap.add_argument("--timeout", type=float, default=8.0)
    ap.add_argument("--raw-out", default="gethostlist.bin")
    args = ap.parse_args()

    clients, raw = run(args.host, args.port, args.timeout)
    if raw is None:
        raise SystemExit(2)
    if args.raw_out:
        Path(args.raw_out).write_bytes(raw)
        print("saved raw:", args.raw_out)
    print(json.dumps(clients, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
