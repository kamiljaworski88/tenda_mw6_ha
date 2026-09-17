# Run 39 — resolved HostInfo memory layout, host matcher and rate directions

## Major correction

Earlier notes treated the `HostInfo + 0x20` gate in `fill_host_lists_rate()` as a likely `condtion_time` check. That interpretation is superseded by the exact 32-bit protobuf-c object layout below.

`HostInfo + 0x20` is the `online` scalar. `condtion_time` is at `+0x1c`.

This matches all independently observed accesses in `confsrv`:

- `+0x0c` is passed to the IPv4 parser -> `ipaddr`
- `+0x10` is passed to the MAC parser -> `ethaddr`
- `+0x20` is tested before rate lookup -> `online`
- `+0x24` is written by the second rate calculation -> `uprate`
- `+0x28` is written by the first rate calculation -> `downrate`

## 32-bit protobuf-c HostInfo object

`ProtobufCMessage` occupies 12 bytes on this 32-bit firmware. Fields follow in descriptor/declaration order.

| Offset | HostInfo field | Protobuf field |
|---:|---|---:|
| 0x00..0x0b | `ProtobufCMessage base` | — |
| 0x0c | `ipaddr` pointer | 1 |
| 0x10 | `ethaddr` pointer | 2 |
| 0x14 | `access` pointer | 3 |
| 0x18 | `assoc_sn` pointer | 4 |
| 0x1c | `condtion_time` | 5 |
| 0x20 | `online` | 6 |
| 0x24 | `uprate` | 7 |
| 0x28 | `downrate` | 8 |
| 0x2c | `signal` | 9 |
| 0x30 | `name` pointer | 10 |

## Rate gate

Observed code is equivalent to:

```c
if (!host->online)
    continue;
```

It is not a `condtion_time` gate.

## Exact g_ip_info / online_ip matcher

For each online client firmware parses:

- `host->ipaddr` from `HostInfo+0x0c` into a 32-bit IPv4 value,
- `host->ethaddr` from `HostInfo+0x10` into a 6-byte MAC buffer.

The static helper at `0x4340cc` receives:

```text
a0 = parsed IPv4
a1 = parsed 6-byte MAC
a2 = g_ip_info base
a3 = record count
```

The record stride calculation in the helper is exactly `0xE8` (232 bytes). For every record it first compares the six MAC bytes at `record+0x04`; only when that comparison succeeds does it compare the IPv4 value at `record+0x00`.

Equivalent logic:

```c
for (i = 0; i < count; i++) {
    rec = (uint8_t *)g_ip_info + i * 0xE8;
    if (memcmp(input_mac, rec + 0x04, 6) != 0)
        continue;
    if (*(uint32_t *)(rec + 0x00) != input_ip)
        continue;
    return rec;
}
return NULL;
```

Therefore matching is strict **MAC AND IP**. There is no IP-only or MAC-only fallback in this helper. A stale/inconsistent IP/MAC pair in `g_ip_info` causes an online HostInfo to skip rate calculation and retain zero rates.

## Direction mapping resolved

The rate helper computes two independent 64-bit counter deltas from the matched `online_ip` record.

### Record group at +0x28 / +0x30

Current counter begins at record `+0x28`, previous/sample counter begins at `+0x30`. The normalized result is written to `HostInfo + 0x28`, which is `downrate`.

Therefore the counter group based at `+0x28` is DOWNLOAD.

### Record group at +0x18 / +0x20

Current counter begins at record `+0x18`, previous/sample counter begins at `+0x20`. The normalized result is written to `HostInfo + 0x24`, which is `uprate`.

Therefore the counter group based at `+0x18` is UPLOAD.

## Arithmetic helpers resolved

The rate path uses the expected soft-float helpers:

- `__floatundisf` to convert a 64-bit unsigned delta to float,
- `__divsf3` for normalization/division,
- `__fixunssfdi` to convert the normalized float back to an unsigned integer.

The elapsed-time path also uses `__divsf3` and falls back to a positive constant when the computed interval is not positive. The final upload/download calculation performs an additional division by the same firmware constant at the data slot corresponding to `base+0x3360`.

The exact numeric value of that final scale constant is the only remaining item needed before assigning a display unit such as B/s, kB/s or KiB/s with full confidence.

## Resolved pipeline

```text
GetHostList
  -> fill HostInfo list
  -> snapshot network statistics
  -> ~500 ms delay
  -> second snapshot
  -> for each HostInfo:
       online != 0 ?
       parse IP
       parse MAC
       strict match: MAC == rec+0x04 AND IP == rec+0x00
       upload delta  : record +0x18 versus +0x20
       download delta: record +0x28 versus +0x30
       normalize by elapsed time and firmware scale constant
       HostInfo.uprate   = result at +0x24
       HostInfo.downrate = result at +0x28
  -> protobuf pack
```

## Remaining unknown

For current-rate support only one material item remains: the exact exposed unit/scaling of `uprate` and `downrate` after the final `__divsf3` normalization.
