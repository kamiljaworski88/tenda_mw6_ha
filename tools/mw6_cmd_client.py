#!/usr/bin/env python3
"""Read-only Tenda MW6 cmdsrv client.

Protocol recovered from MW6 libredis.so:
  u32le frame_len (= 8 + compressed_len)
  u32le XXH32(compressed, seed=0)
  u32le uncompressed_len
  LZ4 block(RESP bytes + magic f7 c6 89 be)

Only PING and SUBSCRIBE are exposed. No SET/PUBLISH support.
"""
from __future__ import annotations
import argparse, socket, struct, time
from pathlib import Path

MAGIC = bytes.fromhex("f7 c6 89 be")
MASK32 = 0xffffffff
P1,P2,P3,P4,P5 = 0x9E3779B1,0x85EBCA77,0xC2B2AE3D,0x27D4EB2F,0x165667B1

def rol(x,n): return ((x << n) | (x >> (32-n))) & MASK32
def xxh32(data: bytes, seed=0):
    n=len(data); p=0
    def rnd(a,b): return (rol((a + b*P2)&MASK32,13)*P1)&MASK32
    if n>=16:
        v1=(seed+P1+P2)&MASK32; v2=(seed+P2)&MASK32; v3=seed&MASK32; v4=(seed-P1)&MASK32
        while p<=n-16:
            v1=rnd(v1,int.from_bytes(data[p:p+4],'little')); v2=rnd(v2,int.from_bytes(data[p+4:p+8],'little'))
            v3=rnd(v3,int.from_bytes(data[p+8:p+12],'little')); v4=rnd(v4,int.from_bytes(data[p+12:p+16],'little')); p+=16
        h=(rol(v1,1)+rol(v2,7)+rol(v3,12)+rol(v4,18))&MASK32
    else: h=(seed+P5)&MASK32
    h=(h+n)&MASK32
    while p<=n-4:
        h=(h + int.from_bytes(data[p:p+4],'little')*P3)&MASK32; h=(rol(h,17)*P4)&MASK32; p+=4
    while p<n:
        h=(h + data[p]*P5)&MASK32; h=(rol(h,11)*P1)&MASK32; p+=1
    h ^= h>>15; h=(h*P2)&MASK32; h ^= h>>13; h=(h*P3)&MASK32; h ^= h>>16
    return h&MASK32

def lz4_literals(data: bytes) -> bytes:
    n=len(data); out=bytearray(); out.append(min(n,15)<<4)
    if n>=15:
        x=n-15
        while x>=255: out.append(255); x-=255
        out.append(x)
    out += data
    return bytes(out)

def lz4_decompress(src: bytes, expected: int) -> bytes:
    i=0; out=bytearray()
    while i<len(src):
        token=src[i]; i+=1; lit=token>>4
        if lit==15:
            while True:
                x=src[i]; i+=1; lit+=x
                if x!=255: break
        out += src[i:i+lit]; i+=lit
        if i>=len(src): break
        off=src[i] | (src[i+1]<<8); i+=2
        if not off or off>len(out): raise ValueError('invalid LZ4 offset')
        m=token&15
        if m==15:
            while True:
                x=src[i]; i+=1; m+=x
                if x!=255: break
        m += 4
        for _ in range(m): out.append(out[-off])
    if len(out)!=expected: raise ValueError(f'LZ4 size {len(out)} != {expected}')
    return bytes(out)

def resp(*args: str) -> bytes:
    b=[f'*{len(args)}\r\n'.encode()]
    for a in args:
        x=a.encode(); b += [f'${len(x)}\r\n'.encode(), x, b'\r\n']
    return b''.join(b)

def frame(payload: bytes) -> bytes:
    plain=payload+MAGIC; comp=lz4_literals(plain)
    return struct.pack('<III', len(comp)+8, xxh32(comp), len(plain))+comp

def recv_exact(s,n):
    b=bytearray()
    while len(b)<n:
        x=s.recv(n-len(b))
        if not x: raise EOFError('connection closed')
        b+=x
    return bytes(b)

def recv_frame(s):
    flen=struct.unpack('<I',recv_exact(s,4))[0]
    if flen<8 or flen>1024*1024: raise ValueError(f'invalid frame length {flen}')
    body=recv_exact(s,flen); checksum,usize=struct.unpack('<II',body[:8]); comp=body[8:]
    if xxh32(comp)!=checksum: raise ValueError('XXH32 mismatch')
    plain=lz4_decompress(comp,usize)
    if not plain.endswith(MAGIC): raise ValueError('MW6 magic mismatch')
    return plain[:-4]

def show(data: bytes, index: int, capture_dir: Path | None):
    print(f'\n--- message {index}: {len(data)} B ---')
    try:
        text=data.decode('utf-8')
        print(text.rstrip())
    except UnicodeDecodeError:
        print('BINARY HEX:', data.hex(' '))
    if capture_dir:
        capture_dir.mkdir(parents=True,exist_ok=True)
        p=capture_dir/f'mw6_message_{index:04d}.bin'; p.write_bytes(data)
        print('saved:',p)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--host',default='192.168.5.1'); ap.add_argument('--port',type=int,default=12598)
    sub=ap.add_subparsers(dest='cmd',required=True); sub.add_parser('ping')
    sp=sub.add_parser('subscribe'); sp.add_argument('channel'); sp.add_argument('--count',type=int,default=0,help='0 = listen until Ctrl+C'); sp.add_argument('--timeout',type=float,default=0,help='0 = no read timeout'); sp.add_argument('--capture-dir',default='mw6_capture')
    a=ap.parse_args(); command=('PING',) if a.cmd=='ping' else ('SUBSCRIBE',a.channel)
    with socket.create_connection((a.host,a.port),3) as s:
        s.settimeout(10 if a.cmd=='ping' else (a.timeout or None)); s.sendall(frame(resp(*command)))
        limit=1 if a.cmd=='ping' else a.count; i=0
        try:
            while limit==0 or i<limit:
                data=recv_frame(s); i+=1
                show(data,i,None if a.cmd=='ping' else Path(a.capture_dir))
        except KeyboardInterrupt:
            print(f'\nStopped. Received {i} message(s).')
        except TimeoutError:
            print(f'\nNo new message for {a.timeout:g}s. Received {i} message(s).')
if __name__=='__main__': main()
