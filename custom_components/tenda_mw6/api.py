from __future__ import annotations

from dataclasses import dataclass
import re
import socket
from typing import Any

MAGIC = b"\x24\x00"
REQ_KIND = 0x07
RESP_KIND = 0x06
FIXED = b"\x00\xd5"
AUTH_MODULE = 0x18
AUTH_GET_STA = 0x00
AUTH_LOGIN = 0x01
MESH_HOSTS_MODULE = 0x14
MESH_HOSTS_GET = 0x00
LOGIN_ACCOUNT_RE = re.compile(r"^[0-9a-fA-F]{32}$")


class TendaMW6Error(Exception):
    """Base exception for the Tenda MW6 local protocol."""


class TendaMW6AuthError(TendaMW6Error):
    """Raised when the router rejects the login account."""


@dataclass(slots=True)
class TendaMW6Client:
    ip: str
    mac: str
    name: str
    node_sn: str
    signal: int | None
    access: str | None
    condition_time: int | None
    raw_online: int | None
    raw_uprate: int | None
    raw_downrate: int | None


@dataclass(frozen=True, slots=True)
class TendaMW6InventorySummary:
    """Summary of the HostList inventory freshness reported by the router."""

    total_clients: int
    reported_online: int
    reported_offline: int
    unknown_online_state: int
    all_reported_offline: bool


def summarize_inventory(clients: list[TendaMW6Client]) -> TendaMW6InventorySummary:
    """Summarize the firmware's reported online flags without guessing traffic state.

    The MW6 rate helper skips a client when its reported online flag is zero.
    A non-empty HostList in which every record is zero is therefore exposed as
    a diagnostic condition, not silently treated as zero client traffic.
    """
    reported_online = sum(
        1 for client in clients if client.raw_online is not None and client.raw_online != 0
    )
    reported_offline = sum(1 for client in clients if client.raw_online == 0)
    unknown_online_state = len(clients) - reported_online - reported_offline
    return TendaMW6InventorySummary(
        total_clients=len(clients),
        reported_online=reported_online,
        reported_offline=reported_offline,
        unknown_online_state=unknown_online_state,
        all_reported_offline=bool(clients) and reported_offline == len(clients),
    )


@dataclass(frozen=True, slots=True)
class TendaMW6TransferReadiness:
    """Whether the current HostList can safely drive local transfer counters."""

    eligible_clients: int
    clients_with_rate: int
    clients_with_upload_rate: int
    clients_with_download_rate: int
    inventory_all_reported_offline: bool


def summarize_transfer_readiness(
    clients: list[TendaMW6Client],
) -> TendaMW6TransferReadiness:
    """Summarize only non-zero rates from clients with fresh inventory state."""
    inventory = summarize_inventory(clients)
    eligible = [
        client
        for client in clients
        if client.raw_online is not None and client.raw_online != 0
    ]
    clients_with_upload_rate = sum(
        1 for client in eligible if client.raw_uprate is not None and client.raw_uprate > 0
    )
    clients_with_download_rate = sum(
        1 for client in eligible if client.raw_downrate is not None and client.raw_downrate > 0
    )
    clients_with_rate = sum(
        1
        for client in eligible
        if (client.raw_uprate is not None and client.raw_uprate > 0)
        or (client.raw_downrate is not None and client.raw_downrate > 0)
    )
    return TendaMW6TransferReadiness(
        eligible_clients=len(eligible),
        clients_with_rate=clients_with_rate,
        clients_with_upload_rate=clients_with_upload_rate,
        clients_with_download_rate=clients_with_download_rate,
        inventory_all_reported_offline=inventory.all_reported_offline,
    )


def estimate_transfer_bytes(rate_kib_s: int | None, elapsed_seconds: float) -> float:
    """Estimate transferred bytes from one valid instantaneous MW6 rate sample.

    The firmware reports a truncated KiB/s rate, not a cumulative byte counter.
    This helper intentionally returns no transfer for invalid/negative samples;
    callers must additionally gate it on fresh HostList inventory.
    """
    if rate_kib_s is None or rate_kib_s < 0 or elapsed_seconds <= 0:
        return 0.0
    return rate_kib_s * 1024.0 * elapsed_seconds


def build_login_payload(login_account: str) -> bytes:
    """Build the firmware LoginMsg protobuf from its 32-character account value.

    Live official-app captures use:
      field 1 (account): 32 ASCII hex characters
      field 2 (qrmsg): empty string

    Wire form is therefore: 0a 20 <32 bytes> 12 00.
    """
    account = login_account.strip()
    if not LOGIN_ACCOUNT_RE.fullmatch(account):
        raise ValueError("login account must contain exactly 32 hexadecimal characters")
    return b"\x0a\x20" + account.encode("ascii") + b"\x12\x00"


def extract_login_account(login_payload: bytes) -> str:
    """Extract the 32-character account from a captured LoginMsg payload."""
    if len(login_payload) != 36 or login_payload[:2] != b"\x0a\x20" or login_payload[34:] != b"\x12\x00":
        raise ValueError("unsupported MW6 LoginMsg payload shape")
    account = login_payload[2:34].decode("ascii", "strict")
    if not LOGIN_ACCOUNT_RE.fullmatch(account):
        raise ValueError("invalid MW6 login account")
    return account


class TendaMW6Api:
    """Small read-only client for the locally exposed TCP/9000 protocol."""

    def __init__(
        self,
        host: str,
        login_account: str,
        port: int = 9000,
        timeout: float = 4.0,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._login_payload = build_login_payload(login_account)

    def validate(self) -> None:
        """Authenticate and verify that MESH_HOSTS can be read."""
        self.get_clients()

    def get_clients(self) -> list[TendaMW6Client]:
        with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
            sock.settimeout(self.timeout)
            tid = 0xA0

            sock.sendall(_build_request(tid, AUTH_MODULE, AUTH_GET_STA))
            _expect_response(_recv_frame(sock), AUTH_MODULE, AUTH_GET_STA)

            tid = (tid + 1) & 0xFF
            sock.sendall(_build_request(tid, AUTH_MODULE, AUTH_LOGIN, self._login_payload))
            login = _expect_response(_recv_frame(sock), AUTH_MODULE, AUTH_LOGIN)
            if _status(login["payload"]) != 0:
                raise TendaMW6AuthError("Router rejected login account")

            tid = (tid + 1) & 0xFF
            sock.sendall(_build_request(tid, MESH_HOSTS_MODULE, MESH_HOSTS_GET))
            hosts = _expect_response(_recv_frame(sock), MESH_HOSTS_MODULE, MESH_HOSTS_GET)
            status, records = _decode_mesh_hosts(hosts["payload"])
            if status != 0:
                raise TendaMW6Error(f"MESH_HOSTS returned status={status}")
            return records


def _build_request(tid: int, module: int, command: int, payload: bytes = b"") -> bytes:
    return (
        MAGIC
        + bytes([REQ_KIND, tid & 0xFF])
        + FIXED
        + len(payload).to_bytes(2, "big")
        + bytes([module, command, 0, 0])
        + b"\x01\x00\x00\x00"
        + payload
    )


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise TendaMW6Error("Router closed the connection")
        data.extend(chunk)
    return bytes(data)


def _recv_frame(sock: socket.socket) -> dict[str, Any]:
    header = _recv_exact(sock, 16)
    if header[:2] != MAGIC:
        raise TendaMW6Error("Unexpected TCP/9000 frame magic")
    payload_len = int.from_bytes(header[6:8], "big")
    payload = _recv_exact(sock, payload_len)
    return {
        "kind": header[2],
        "tid": header[3],
        "module": header[8],
        "command": header[9],
        "payload": payload,
    }


def _expect_response(frame: dict[str, Any], module: int, command: int) -> dict[str, Any]:
    if frame["kind"] != RESP_KIND:
        raise TendaMW6Error(f"Unexpected response kind 0x{frame['kind']:02x}")
    if frame["module"] != module or frame["command"] != command:
        raise TendaMW6Error(
            f"Unexpected response module/cmd 0x{frame['module']:02x}/0x{frame['command']:02x}"
        )
    return frame


def _status(payload: bytes) -> int:
    if len(payload) < 4:
        raise TendaMW6Error("Response payload too short")
    return int.from_bytes(payload[:4], "little", signed=True)


def _read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while pos < len(buf) and shift < 70:
        byte = buf[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return value, pos
        shift += 7
    raise TendaMW6Error("Invalid protobuf varint")


def _protobuf_fields(buf: bytes) -> list[tuple[int, int, int | bytes]]:
    pos = 0
    fields: list[tuple[int, int, int | bytes]] = []
    while pos < len(buf):
        key, pos = _read_varint(buf, pos)
        field_no = key >> 3
        wire_type = key & 7
        if wire_type == 0:
            value, pos = _read_varint(buf, pos)
        elif wire_type == 2:
            length, pos = _read_varint(buf, pos)
            if pos + length > len(buf):
                raise TendaMW6Error("Truncated protobuf field")
            value = buf[pos : pos + length]
            pos += length
        elif wire_type == 1:
            if pos + 8 > len(buf):
                raise TendaMW6Error("Truncated fixed64 field")
            value = buf[pos : pos + 8]
            pos += 8
        elif wire_type == 5:
            if pos + 4 > len(buf):
                raise TendaMW6Error("Truncated fixed32 field")
            value = buf[pos : pos + 4]
            pos += 4
        else:
            raise TendaMW6Error(f"Unsupported protobuf wire type {wire_type}")
        fields.append((field_no, wire_type, value))
    return fields


def _signed64(value: int) -> int:
    return value - (1 << 64) if value >= (1 << 63) else value


def _as_text(value: bytes) -> str:
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        return value.hex()


def _decode_mesh_hosts(payload: bytes) -> tuple[int, list[TendaMW6Client]]:
    status = _status(payload)
    clients: list[TendaMW6Client] = []

    for field_no, wire_type, value in _protobuf_fields(payload[4:]):
        if field_no != 1 or wire_type != 2 or not isinstance(value, bytes):
            continue

        raw: dict[int, int | str] = {}
        for inner_no, inner_wire, inner_value in _protobuf_fields(value):
            if inner_wire == 2 and isinstance(inner_value, bytes):
                raw[inner_no] = _as_text(inner_value)
            elif inner_wire == 0 and isinstance(inner_value, int):
                raw[inner_no] = _signed64(inner_value) if inner_no == 9 else inner_value

        clients.append(
            TendaMW6Client(
                ip=str(raw.get(1, "")),
                mac=str(raw.get(2, "")),
                access=raw.get(3) if isinstance(raw.get(3), str) else None,
                node_sn=str(raw.get(4, "")),
                condition_time=raw.get(5) if isinstance(raw.get(5), int) else None,
                raw_online=raw.get(6) if isinstance(raw.get(6), int) else None,
                raw_uprate=raw.get(7) if isinstance(raw.get(7), int) else None,
                raw_downrate=raw.get(8) if isinstance(raw.get(8), int) else None,
                signal=raw.get(9) if isinstance(raw.get(9), int) else None,
                name=str(raw.get(10, "")),
            )
        )

    return status, clients
