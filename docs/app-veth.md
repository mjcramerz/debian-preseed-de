# Managed application networking

The Forky installer publishes `/etc/app-veth.json` from
`d-i/forky/hooks/target/etc/app-veth.json.tmpl`. This root-owned file selects
which managed application instances receive a kernel veth lease. Applications
use separate network and PID namespaces; the root broker configures routing
and nftables without executing application code.

## Configuration

The complete file has three top-level keys:

```json
{
  "version": 1,
  "desktop_user": "desktop",
  "apps": {
    "bitwarden": {"network": true, "block_lan": true},
    "qbittorrent": {
      "network": true,
      "block_lan": false,
      "pin_route": true,
      "peer_port": 50309
    },
    "new-client": {
      "network": true,
      "block_lan": true,
      "executables": ["/opt/new-client/client"]
    },
    "keepassxc": {"network": false}
  }
}
```

Use the installed desktop username. The template includes the configured
qBittorrent port and the reviewed network clients, including Bitwarden,
ChatGPT, Codex, browsers, Code, Postman, Spotify, messaging and remote-access
clients. KeePassXC, Sleek, MPV and RetroArch have no network entry by default.

| Application key | Meaning |
| --- | --- |
| `network` | Required Boolean. Only `true` authorizes a lease. An omitted managed app, or an entry with `false`, launches in its private namespace without a veth. |
| `block_lan` | Optional Boolean, default `false`. Blocks private IPv4, carrier-grade NAT, link-local, loopback, benchmark, multicast and reserved ranges, plus directly connected LAN subnets. DNS continues through systemd-resolved. |
| `peer_port` | Optional integer in `1024..65535`. Reserves and forwards this TCP and UDP port on the selected Internet source address to the instance. Omission creates no inbound peer forwarding. |
| `pin_route` | Optional Boolean. Defaults to `true` when `peer_port` is present, otherwise `false`. Pins egress to the selected interface and source address. Peer forwarding requires this setting. |
| `executables` | Optional list of absolute installed program paths. Used to match a newly installed package through the generic desktop launchers. Paths must be below `/usr/bin`, `/usr/local/bin`, `/usr/lib` or `/opt`; the worker checks root ownership and parent permissions before execution. |

App identifiers use lowercase letters, digits, underscores and hyphens. Known
managed clients retain their existing application identifiers and dedicated
sandbox policies, so they do not need `executables` entries. PurePrivacy modes
retain their existing restrictions; disposable qBittorrent uses the separate
`qbittorrent-privacy` policy without persistent peer forwarding.

Keep the file root-owned, mode `0644`, with one hard link. Duplicate keys,
unknown settings, malformed types, unsafe paths and oversized files are rejected.
Validate a change as root with:

```sh
/usr/local/sbin/app-veth --check-config
```

This command validates configuration without creating links or changing routes
or firewall state. Both the launchers and broker read the policy for a new
launch/request; an app restart applies changed settings to its next instance.
Existing leases keep their creation policy until the instance exits.

## Adding a package

Add its identifier and actual executable paths to `apps`. The existing desktop
entry wrapping mechanism routes package desktop entries through
`labwc-wayland-app` or `labwc-electron-app`. On its next managed launch, the
executable match selects the private network worker automatically.

A terminal invocation can use the same launch path:

```sh
labwc-wayland-app launch -- /opt/new-client/client
```

For an Electron program, use `labwc-electron-app` with the same syntax. These
launchers require the active Labwc user session. Executing an arbitrary vendor
binary directly does not invoke the managed launchers. Existing terminal,
file-manager and host administration entrypoints retain their host lifecycle
contracts and remain available for repairing the configuration.

New generic clients retain the generic launcher's filesystem and IPC access.
The network worker provides private network/PID namespaces, capability removal,
private procfs, a private temporary directory and a hidden broker socket.
Explicit desktop `env NAME=value` assignments and session restore metadata
survive worker dispatch. Values use a private read-only payload file rather
than command-line arguments; unrelated user-manager environment is not copied.
Application-specific filesystem and AppArmor policy belongs to the package or
its dedicated managed launcher. The existing private Xwayland launchers remain
restricted to Zoom and Discord.

## Routing and lifecycle

`app-veth.service` pre-creates 32 guarded, DOWN pairs before publishing readiness.
An authorized instance receives a unique available slot. Offline apps receive
no lease. The guest link is raised before adding its default route; its host
peer stays DOWN until the nftables transaction commits. Bubblewrap's payload
gate stays closed until setup and readiness checks succeed.

The namespace client resolver uses `10.0.2.3`, translated only to
systemd-resolved's extra host listener on `127.0.0.1:53053`. Resolved keeps its
upstream, VPN and search-domain policy. Managed packet transport remains IPv4;
the broker guards against IPv6 escaping through these links.

The broker rejects host namespaces, foreign namespace ownership, unconfigured
app labels and duplicate namespace leases. It verifies source addresses,
blocks traffic between application namespaces and limits incoming traffic to
its explicit forwarding maps. Discord's existing fixed local RPC mappings
remain supported. LAN restrictions are installed before outbound and established
forwarding accepts; kernel route/address notifications refresh connected LAN
subnets, including LANs using public addresses. Tunnel Internet routes are
excluded from the connected-LAN snapshot.

The supervisor pins the private namespace init with a pidfd and terminates it
on normal exit or failure, then releases the lease. This also covers offline
instances and detached descendants. Recycled peers are lowered and stripped of
their addresses before returning to the pool. Failed cleanup keeps the guards
installed and requires service recovery before reuse.

The existing Podman helper remains a separate `podman` policy restricted to
the devops service account. Desktop callers cannot request that identity.

## Enrollment and bytecode

A successful CrowdSec console enrollment request records
`enrollment=pending-approval`, publishes its completion marker and exits zero.
Console approval remains a later remote step. Genuine authentication, API and
registration failures retain retry/failure behavior. CrowdSec and Tailscale
completion can trigger secondboot cleanup; firstboot success also triggers it
to cover validation finishing last. Cleanup uses the component markers and
retains unfinished enrollment artifacts.

Installed Python entrypoints use `-B`, including `-IB` for isolated shebangs.
Interpreter-driven helpers and startup gates also pass `-B`. Codex sets
`sys.dont_write_bytecode` before importing managed modules. This prevents cache
writes in managed code directories while allowing Python to read existing
distribution bytecode. No writable cache directory or AppArmor write permission
is added to installed code paths.
