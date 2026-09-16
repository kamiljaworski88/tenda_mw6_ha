#!/usr/bin/env python3
"""Read-only Tenda MW6 cmdsrv client.

Recovered local transport on TCP/12598:
  u32le frame_len (= 8 + compressed_len)
  u32le XXH32(compressed, seed=0)
  u32le uncompressed_len
  LZ4 block(RESP bytes + magic f7 c6 89 be)

Public CLI intentionally exposes only read-only operations:
  ping, get, subscribe, clients

`clients` is a dedicated fixed GetHostList RPC. It does NOT expose a generic
PUBLISH/SET primitive to the user.
"""
from __future__ import annotations

import argparse
import json
import socket
import struct
from pathlib import Path
from typing import Any

MAGIC = bytes.fromhex("f7 c6 89 be")
MASK32 = 0xFFFFFFFF
P1, P2, P3, P4, P5 = 0x9E3779B1, 0x85EBCA77, 0xC2B2AE3D, 0x27D4EB2F, 0x165667B1

CONFCTL_SERVER_CHANNEL = b"confctl_srv_key"
CONFCTL_CLIENT_CHANNEL = b"confctl_cli_key"
GET_HOST_LIST = b"GetHostList"


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
            v1 = rnd(v1, int.from_bytes(data[p : p + 4], "little"))
            v2 = rnd(v2, int.from_bytes(data[p + 4 : p + 8], "little"))
            v3 = rnd(v3, int.from_bytes(data[p + 8 : p + 12], "little"))
            v4 = rnd(v4, int.from_bytes(data[p + 12 : p + 16], "little"))
            p += 16
        h = (rol(v1, 1) + rol(v2, 7) + rol(v3, 12) + rol(v4, 18)) & MASK32
    else:
        h = (seed + P5) & MASK32
    h = (h + n) & MASK32
    while p <= n - 4:
        h = (h + int.from_bytes(data[p : p + 4], "little") * P3) & MASK32
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
        out += src[i : i + lit]
        i += lit
        if i >= len(src):
            break
        off = src[i] | (src[i + 1] << 8)
        i += 2
        if not off or off > len(out):
            raise ValueError("invalid LZ4 offset")
        m = token & 15
        if m == 15:
            while True:
                x = src[i]
                i += 1
                m += x
                if x != 255:
                    break
        m += 4
        for _ in range(m):
            out.append(out[-off])
    if len(out) != expected:
        raise ValueError(f"LZ4 size {len(out)} != {expected}")
    return bytes(out)


def resp_bytes(*args: bytes | str) -> bytes:
    chunks = [f"*{len(args)}\r\n".encode()]
    for arg in args:
        x = arg.encode() if isinstance(arg, str) else arg
        chunks += [f"${len(x)}\r\n".encode(), x, b"\r\n"]
    return b"".join(chunks)


def frame(payload: bytes) -> bytes:
    plain = payload + MAGIC
    comp = lz4_literals(plain)
    return struct.pack("<III", len(comp) + 8, xxh32(comp), len(plain)) + comp


def recv_exact(sock: socket.socket, n: int) -> bytes:
    b = bytearray()
    while len(b) < n:
        x = sock.recv(n - len(b))
        if not x:
            raise EOFError("connection closed")
        b += x
    return bytes(b)


def recv_frame(sock: socket.socket) -> bytes:
    flen = struct.unpack("<I", recv_exact(sock, 4))[0]
    if flen < 8 or flen > 1024 * 1024:
        raise ValueError(f"invalid frame length {flen}")
    body = recv_exact(sock, flen)
    checksum, usize = struct.unpack("<II", body[:8])
    comp = body[8:]
    if xxh32(comp) != checksum:
        raise ValueError("XXH32 mismatch")
    plain = lz4_decompress(comp, usize)
    if not plain.endswith(MAGIC):
        raise ValueError("MW6 magic mismatch")
    return plain[:-4]


def _resp_value(data: bytes, pos: int = 0) -> tuple[Any, int]:
    if pos >= len(data):
        raise ValueError("truncated RESP")
    kind = data[pos : pos + 1]
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
        if end + 2 > len(data) or data[end : end + 2] != b"\r\n":
            raise ValueError("truncated RESP bulk string")
        value = data[pos:end]
        return value, end + 2
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
    value, pos = _resp_value(data, 0)
    if pos != len(data):
        raise ValueError(f"extra RESP bytes: {len(data) - pos}")
    if isinstance(value, RuntimeError):
        raise value
    return value


def conf_envelope(command: bytes, payload: bytes = b"") -> bytes:
    """Build the 36-byte conf message header recovered from confcli/confsrv.

    Layout:
      0..31  NUL-padded command name
      32..35 little-endian payload length
      36..   payload
    """
    if len(command) > 31:
        raise ValueError("conf command name too long")
    return command + b"\x00" * (32 - len(command)) + struct.pack("<I", len(payload)) + payload


def parse_conf_envelope(data: bytes) -> tuple[str, bytes]:
    if len(data) < 36:
        raise ValueError(f"conf response too short: {len(data)} B")
    command = data[:32].split(b"\x00", 1)[0].decode("ascii", "replace")
    n = struct.unpack_from("<I", data, 32)[0]
    if n > len(data) - 36:
        raise ValueError(f"conf payload length {n} exceeds available {len(data) - 36}")
    return command, data[36 : 36 + n]


def _varint(data: bytes, pos: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while True:
        if pos >= len(data) or shift >= 70:
            raise ValueError("invalid protobuf varint")
        b = data[pos]
        pos += 1
        value |= (b & 0x7F) << shift
        if not b & 0x80:
            return value, pos
        shift += 7


def protobuf_fields(data: bytes) -> list[tuple[int, int, Any]]:
    out = []
    pos = 0
    while pos < len(data):
        key, pos = _varint(data, pos)
        field, wire = key >> 3, key & 7
        if field == 0:
            raise ValueError("protobuf field 0")
        if wire == 0:
            value, pos = _varint(data, pos)
        elif wire == 1:
            if pos + 8 > len(data):
                raise ValueError("truncated fixed64")
            value = int.from_bytes(data[pos : pos + 8], "little")
            pos += 8
        elif wire == 2:
            n, pos = _varint(data, pos)
            if pos + n > len(data):
                raise ValueError("truncated length-delimited field")
            value = data[pos : pos + n]
            pos += n
        elif wire == 5:
            if pos + 4 > len(data):
                raise ValueError("truncated fixed32")
            value = int.from_bytes(data[pos : pos + 4], "little")
            pos += 4
        else:
            raise ValueError(f"unsupported protobuf wire type {wire}")
        out.append((field, wire, value))
    return out


def _text_or_hex(value: bytes) -> str:
    try:
        text = value.decode("utf-8")
        if text and all(ch.isprintable() or ch in "\t\r\n" for ch in text):
            return text
    except UnicodeDecodeError:
        pass
    return value.hex()


def decode_host_message(data: bytes) -> dict[str, Any]:
    """Decode one HostInfo without pretending unresolved field semantics are known."""
    raw: dict[str, Any] = {}
    for field, wire, value in protobuf_fields(data):
        key = f"f{field}"
        if wire == 2:
            raw[key] = _text_or_hex(value)
        else:
            raw[key] = value

    # Live captures established f7/f8 as the two rate fields. Direction and unit
    # are intentionally left neutral until the controlled live transfer test.
    return {
        "fields": raw,
        "rate_a": raw.get("f7"),
        "rate_b": raw.get("f8"),
    }


def decode_host_lists(payload: bytes) -> list[dict[str, Any]]:
    """Decode HostLists repeated embedded HostInfo messages.

    We accept every length-delimited outer field that itself parses as protobuf;
    this keeps the tool robust while exact HostLists descriptor field numbering is
    still being finalized from libpb.so.
    """
    hosts = []
    for outer_field, wire, value in protobuf_fields(payload):
        if wire != 2 or not isinstance(value, bytes):
            continue
        try:
            fields = protobuf_fields(value)
        except ValueError:
            continue
        if not fields:
            continue
        host = decode_host_message(value)
        host["outer_field"] = outer_field
        hosts.append(host)
    return hosts


def show(data: bytes, index: int, capture_dir: Path | None) -> None:
    print(f"\n--- message {index}: {len(data)} B ---")
    try:
        print(data.decode("utf-8").rstrip())
    except UnicodeDecodeError:
        print("BINARY HEX:", data.hex(" "))
    if capture_dir:
        capture_dir.mkdir(parents=True, exist_ok=True)
        p = capture_dir / f"mw6_message_{index:04d}.bin"
        p.write_bytes(data)
        print("saved:", p)


def get_clients(host: str, port: int, timeout: float) -> tuple[list[dict[str, Any]], bytes]:
    request = conf_envelope(GET_HOST_LIST)

    # confsrv listens on confctl_srv_key. Replies are delivered on the fixed
    # confctl_cli_key bus. Subscribe first so the reply cannot race us.
    with socket.create_connection((host, port), 3) as sub_sock:
        sub_sock.settimeout(timeout)
        sub_sock.sendall(frame(resp_bytes(b"SUBSCRIBE", CONFCTL_CLIENT_CHANNEL)))
        ack = parse_resp(recv_frame(sub_sock))
        if not (isinstance(ack, list) and len(ack) >= 3 and ack[0] == b"subscribe"):
            raise RuntimeError(f"unexpected subscribe ACK: {ack!r}")

        with socket.create_connection((host, port), 3) as pub_sock:
            pub_sock.settimeout(timeout)
            pub_sock.sendall(frame(resp_bytes(b"PUBLISH", CONFCTL_SERVER_CHANNEL, request)))
            published = parse_resp(recv_frame(pub_sock))
            if not isinstance(published, int):
                raise RuntimeError(f"unexpected PUBLISH result: {published!r}")
            if published < 1:
                raise RuntimeError("confsrv did not receive GetHostList request")

        while True:
            msg = parse_resp(recv_frame(sub_sock))
            if not (isinstance(msg, list) and len(msg) >= 3 and msg[0] == b"message"):
                continue
            body = msg[2]
            if not isinstance(body, bytes):
                continue
            command, payload = parse_conf_envelope(body)
            if command != "GetHostList":
                continue
            return decode_host_lists(payload), payload


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="192.168.5.1")
    ap.add_argument("--port", type=int, default=12598)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ping")
    gp = sub.add_parser("get", help="read one Redis key through cmdsrv")
    gp.add_argument("key")
    sp = sub.add_parser("subscribe")
    sp.add_argument("channel")
    sp.add_argument("--count", type=int, default=0, help="0 = listen until Ctrl+C")
    sp.add_argument("--timeout", type=float, default=0, help="0 = no read timeout")
    sp.add_argument("--capture-dir", default="mw6_capture")
    cp = sub.add_parser("clients", help="read local MW6 GetHostList (read-only)")
    cp.add_argument("--timeout", type=float, default=8.0)
    cp.add_argument("--raw-out", help="optionally save raw packed HostLists protobuf")
    cp.add_argument("--pretty", action="store_true", help="pretty JSON output")
    a = ap.parse_args()

    if a.cmd == "clients":
        clients, raw = get_clients(a.host, a.port, a.timeout)
        if a.raw_out:
            Path(a.raw_out).write_bytes(raw)
        print(json.dumps(clients, ensure_ascii=False, indent=2 if a.pretty else None))
        return

    if a.cmd == "ping":
        command = ("PING",)
        limit = 1
        timeout = 10
        capture = None
    elif a.cmd == "get":
        command = ("GET", a.key)
        limit = 1
        timeout = 10
        capture = None
    else:
        command = ("SUBSCRIBE", a.channel)
        limit = a.count
        timeout = a.timeout or None
        capture = Path(a.capture_dir)

    with socket.create_connection((a.host, a.port), 3) as sock:
        sock.settimeout(timeout)
        sock.sendall(frame(resp_bytes(*command)))
        i = 0
        try:
            while limit == 0 or i < limit:
                data = recv_frame(sock)
                i += 1
                show(data, i, capture)
        except KeyboardInterrupt:
            print(f"\nStopped. Received {i} message(s).")
        except TimeoutError:
            print(f"\nNo new message. Received {i} message(s).")


if __name__ == "__main__":
    main()
