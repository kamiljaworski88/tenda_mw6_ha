# MW6 internal IPC / rate-data reverse engineering

This note tracks the internal path behind TCP/12598, Redis, and per-client rate data in the public MW6 HW2.1 firmware dump.

## TCP/12598 is `cmdsrv`, not Redis RESP

The public firmware process listing contains the exact command line:

```text
redis-server /etc_ro/redis.conf
cmdsrv -l tcp://0.0.0.0:12598 -R tcp://127.0.0.1:6379
```

This explains the live-router observation that TCP/12598 accepts a connection but closes/returns nothing for a raw Redis `PING`: port 12598 is `cmdsrv`'s own protocol. `cmdsrv` uses Redis on localhost as its backend.

The Redis configuration confirms:

```text
port 6379
bind 127.0.0.1
unixsocket /tmp/redis.sock
unixsocketperm 755
```

Therefore Redis itself is intentionally local-only. We should not treat 12598 as a Redis socket.

## Internal command bus

`device_list` imports `cmd_init`, `cmd_pub`, `cmd_sub` and `redis_option_new`, and links both `libcmdctl.so` and `libredis.so`.

Direct binary inspection now confirms `cmdsrv` itself imports Redis reader/writer/client routines and the generic `cm_io_*` server primitives, including:

```text
redis_client_execute
redis_client_try_execute
redis_client_init
redisReaderFeed
redisReaderGetReply
subscribe_new
subscribe_register
subscribe_unregister
cm_io_listen
cm_io_accept
cm_io_read
cm_io_write
```

This is stronger than the process-list inference: `cmdsrv` really is a command-service frontend backed by Redis, not a transparent Redis TCP forwarder.

The firmware's `cmdctl_test` binary links `libcmdctl.so` and imports the complete high-level API:

```text
cmd_init
cmd_sub
cmd_pub
cmd_set
cmd_get
```

It also imports `redis_option_new`, which confirms the command-control library is implemented on top of the Redis transport. `cmdctl_test` is therefore the best offline reference for recovering the API's argument layout and message/channel naming.

Current model:

```text
device_list / other processes
        |
     libcmdctl
 cmd_pub/sub/get/set
        |
 Redis command transport
        |
 Redis 127.0.0.1:6379
        |
      cmdsrv
 cm_io_* + subscribe_*
        |
 TCP/12598 custom frontend
```

The exact 12598 framing and topic/channel names are not recovered yet. No speculative packets should be sent until the `cmdctl_test` call sites / `libcmdctl` convention are decoded.

## Stronger lead for traffic/rate source: kernel `bm_online_ip`

The firmware boot log reports:

```text
[BM CORE][init_online_ip] INFO: online ip data hash table created
[BM CORE][init_online_ip_procfs] INFO: online_ip proc file created
```

The kernel's built-in module list includes:

```text
kernel/net/netfilter/bm_common.ko
kernel/net/netfilter/bm_online_ip.ko
kernel/net/netfilter/bm_http.ko
kernel/net/netfilter/nos_track.ko
```

Separately, cloud-info logs:

```text
[fill_cloud_info_device_lists_rate][2600][luminais] NULL == g_ip_info
```

This creates a plausible data chain:

```text
network traffic
    |
netfilter / BM / NOS
    |
bm_online_ip + online-IP hash table
    |
per-IP runtime information (`g_ip_info` or derived structure)
    |
fill_cloud_info_device_lists_rate()
    |
cloud-info device-list payload
```

This is currently the strongest lead for where instantaneous per-client upload/download rates originate. It is more specific than `QOS_GET`, which live testing showed only returns global QoS configuration.

## Client identity / mesh-node sources

Firmware scripts also expose useful local kernel/proc data sources:

```text
/proc/wlan0/sta_info
/proc/wlan1/sta_info
/proc/wlan0/mesh_assoc_mpinfo
/proc/wlan1/mesh_assoc_mpinfo
/proc/wlan0/mesh_pathsel_routetable
/proc/wlan1/mesh_pathsel_routetable
/proc/mesh/status
/etc/dhcps.leases
/proc/net/nf_conntrack
```

`device_list`'s symbols (`wifi_get_vap_client_lists`, DHCP/netlink handlers, roaming/connection-type lists) fit this model: client identity and attachment state are assembled from Wi-Fi/DHCP/netlink data, while rate information can be supplied by the BM/NOS traffic-tracking path.

## Offline tooling

`tools/cmdctl_extract.py` was added to this repository. It accepts firmware binaries such as `cmdsrv`, `cmdcli`, `cmdctl_test` and `libcmdctl.so`, extracts printable strings with offsets and highlights command/Redis/pub-sub/socket-related material. It never connects to the router.

## Current research priority

1. Recover the MIPS call sites for `cmd_pub`, `cmd_sub`, `cmd_get` and `cmd_set` from `cmdctl_test`.
2. Decode `libcmdctl.so` and map those calls to Redis commands/channel names.
3. Recover the topic/arguments used by `device_list -> cmd_pub()`.
4. Determine whether the published client structure already contains rate values or only identity/state.
5. Locate the exact procfs name created by `bm_online_ip` and the structure consumed by `fill_cloud_info_device_lists_rate()`.
6. Prefer a read-only local subscription/query for Home Assistant. Do not invoke cloud upload commands or router SET operations.
