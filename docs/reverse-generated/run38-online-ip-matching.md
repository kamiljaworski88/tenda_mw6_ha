# Run 38 — HostInfo → online_ip matching path

This note records the concrete caller-side matching path used by the GetHostList rate helper.

## Preconditions

For each runtime HostInfo entry, firmware first loads the value at HostInfo +0x20 (32). If it is zero, the client is skipped before rate lookup.

The protobuf-c layout is consistent with this slot being the `condtion_time` scalar value:

- +0x0c: `ipaddr` pointer
- +0x10: `ethaddr` pointer
- +0x20: `condtion_time` value

## Matching inputs prepared by fill_host_lists_rate

Before calling the internal matcher, firmware prepares both IP and MAC:

1. `HostInfo + 0x0c` is passed to the IP string conversion routine; the resulting IPv4 value is stored in a local variable.
2. A 6-byte local MAC buffer is zeroed.
3. `HostInfo + 0x10` is passed with that 6-byte buffer to the MAC parser (`ifaddrs_ethaddr_aton`-style helper).
4. If MAC parsing fails (non-zero return), the lookup path is skipped for that client.
5. The internal online-ip matcher is then called with four arguments:
   - a0 = parsed IPv4 value
   - a1 = pointer to parsed 6-byte MAC
   - a2 = `g_ip_info` base/list
   - a3 = online-ip record count / list length

Therefore the caller supplies **both IP and MAC** to `find_client_in_online_ip_info`.

## What is confirmed vs still unresolved

Confirmed:

- `condtion_time == 0` prevents rate processing.
- malformed/unparseable MAC also prevents the online-ip lookup.
- the matcher receives both IPv4 and MAC plus the `g_ip_info` list.

Still to resolve from the static matcher body:

- whether it requires `(IP && MAC)` equality,
- whether it tries IP first then MAC fallback,
- whether it accepts MAC-only/IP-only matches,
- whether it additionally filters on interface/type/status fields.

## Practical consequence

If `GetHostList` returns `condtion_time != 0` but `uprate/downrate == 0` under active traffic, the next diagnostic suspects are now narrowly defined:

1. IP conversion/value mismatch,
2. MAC parse mismatch,
3. exact match predicate inside `find_client_in_online_ip_info`,
4. absence/staleness of the corresponding record in `g_ip_info`.

This is a stronger target than revisiting TCP/9000 or `cmdrpc@` routing.
