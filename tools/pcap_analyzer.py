#!/usr/bin/env python3
"""Passive classic-PCAP analyzer for Tenda MW6 traffic.

By default proprietary MW6 frames are decoded only on TCP/9000. This avoids
false positives in opaque cloud/TLS payloads. LOGIN request payloads are never
printed.
"""
import argparse, ipaddress, struct
from collections import Counter

MAGIC = b'\x24\x00'
SERVICE = b'\x00\xd5'
HEADER_LEN = 16


def packets(path):
    with open(path, 'rb') as f:
        gh = f.read(24)
        magic = gh[:4]
        endian = '<' if magic == b'\xd4\xc3\xb2\xa1' else '>' if magic == b'\xa1\xb2\xc3\xd4' else None
        if not endian:
            raise ValueError('Classic PCAP required')
        link = struct.unpack(endian + 'I', gh[20:24])[0]
        if link != 101:
            raise ValueError(f'Expected DLT_RAW=101, got {link}')
        while True:
            ph = f.read(16)
            if len(ph) < 16:
                break
            sec, usec, n, _ = struct.unpack(endian + 'IIII', ph)
            pkt = f.read(n)
            if len(pkt) < 40 or pkt[0] >> 4 != 4 or pkt[9] != 6:
                continue
            ihl = (pkt[0] & 15) * 4
            if len(pkt) < ihl + 20:
                continue
            sp, dp = struct.unpack('!HH', pkt[ihl:ihl + 4])
            doff = (pkt[ihl + 12] >> 4) * 4
            pay = pkt[ihl + doff:]
            if pay:
                yield sec + usec / 1e6, str(ipaddress.ip_address(pkt[12:16])), sp, str(ipaddress.ip_address(pkt[16:20])), dp, pay


def valid_header(raw):
    if len(raw) < HEADER_LEN:
        return False
    if raw[:2] != MAGIC or raw[2] not in (6, 7) or raw[4:6] != SERVICE:
        return False
    n = int.from_bytes(raw[6:8], 'big')
    return len(raw) == HEADER_LEN + n


def frames(payload):
    """Extract complete, validated MW6 frames from one TCP payload."""
    pos = 0
    while True:
        i = payload.find(MAGIC, pos)
        if i < 0 or i + HEADER_LEN > len(payload):
            return
        n = int.from_bytes(payload[i + 6:i + 8], 'big')
        end = i + HEADER_LEN + n
        if end > len(payload):
            return
        raw = payload[i:end]
        pos = end
        if valid_header(raw):
            yield raw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pcap')
    ap.add_argument('--port', type=int, default=9000, help='MW6 local API TCP port (default: 9000)')
    ap.add_argument('--all-ports', action='store_true', help='research mode: inspect validated headers on every TCP port')
    a = ap.parse_args()

    flows = Counter()
    found = []
    for t, src, sp, dst, dp, pay in packets(a.pcap):
        flows[(src, sp, dst, dp)] += len(pay)
        if not a.all_ports and sp != a.port and dp != a.port:
            continue
        for raw in frames(pay):
            kind, tid, mod, cmd = raw[2], raw[3], raw[8], raw[9]
            n = int.from_bytes(raw[6:8], 'big')
            found.append((t, src, sp, dst, dp, kind, tid, mod, cmd, n))

    print('=== TCP flows with payload ===')
    for (src, sp, dst, dp), n in flows.most_common():
        print(f'{src}:{sp} -> {dst}:{dp}: {n} B')

    print('\n=== Valid MW6 frames ===')
    if not found:
        print('(none)')
    for t, src, sp, dst, dp, k, tid, m, c, n in found:
        direction = 'REQ' if k == 7 else 'RESP'
        secret = ' [LOGIN payload hidden]' if m == 0x18 and c == 1 and k == 7 else ''
        print(f'{t:.3f} {src}:{sp}->{dst}:{dp} {direction} tid=0x{tid:02x} module=0x{m:02x} cmd=0x{c:02x} payload={n} B{secret}')


if __name__ == '__main__':
    main()
