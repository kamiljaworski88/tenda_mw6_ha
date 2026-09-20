#!/usr/bin/env python3
"""Read-only probe for an already exposed MW6 diagnostic shell surface.

The probe only opens TCP connections to SSH (22) and Telnet (23), waits for a
server banner, and closes the sockets. It does not authenticate, negotiate a
session, send commands, or change router state.
"""
from __future__ import annotations

import argparse
import socket
from dataclasses import dataclass


@dataclass(frozen=True)
class ProbeResult:
    port: int
    open: bool
    banner_bytes: int = 0
    protocol: str = "none"
    error: str = ""


def classify_banner(port: int, data: bytes) -> str:
    if data.startswith(b"SSH-"):
        return "ssh"
    if port == 23 and data:
        if data[0] == 0xFF:
            return "telnet-negotiation"
        return "telnet-or-plain-shell"
    if data:
        return "unknown-banner"
    return "open-no-banner"


def probe(host: str, port: int, connect_timeout: float, banner_timeout: float) -> ProbeResult:
    try:
        with socket.create_connection((host, port), connect_timeout) as sock:
            sock.settimeout(banner_timeout)
            try:
                data = sock.recv(256)
            except socket.timeout:
                data = b""
            return ProbeResult(
                port=port,
                open=True,
                banner_bytes=len(data),
                protocol=classify_banner(port, data),
            )
    except (ConnectionRefusedError, TimeoutError, OSError) as exc:
        return ProbeResult(
            port=port,
            open=False,
            error=exc.__class__.__name__,
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Passively check whether SSH/Telnet is already exposed by an MW6"
    )
    parser.add_argument("--host", default="192.168.0.1")
    parser.add_argument("--connect-timeout", type=float, default=2.0)
    parser.add_argument("--banner-timeout", type=float, default=1.0)
    args = parser.parse_args()

    if args.connect_timeout <= 0 or args.banner_timeout <= 0:
        parser.error("timeouts must be greater than zero")

    print(
        f"Read-only shell-surface probe for {args.host}. "
        "No credentials or commands will be sent."
    )
    print("PORT  OPEN  PROTOCOL                 BANNER_B  RESULT")

    results = [
        probe(args.host, port, args.connect_timeout, args.banner_timeout)
        for port in (22, 23)
    ]
    for item in results:
        print(
            f"{item.port:>4}  {'yes' if item.open else 'no ':>4}  "
            f"{item.protocol:<23}  {item.banner_bytes:>8}  "
            f"{item.error or 'connected'}"
        )

    ssh = next(item for item in results if item.port == 22)
    telnet = next(item for item in results if item.port == 23)
    print("\n=== SHELL SURFACE SUMMARY ===")
    if ssh.open and ssh.protocol == "ssh":
        print("classification: SSH_BANNER_DETECTED")
        print(
            "meaning: an existing SSH listener can support the next read-only "
            "process/socket diagnostic if valid credentials are already available."
        )
    elif telnet.open:
        print("classification: TELNET_LISTENER_DETECTED")
        print(
            "meaning: an existing Telnet-like listener may support the next read-only "
            "diagnostic; do not enable or alter it merely for this investigation."
        )
    elif ssh.open:
        print("classification: PORT_22_OPEN_PROTOCOL_UNCONFIRMED")
        print(
            "meaning: TCP/22 accepted the connection but did not identify itself as "
            "SSH during the passive banner window."
        )
    else:
        print("classification: NO_EXISTING_SHELL_LISTENER")
        print(
            "meaning: neither SSH nor Telnet was already reachable. The known remote "
            "read-only interfaces cannot expose timer/device_list process state."
        )


if __name__ == "__main__":
    main()
