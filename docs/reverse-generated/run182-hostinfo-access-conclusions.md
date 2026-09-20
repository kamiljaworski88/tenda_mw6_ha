# Run 182 — HostInfo access conclusions

## Scope

Static firmware evidence from Runs 180–181 was applied to the Home Assistant
decoder. No router commands were sent.

## Result

`HostInfo.access` uses protobuf wire type 2 and is formatted by `confsrv`
with `%s`; it is a text label, not an integer. The device-list connection
paths preserve labels including `wired`, `gst_2g`, `gst_5g`, and
`unknow`.

Integration version 0.6.0 now:

- preserves this raw text value in `TendaMW6Client.access`;
- exposes a per-client diagnostic **Connection type** sensor;
- does not invent a mapping for unseen firmware labels;
- tests decoding of the representative `wired` protobuf field.

This is independent from the unresolved inventory freshness fault and does not
make the per-client transfer counters authoritative.
