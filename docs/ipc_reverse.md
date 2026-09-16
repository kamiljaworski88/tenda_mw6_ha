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

`device_list` imports:

```text
cmd_init
cmd_pub
cmd_sub
redis_option_new
```

and links both `libcmdctl.so` and `libredis.so`.

Combined with the `cmdsrv -R tcp://127.0.0.1:6379` command line, the current model is:

```text
processes (device_list, etc.)
        |
     libcmdctl
   cmd_pub/cmd_sub
        |
     Redis 6379
   127.0.0.1 only
        |
      cmdsrv
        |
   TCP/12598 custom protocol
```

The exact `cmdsrv` framing and topic/channel names are not recovered yet. No speculative packets should be sent until its client/test binary or `libcmdctl` call convention is decoded.

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

## Current research priority

1. Decode the `cmdsrv` / `libcmdctl` protocol using the firmware's `cmdcli` and `cmdctl_test` binaries offline.
2. Recover the topic/arguments used by `device_list -> cmd_pub()`.
3. Determine whether the published client structure already contains rate values or only identity/state.
4. Locate the exact procfs name created by `bm_online_ip` and the structure consumed by `fill_cloud_info_device_lists_rate()`.
5. Prefer a read-only local subscription/query for Home Assistant. Do not invoke cloud upload commands or router SET operations.
