#!/usr/bin/env python3
"""Read-only Tenda MW6 cmdsrv client for TCP/12598.

Recovered wire transport:
  u32le frame_len (= 8 + compressed_len)
  u32le XXH32(compressed, seed=0)
  u32le uncompressed_len
  LZ4 block(RESP bytes + magic f7 c6 89 be)

This utility intentionally exposes only Redis-side read/observe operations:
  ping, get, subscribe

Client discovery is NOT implemented here. Static analysis of confsrv shows that
its GetHostList handler returns an out-buffer to the in-process dispatcher and
that the dispatcher frees that buffer; a fixed confctl_cli_key subscription is
therefore not a valid GetHostList response path. Use mw6_probe.py / TCP 9000 for
client discovery instead.
"""
from __future__ import annotations

import argparse
import socket
import struct
from pathlib import Path
from typing import Any

MAGIC = bytes.fromhex("f7 c6 89 be")
MASK32 = 0xFFFFFFFF
P1, P2, P3, P4, P5 = 0x9E3779B1, 0x85EBCA77, 0xC2B2AE3D, 0x27D4EB2F, 0x165667B1


def rol(x: int, n: int) -> int:
    return ((x << n) | (x >> (32 - n))) & MASK32


def xxh32(data: bytes, seed: int = 0) -> int:
    n = len(data)
    p = 0

    def rnd(a: int, b: int) -> int:
        return (rol((a + b * P2) & MASK32, 13) * P1) & MASK32

    if n >= 16:
        v1 = (seed + P1 + P2) & MASK32
        v2 = (seed + P2) & MASK32
        v3 = seed & MASK32
        v4 = (seed - P1) & MASK32
        while p <= n - 16:
            v1 = rnd(v1, int.from_bytes(data[p:p + 4], "little"))
            v2 = rnd(v2, int.from_bytes(data[p + 4:p + 8], "little"))
            v3 = rnd(v3, int.from_bytes(data[p + 8:p + 12], "little"))
            v4 = rnd(v4, int.from_bytes(data[p + 12:p + 16], "little"))
            p += 16
        h = (rol(v1, 1) + rol(v2, 7) + rol(v3, 12) + rol(v4, 18)) & MASK32
    else:
        h = (seed + P5) & MASK32
    h = (h + n) & MASK32
    while p <= n - 4:
        h = (h + int.from_bytes(data[p:p + 4], "little") * P3) & MASK32
        h = (rol(h, 17) * P4) & MASK32
        p += 4
    while p < n:
        h = (h + data[p] * P5) & MASK32
        h = (rol(h, 11) * P1) & MASK32
        p += 1
    h ^= h >> 15
    h = (h * P2) & MASK32
    h ^= h >> 13
    h = (h * P3) & MASK32
    h ^= h >> 16
    return h & MASK32


def lz4_literals(data: bytes) -> bytes:
    n = len(data)
    out = bytearray()
    out.append(min(n, 15) << 4)
    if n >= 15:
        x = n - 15
        while x >= 255:
            out.append(255)
            x -= 255
        out.append(x)
    out += data
    return bytes(out)


def lz4_decompress(src: bytes, expected: int) -> bytes:
    i = 0
    out = bytearray()
    while i < len(src):
        token = src[i]
        i += 1
        lit = token >> 4
        if lit == 15:
            while True:
                x = src[i]
                i += 1
                lit += x
                if x != 255:
                    break
        out += src[i:i + lit]
        i += lit
        if i >= len(src):
            break
        off = src[i] | (src[i + 1] << 8)
        i += 2
        if not off or off > len(out):
            raise ValueError("invalid LZ4 offset")
        match = token & 15
        if match == 15:
            while True:
                x = src[i]
                i += 1
                match += x
                if x != 255:
                    break
        match += 4
        for _ in range(match):
            out.append(out[-off])
    if len(out) != expected:
        raise ValueError(f"LZ4 size {len(out)} != {expected}")
    return bytes(out)


def resp_bytes(*args: bytes | str) -> bytes:
    chunks = [f"*{len(args)}\r\n".encode()]
    for arg in args:
        value = arg.encode() if isinstance(arg, str) else arg
        chunks += [f"${len(value)}\r\n".encode(), value, b"\r\n"]
    return b"".join(chunks)


def frame(payload: bytes) -> bytes:
    plain = payload + MAGIC
    compressed = lz4_literals(plain)
    return struct.pack("<III", len(compressed) + 8, xxh32(compressed), len(plain)) + compressed


def recv_exact(sock: socket.socket, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise EOFError("connection closed")
        data += chunk
    return bytes(data)


def recv_frame(sock: socket.socket) -> bytes:
    frame_len = struct.unpack("<I", recv_exact(sock, 4))[0]
    if frame_len < 8 or frame_len > 1024 * 1024:
        raise ValueError(f"invalid frame length {frame_len}")
    body = recv_exact(sock, frame_len)
    checksum, uncompressed_size = struct.unpack("<II", body[:8])
    compressed = body[8:]
    if xxh32(compressed) != checksum:
        raise ValueError("XXH32 mismatch")
    plain = lz4_decompress(compressed, uncompressed_size)
    if not plain.endswith(MAGIC):
        raise ValueError("MW6 magic mismatch")
    return plain[:-4]


def _resp_value(data: bytes, pos: int = 0) -> tuple[Any, int]:
    if pos >= len(data):
        raise ValueError("truncated RESP")
    kind = data[pos:pos + 1]
    pos += 1

    def line() -> bytes:
        nonlocal pos
        end = data.find(b"\r\n", pos)
        if end < 0:
            raise ValueError("truncated RESP line")
        value = data[pos:end]
        pos = end + 2
        return value

    if kind == b"+":
        return line().decode("utf-8", "replace"), pos
    if kind == b"-":
        return RuntimeError(line().decode("utf-8", "replace")), pos
    if kind == b":":
        return int(line()), pos
    if kind == b"$":
        n = int(line())
        if n < 0:
            return None, pos
        end = pos + n
        if end + 2 > len(data) or data[end:end + 2] != b"\r\n":
            raise ValueError("truncated RESP bulk string")
        return data[pos:end], end + 2
    if kind == b"*":
        n = int(line())
        if n < 0:
            return None, pos
        out = []
        for _ in range(n):
            value, pos = _resp_value(data, pos)
            out.append(value)
        return out, pos
    raise ValueError(f"unsupported RESP type {kind!r}")


def parse_resp(data: bytes) -> Any:
    value, pos = _resp_value(data)
    if pos != len(data):
        raise ValueError(f"extra RESP bytes: {len(data) - pos}")
    if isinstance(value, RuntimeError):
        raise value
    return value


def show(data: bytes, index: int, capture_dir: Path | None) -> None:
    print(f"\n--- message {index}: {len(data)} B ---")
    try:
        print(data.decode("utf-8").rstrip())
    except UnicodeDecodeError:
        print("BINARY HEX:", data.hex(" "))
    if capture_dir:
        capture_dir.mkdir(parents=True, exist_ok=True)
        path = capture_dir / f"mw6_message_{index:04d}.bin"
        path.write_bytes(data)
        print("saved:", path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="192.168.5.1")
    parser.add_argument("--port", type=int, default=12598)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("ping")
    get_parser = sub.add_parser("get", help="read one Redis key through cmdsrv")
    get_parser.add_argument("key")
    sub_parser = sub.add_parser("subscribe", help="observe one Redis pub/sub channel")
    sub_parser.add_argument("channel")
    sub_parser.add_argument("--count", type=int, default=0, help="0 = listen until Ctrl+C")
    sub_parser.add_argument("--timeout", type=float, default=0, help="0 = no read timeout")
    sub_parser.add_argument("--capture-dir", default="mw6_capture")

    args = parser.parse_args()
    if args.cmd == "ping":
        command = ("PING",)
        limit = 1
        timeout = 10
        capture = None
    elif args.cmd == "get":
        command = ("GET", args.key)
        limit = 1
        timeout = 10
        capture = None
    else:
        command = ("SUBSCRIBE", args.channel)
        limit = args.count
        timeout = args.timeout or None
        capture = Path(args.capture_dir)

    with socket.create_connection((args.host, args.port), 3) as sock:
        sock.settimeout(timeout)
        sock.sendall(frame(resp_bytes(*command)))
        count = 0
        try:
            while limit == 0 or count < limit:
                data = recv_frame(sock)
                count += 1
                show(data, count, capture)
        except KeyboardInterrupt:
            print(f"\nStopped. Received {count} message(s).")
        except TimeoutError:
            print(f"\nNo new message. Received {count} message(s).")


if __name__ == "__main__":
    main()
