#!/usr/bin/env python3
"""Offline helper for analysing Tenda MW6 device_list ELF.

Usage:
    python tools/device_list_extract.py ./device_list

No router connection is made. The script extracts printable strings, highlights
client-list/IPC/rate-related strings and shows nearby strings by file offset.
"""
from __future__ import annotations
import argparse
import re
from pathlib import Path

KEYWORDS = (
    "client", "device", "upload", "cmd_", "redis", "rate", "speed", "traffic",
    "ip_info", "mac", "dhcp", "wifi", "roam", "ifname", "node", "socket",
    "cloud", "pub", "sub",
)


def strings_with_offsets(data: bytes, min_len: int = 4):
    rx = re.compile(rb"[\x20-\x7e]{%d,}" % min_len)
    return [(m.start(), m.group().decode("ascii", "replace")) for m in rx.finditer(data)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("elf", type=Path)
    ap.add_argument("--context", type=int, default=5)
    args = ap.parse_args()
    data = args.elf.read_bytes()
    rows = strings_with_offsets(data)
    print(f"file={args.elf} bytes={len(data)} strings={len(rows)}")
    hits = [i for i, (_, s) in enumerate(rows) if any(k in s.lower() for k in KEYWORDS)]
    shown = set()
    for i in hits:
        lo, hi = max(0, i-args.context), min(len(rows), i+args.context+1)
        if any(j in shown for j in range(lo, hi)):
            continue
        print("\n---")
        for j in range(lo, hi):
            off, s = rows[j]
            mark = ">" if j == i else " "
            print(f"{mark} 0x{off:08x}  {s}")
            shown.add(j)


if __name__ == "__main__":
    main()
