#!/usr/bin/env python3
"""Extract the MW6 32-character LOGIN account from a classic PCAP capture.

The script never prints the value unless --show is explicitly supplied.
It is intended for local setup of the Home Assistant integration.
"""
from __future__ import annotations

import argparse
import struct
from pathlib import Path

PORT = 9000
MAGIC = b"\x24\x00"
REQ_KIND = 0x07
RESP_KIND = 0x06
AUTH_MODULE = 0x18
AUTH_LOGIN = 0x01


def tcp_payloads(path: Path):
    with path.open("rb") as handle:
        global_header = handle.read(24)
        if len(global_header) != 24:
            raise ValueError("invalid or truncated PCAP")
        magic = global_header[:4]
        if magic == b"\xd4\xc3\xb2\xa1":
            endian = "<"
        elif magic == b"\xa1\xb2\xc3\xd4":
            endian = ">"
        else:
            raise ValueError("classic PCAP required (PCAPNG is not supported by this helper)")
        linktype = struct.unpack(endian + "I", global_header[20:24])[0]
        if linktype != 101:
            raise ValueError(f"expected DLT_RAW=101, got {linktype}")

        while True:
            packet_header = handle.read(16)
            if not packet_header:
                return
            if len(packet_header) != 16:
                raise ValueError("truncated PCAP packet header")
            _, _, included_len, _ = struct.unpack(endian + "IIII", packet_header)
            packet = handle.read(included_len)
            if len(packet) != included_len:
                raise ValueError("truncated PCAP packet")
            if len(packet) < 40 or packet[0] >> 4 != 4 or packet[9] != 6:
                continue
            ihl = (packet[0] & 0x0F) * 4
            if len(packet) < ihl + 20:
                continue
            sport, dport = struct.unpack("!HH", packet[ihl : ihl + 4])
            data_offset = ((packet[ihl + 12] >> 4) & 0x0F) * 4
            payload = packet[ihl + data_offset :]
            if payload and (sport == PORT or dport == PORT):
                yield sport, dport, payload


def parse_frame(raw: bytes):
    if len(raw) < 16 or raw[:2] != MAGIC:
        return None
    size = int.from_bytes(raw[6:8], "big")
    if len(raw) < 16 + size:
        return None
    return {
        "kind": raw[2],
        "tid": raw[3],
        "module": raw[8],
        "command": raw[9],
        "payload": raw[16 : 16 + size],
    }


def account_from_login_payload(payload: bytes) -> str:
    if len(payload) != 36 or payload[:2] != b"\x0a\x20" or payload[34:] != b"\x12\x00":
        raise ValueError("unsupported LoginMsg payload shape")
    account = payload[2:34].decode("ascii", "strict")
    if len(account) != 32 or any(ch not in "0123456789abcdefABCDEF" for ch in account):
        raise ValueError("LoginMsg account is not a 32-character hexadecimal value")
    return account


def extract_successful_account(path: Path) -> str:
    requests: dict[int, bytes] = {}
    for sport, dport, raw in tcp_payloads(path):
        frame = parse_frame(raw)
        if frame is None:
            continue
        if (
            dport == PORT
            and frame["kind"] == REQ_KIND
            and frame["module"] == AUTH_MODULE
            and frame["command"] == AUTH_LOGIN
        ):
            requests[frame["tid"]] = frame["payload"]
            continue
        if (
            sport == PORT
            and frame["kind"] == RESP_KIND
            and frame["module"] == AUTH_MODULE
            and frame["command"] == AUTH_LOGIN
            and len(frame["payload"]) >= 4
            and frame["payload"][:4] == b"\x00\x00\x00\x00"
            and frame["tid"] in requests
        ):
            return account_from_login_payload(requests[frame["tid"]])
    raise RuntimeError("no successful MW6 LOGIN exchange found in the capture")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pcap", type=Path, help="classic DLT_RAW PCAP captured from the official app")
    parser.add_argument(
        "--show",
        action="store_true",
        help="print the sensitive 32-character login account for entering into Home Assistant",
    )
    args = parser.parse_args()

    account = extract_successful_account(args.pcap)
    if args.show:
        print(account)
    else:
        print("Successful MW6 LOGIN found. Account value is hidden; rerun with --show to display it locally.")


if __name__ == "__main__":
    main()
