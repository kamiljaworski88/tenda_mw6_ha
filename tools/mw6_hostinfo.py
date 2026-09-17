#!/usr/bin/env python3
"""Resolved protobuf decoder for Tenda MW6 HostLists/HostInfo.

Recovered from firmware libpb.so / onhosts.pb-c.c descriptor strings.
This module is read-only and has no network side effects.

HostInfo protobuf fields:
  1 ipaddr
  2 ethaddr
  3 access
  4 assoc_sn
  5 condtion_time   (spelling preserved from firmware)
  6 online
  7 uprate          (integer KiB/s)
  8 downrate        (integer KiB/s)
  9 signal
 10 name

HostLists contains repeated HostInfo messages. Firmware descriptor strings name
that collection `hosts`; observed wire data uses length-delimited embedded
messages.
"""
from __future__ import annotations

from typing import Any


HOSTINFO_FIELDS = {
    1: "ipaddr",
    2: "ethaddr",
    3: "access",
    4: "assoc_sn",
    5: "condtion_time",
    6: "online",
    7: "uprate",
    8: "downrate",
    9: "signal",
    10: "name",
}

TEXT_FIELDS = {1, 2, 3, 4, 10}
SIGNED_INT32_FIELDS = {9}


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
    out: list[tuple[int, int, Any]] = []
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
            value = int.from_bytes(data[pos:pos + 8], "little")
            pos += 8
        elif wire == 2:
            n, pos = _varint(data, pos)
            if pos + n > len(data):
                raise ValueError("truncated length-delimited field")
            value = data[pos:pos + n]
            pos += n
        elif wire == 5:
            if pos + 4 > len(data):
                raise ValueError("truncated fixed32")
            value = int.from_bytes(data[pos:pos + 4], "little")
            pos += 4
        else:
            raise ValueError(f"unsupported protobuf wire type {wire}")
        out.append((field, wire, value))
    return out


def _signed32(value: int) -> int:
    value &= 0xFFFFFFFF
    return value - 0x100000000 if value & 0x80000000 else value


def _text(value: bytes) -> str:
    return value.decode("utf-8", "replace").rstrip("\x00")


def decode_host_info(data: bytes) -> dict[str, Any]:
    host: dict[str, Any] = {}
    unknown: dict[str, Any] = {}

    for field, wire, value in protobuf_fields(data):
        name = HOSTINFO_FIELDS.get(field)
        if name is None:
            unknown[f"f{field}"] = value.hex() if isinstance(value, bytes) else value
            continue

        if field in TEXT_FIELDS:
            if wire != 2 or not isinstance(value, bytes):
                unknown[f"f{field}_wire"] = wire
                unknown[f"f{field}_raw"] = value.hex() if isinstance(value, bytes) else value
                continue
            host[name] = _text(value)
        elif field in SIGNED_INT32_FIELDS:
            if not isinstance(value, int):
                unknown[f"f{field}_raw"] = value
                continue
            host[name] = _signed32(value)
        else:
            host[name] = value

    # Normalized aliases useful to Home Assistant later.
    host["ip"] = host.get("ipaddr")
    host["mac"] = host.get("ethaddr")
    host["node_serial"] = host.get("assoc_sn")
    host["is_online"] = bool(host.get("online", 0))

    # Firmware computes these as byte-counter delta / elapsed seconds / 1024.
    # Keep the raw aliases for compatibility and expose the resolved unit too.
    host["upload_rate_raw"] = host.get("uprate")
    host["download_rate_raw"] = host.get("downrate")
    host["upload_rate_kib_s"] = host.get("uprate")
    host["download_rate_kib_s"] = host.get("downrate")

    if unknown:
        host["unknown_fields"] = unknown
    return host


def decode_host_lists(payload: bytes) -> list[dict[str, Any]]:
    """Decode HostLists repeated HostInfo messages.

    Primary expectation is field 1 = repeated HostInfo. A cautious fallback
    accepts any embedded message that contains at least IP or MAC, which helps
    while validating different MW6 firmware builds without misclassifying
    arbitrary scalar fields as clients.
    """
    hosts: list[dict[str, Any]] = []
    fallback: list[dict[str, Any]] = []

    for outer_field, wire, value in protobuf_fields(payload):
        if wire != 2 or not isinstance(value, bytes):
            continue
        try:
            host = decode_host_info(value)
        except ValueError:
            continue
        if not (host.get("ipaddr") or host.get("ethaddr")):
            continue
        host["_outer_field"] = outer_field
        if outer_field == 1:
            hosts.append(host)
        else:
            fallback.append(host)

    return hosts or fallback
