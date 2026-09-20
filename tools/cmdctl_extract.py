#!/usr/bin/env python3
"""Offline string/symbol triage for MW6 cmdsrv/cmdcli/cmdctl_test/libcmdctl binaries.

No network access. Point it at one or more binaries extracted from firmware.
It prints printable strings relevant to the internal command/Redis transport,
with byte offsets, while suppressing unrelated noise.
"""
import argparse
import re
from pathlib import Path

KEYS = (
    "cmd_", "redis", "subscribe", "publish", "channel", "topic", "socket",
    "tcp://", "unix", "request", "reply", "timeout", "benchmark", "shell",
    "get", "set", "pub", "sub", "json", "sds", "12598", "6379",
)


def strings(data: bytes, min_len: int = 4):
    rx = re.compile(rb"[\x20-\x7e]{%d,}" % min_len)
    for m in rx.finditer(data):
        yield m.start(), m.group().decode("ascii", "replace")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--all", action="store_true", help="show all printable strings")
    args = ap.parse_args()

    for name in args.files:
        p = Path(name)
        data = p.read_bytes()
        print(f"\n=== {p} ({len(data)} bytes) ===")
        for off, text in strings(data):
            low = text.lower()
            if args.all or any(k in low for k in KEYS):
                print(f"0x{off:08x}  {text}")


if __name__ == "__main__":
    main()
