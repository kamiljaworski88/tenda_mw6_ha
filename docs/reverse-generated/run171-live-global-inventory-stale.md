# Run 171 — live proof: central inventory is globally stale

The read-only `--diagnose-inventory` test observed the complete HostLists for
65 seconds with five-second polling.

Selected client:

- IP: `192.168.5.47`
- MAC: `90:61:AE:6F:AD:D3`
- node serial: `E85920101213014563`
- present in all 14 snapshots
- online in 0 of 14 snapshots

Inventory-wide result:

- selected node: `0/9` online in every snapshot;
- complete HostLists: `0/30` online in every snapshot;
- all eight same-node peers remained offline.

The node/peer classifier returned `NODE_REPORTING_STALE`. The global 0/30
observation is stronger than that label: the failure is not isolated to the
selected client or one satellite. No reporting node refreshed the gateway's
central inventory during the observation window.

## Consequence

Runs 163–170 already establish that the nominal producer path should:

1. dispatch timer ID 4 every 20 seconds;
2. call `do_upload_client_list(g_client_hs_list, g_client_hs_list_num)`;
3. serialize all client records rather than permanently skipping previously
   uploaded entries;
4. publish an envelope containing `device_list_upload` to
   `confctl_srv_key` through `cmd_pub`.

Because every central record is stale, the next useful boundary is the local
pub/sub channel on the gateway, not another per-client HostList or rate test.

## Next read-only diagnostic

`mw6_cmd_client.py monitor-device-list` passively subscribes to
`confctl_srv_key` through the already recovered TCP/12598 cmdsrv transport.
It observes for 65 seconds, crossing three nominal 20-second publication
cycles. It prints only timestamps, payload sizes, counts, and classification;
payload bytes are neither printed nor saved.

This separates:

- active local device-list publication with downstream consumption/merge
  failure;
- an active channel carrying other commands but no device-list publication;
- a completely silent local publication channel;
- an unconfirmed subscription.
