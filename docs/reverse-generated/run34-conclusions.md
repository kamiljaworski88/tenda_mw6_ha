# Run 34 conclusions — HostList rate path

Run 34 closes the static mapping of the per-client rate calculation inside `confsrv`.

## Confirmed path

`GetHostList` calls helper `0x434258`. That helper calls `netlink_get_statistic_info()` twice and computes deltas between two snapshots before returning the packed host list.

The helper uses the online-IP/statistics record returned by the local firmware path, then matches it to each host record. No Tenda cloud request is required for this calculation.

## Counter pairs used

For one direction the helper compares the 64-bit pair at offsets `+0x28/+0x2c` against `+0x30/+0x34`.

For the other direction it compares the 64-bit pair at offsets `+0x18/+0x1c` against `+0x20/+0x24`.

The calculated values are then converted/divided by helper routines and stored in the host protobuf backing structure.

## HostInfo rate destinations

The final per-host values are written to:

- host working structure offset `+40`
- host working structure offset `+36`

The same rate path elsewhere in `confsrv` writes the corresponding runtime HostInfo values to:

- runtime host offset `+0x9c` (156), with presence flag bit `0x8`
- runtime host offset `+0x98` (152), with presence flag bit `0x4`

Firmware strings identify these fields as `uprate` and `downrate`; the exact direction-to-offset assignment still needs one live validation before naming them definitively in Home Assistant.

## Sampling

Between the first and second statistics reads the helper passes `0x7a120` (500000 decimal) to the timing/sleep path. This is consistent with an approximately 0.5 s internal sampling window. Therefore the external client should not need to issue two separate `GetHostList` requests just to create a rate sample.

## Why live f7/f8 can still be zero

The zero values seen in live tests are not explained by a missing second sample: the firmware already performs two internal samples. The remaining likely causes are now limited to the host-to-`g_ip_info` match/eligibility path, feature/state gating, or protobuf field mapping/serialization.

## Next implementation target

The next code step is a read-only `clients` operation that invokes the already recovered `GetHostList` RPC, decodes HostLists/HostInfo, and exposes both candidate rate fields without prematurely labelling their direction. One live transfer test can then confirm which one is upload vs download and the exact unit.
