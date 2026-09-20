# Run 175 — live `confctl_srv_key` silence and current fault boundary

## Live observation

The passive TCP/12598 monitor subscribed to `confctl_srv_key` for 65 seconds.
The subscription acknowledgement was received, but the channel delivered no
messages:

- `subscription_ack: yes`
- `pubsub_messages: 0`
- `device_list_upload_messages: 0`
- `other_messages: 0`
- `undecodable_frames: 0`
- classification: `NO_CONFCTL_PUBLICATIONS`

The observation window covers more than three nominal 20-second
`device_list_upload` periods. Because subscription setup succeeded, absence of
messages is evidence of producer-side silence at the local gateway boundary,
not a failed client connection.

## Combined evidence

The preceding live inventory run observed all 30 central `HostInfo` records
offline in every sample. Independent WAN rates remained non-zero during the
selected-client rate run. The zero per-client rates are therefore caused first
by the stale `HostInfo.online` inventory gate.

Runs 163–170 show that a healthy `device_list` process should serialize and
publish the full client list every 20 seconds. Run 172 shows that `monitor`
supervises both `timer` and `device_list`, and that timer registrations are
sent over local IPC to `/var/tm_socket`. `device_list` explicitly contains
timer-exit and timer-restart handling.

Run 173 finds only three ELF users of `timer_start`: `libcommon.so`,
`device_list`, and `netctrl`. Only `device_list` also imports `cmd_pub`, so the
firmware does not provide a second simple periodic Redis publication that can
act as an independent timer sentinel.

Run 174 confirms that `mesh_status_check` can publish `NewNodeReport` on the
same `confctl_srv_key`, but only on mesh registration/state events. It is not a
fixed-cadence heartbeat, so its absence during an otherwise stable 65-second
window does not prove that `cmd_pub` is globally broken.

## Current fault boundary

The remaining leading branches are:

1. the shared `timer` process or `/var/tm_socket` is unavailable;
2. `device_list` did not successfully register or re-register timer IDs 3/4;
3. timer event ID 4 is not delivered to the `device_list` dispatcher;
4. `do_upload_client_list` or its `cmd_pub` call fails before Redis publication.

The established TCP/9000 and TCP/12598 read-only interfaces do not expose
process state, Unix-socket state, or timer registrations. Separating these
four branches now requires read-only shell visibility on the gateway (for
example process, Unix-socket, and log inspection) or another independently
confirmed diagnostic interface. No state-changing command should be sent to
the production mesh merely to force a timer or publication event.
