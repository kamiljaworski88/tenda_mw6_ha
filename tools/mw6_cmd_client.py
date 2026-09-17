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

from mw6_hostinfo import decode_host_lists

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
    data = bytearray()
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise EOFError("connection closed")
        data += chunk
    return bytes(data)


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
    value, pos = _resp_value(data, 0)
    if pos != len(data):
        raise ValueError(f"extra RESP bytes: {len(data) - pos}")
    if isinstance(value, RuntimeError):
        raise value
    return value


def conf_envelope(command: bytes, payload: bytes = b"") -> bytes:
    """Build the 36-byte confcli/confsrv envelope."""
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


def rate_diagnostics(clients: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize conditions relevant to firmware fill_host_lists_rate().

    Firmware checks runtime HostInfo+0x20 before rate processing. Current reverse
    mapping associates that slot with the condition-time/runtime eligibility path.
    This diagnostic intentionally does not claim IP/MAC matching succeeded, since
    g_ip_info is not directly exposed by GetHostList.
    """
    rows = []
    for client in clients:
        cond = client.get("condtion_time")
        up = client.get("uprate")
        down = client.get("downrate")
        rows.append(
            {
                "ip": client.get("ipaddr"),
                "mac": client.get("ethaddr"),
                "name": client.get("name"),
                "assoc_sn": client.get("assoc_sn"),
                "online": client.get("online"),
                "condtion_time": cond,
                "rate_gate_nonzero": bool(cond),
                "uprate": up,
                "downrate": down,
                "both_rates_zero": (up or 0) == 0 and (down or 0) == 0,
            }
        )
    return {
        "clients": rows,
        "rate_gate_zero_count": sum(1 for row in rows if not row["rate_gate_nonzero"]),
        "all_rates_zero": bool(rows) and all(row["both_rates_zero"] for row in rows),
        "note": "If rate_gate_nonzero is true but rates remain zero under traffic, next suspect is IP/MAC matching against g_ip_info/online_ip.",
    }


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


def get_clients(host: str, port: int, timeout: float) -> tuple[list[dict[str, Any]], bytes]:
    request = conf_envelope(GET_HOST_LIST)

    # GetHostList is carried over the fixed confcli/confsrv pub/sub bus.
    # cmdrpc@ random channels belong to libcmdctl cmd_get and are not used here.
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
    cp.add_argument(
        "--diagnose-rates",
        action="store_true",
        help="include read-only rate-gate diagnostics derived from GetHostList",
    )

    a = ap.parse_args()

    if a.cmd == "clients":
        clients, raw = get_clients(a.host, a.port, a.timeout)
        if a.raw_out:
            Path(a.raw_out).write_bytes(raw)
        output: Any = clients
        if a.diagnose_rates:
            output = {"clients": clients, "rate_diagnostics": rate_diagnostics(clients)}
        print(json.dumps(output, ensure_ascii=False, indent=2 if a.pretty else None))
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
