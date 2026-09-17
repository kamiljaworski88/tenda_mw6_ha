# Run 39 — resolved HostInfo memory layout and rate directions

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

Observed code:

```text
HostInfo* host = hosts[i];
if (*(uint32_t *)((uint8_t *)host + 0x20) == 0)
    continue;
```

With the resolved layout this is:

```c
if (!host->online)
    continue;
```

It is not a `condtion_time` gate.

## IP/MAC lookup inputs

For each online client, firmware:

1. parses `host->ipaddr` from `HostInfo+0x0c`,
2. clears a 6-byte local MAC buffer,
3. parses `host->ethaddr` from `HostInfo+0x10`,
4. calls the static `online_ip` matcher with:

```text
a0 = parsed IPv4
a1 = parsed 6-byte MAC
a2 = g_ip_info
a3 = record count
```

A NULL matcher result skips the rate calculation for that host.

The exact internal matcher policy (strict IP+MAC versus fallback matching) remains the main unresolved static detail.

## Direction mapping resolved

The rate helper computes two independent 64-bit counter deltas from the matched `online_ip` record.

### Record group at +0x28 / +0x30

Current counter begins at record `+0x28`, previous/sample counter begins at `+0x30`. The normalized result is stored to stack `+64`, then written to:

```text
HostInfo + 0x28
```

`HostInfo + 0x28` is `downrate`.

Therefore the `online_ip` counter group based at `+0x28` is the DOWNLOAD direction.

### Record group at +0x18 / +0x20

Current counter begins at record `+0x18`, previous/sample counter begins at `+0x20`. The normalized result is stored to stack `+72`, then written to:

```text
HostInfo + 0x24
```

`HostInfo + 0x24` is `uprate`.

Therefore the `online_ip` counter group based at `+0x18` is the UPLOAD direction.

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
       find matching g_ip_info / online_ip record
       upload delta  : record +0x18 versus +0x20
       download delta: record +0x28 versus +0x30
       normalize by elapsed time
       HostInfo.uprate   = result at +0x24
       HostInfo.downrate = result at +0x28
  -> protobuf pack
```

## Remaining unknowns

Only two material pieces remain for current-rate support:

1. exact matching rule inside the static `online_ip` matcher (IP AND MAC, or fallback semantics),
2. exact exposed unit/scaling of `uprate` and `downrate` after the normalization helper.

Neither affects the now-resolved field/direction mapping.
