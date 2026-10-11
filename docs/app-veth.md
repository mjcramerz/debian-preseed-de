# Managed application networking

The Forky installer publishes `/etc/app-veth.json` from
`d-i/forky/hooks/target/etc/app-veth.json.tmpl`. This root-owned file selects
which managed application instances receive a kernel veth lease. Applications
use separate network and PID namespaces; the root broker configures routing
and nftables without executing application code.

## Configuration

The installer emits version 2 with four top-level keys. Identity values come
from `d-i/forky/hosts/installer/identity.env`, using the shared validated
`app-veth-identity.sh` map for all target files:

```json
{
  "version": 2,
  "desktop_user": "desktop",
  "network": {
    "ipv4_cidr": "10.203.0.0/23",
    "max_leases": 128,
    "host_interface_prefix": "veth",
    "host_interface_suffix": "-app",
    "peer_interface_suffix": "-peer",
    "namespace_interface": "eth0",
    "dns_address": "10.0.2.3",
    "dns_host_address": "127.0.0.1",
    "dns_host_port": 53053
  },
  "apps": {
    "bitwarden": {"network": true, "block_lan": true, "slots": [0, 1, 2, 3], "addresses": ["10.203.0.2", "10.203.0.6", "10.203.0.10", "10.203.0.14"]},
    "qbittorrent": {
      "network": true,
      "block_lan": false,
      "pin_route": true,
      "peer_port": 50309,
      "slots": [56],
      "addresses": ["10.203.0.226"]
    },
    "new-client": {
      "network": true,
      "block_lan": true,
      "executables": ["/opt/new-client/client"],
      "slots": [29],
      "addresses": ["10.203.0.118"]
    },
    "keepassxc": {"network": false, "slots": [31], "addresses": ["10.203.0.126"]}
  }
}
```

Use the installed desktop username. The template includes the configured
qBittorrent port and the reviewed network clients, including Bitwarden,
ChatGPT, Codex, browsers, Code, Postman, Spotify, messaging and remote-access
clients. KeePassXC, Sleek, MPV and RetroArch have no network entry by default.

| Application key | Meaning |
| --- | --- |
| `slots` | Required in version 2. Ordered list of unique reserved integers below `max_leases`; no slot may belong to two apps. Ordinary applications reserve four slots; applications with `peer_port` or `pin_route` reserve one slot. The broker uses the first free slot in this app's list, and reports exhaustion instead of borrowing another app's address. |
| `addresses` | Required canonical IPv4 addresses in slot order. The installer derives them from the subnet and reservations; the parser rejects missing or inconsistent addresses. |
| `network` | Required Boolean. Only `true` authorizes a lease. An omitted managed app, or an entry with `false`, launches in its private namespace without a veth. |
| `block_lan` | Optional Boolean, default `false`. Blocks private IPv4, carrier-grade NAT, link-local, loopback, benchmark, multicast and reserved ranges, plus directly connected LAN subnets. DNS continues through the dedicated dnsmasq/Stubby path. |
| `peer_port` | Optional integer in `1024..65535`. Reserves and forwards this TCP and UDP port on the selected Internet source address to the instance. Omission creates no inbound peer forwarding. |
| `pin_route` | Optional Boolean. Defaults to `true` when `peer_port` is present, otherwise `false`. Pins egress to the selected interface and source address. Peer forwarding requires this setting. |
| `executables` | Optional list of absolute installed program paths. Used to match a newly installed package through the generic desktop launchers. Paths must be below `/usr/bin`, `/usr/local/bin`, `/usr/lib` or `/opt`; the worker checks root ownership and parent permissions before execution. |

App identifiers use lowercase letters, digits, underscores and hyphens. Known
managed clients retain their existing application identifiers and dedicated
sandbox policies, so they do not need `executables` entries. PurePrivacy modes
retain their existing restrictions; disposable qBittorrent uses the separate
`qbittorrent-privacy` policy without persistent peer forwarding.

The IPv4 pool must be an aligned RFC1918 subnet with enough /30s for every
slot. Slot `n` owns the /30 starting at `network_address + 4*n`: the host is
`+1`, and the app is `+2`. The default qBittorrent identity is slot 56,
`veth56-app` on the host, gateway `10.203.0.225`, and `10.203.0.226` on its
private `eth0`. Ordinary desktop apps have four fixed slots for concurrent
namespaces. Applications with a pinned route or peer forwarding keep one slot
because their source route or forwarded host port is singleton state. Different
apps never compete for an address. After release the primary slot becomes
available again. Persistent qBittorrent uses its existing singleton IPC path
and one reserved slot.

`APP_VETH_*` defines the subnet, capacity, interface prefix/suffixes, private
interface and DNS endpoints. The installer assigns stable four-slot or
single-slot reservations in canonical application order. A nonempty
`APP_VETH_OVERRIDE` in a host profile selects only the named applications;
empty override values use the identity defaults. The installer renders the
same identity into NetworkManager exclusions, AppArmor sysctl grants, broker
JSON, DNS services and qBittorrent binding. Changing the subnet or interface/DNS
topology on an installed host requires updating these rendered assets and
restarting the broker; it refuses topology changes during a running lease.
Only the complete version-2 policy is accepted. Network identity and reserved
application slots are rendered during the fresh installation. Each app receives
a rendered `addresses` list containing one app-side address for each reserved
`/30` slot; the list is not itself a CIDR range. The parser requires those
exact canonical IPv4 addresses to match the subnet and slots, and the client
checks the broker response against that list.

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

Add its identifier, unused reserved slots, and actual executable paths to
`apps`. Slot 29 is unassigned in the default installer identity. The existing desktop
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

`app-veth.service` pre-creates the configured 64 guarded, DOWN pairs before publishing readiness.
An authorized instance receives an available slot from its application's
reserved list. The configured subnet is checked against host routes; overlap
fails instead of selecting a different range. Offline apps receive
no lease. The guest link is raised before adding its default route; its host
peer stays DOWN until the nftables transaction commits. Bubblewrap's payload
gate stays closed until setup and readiness checks succeed.
Before creating the pool, the broker waits up to five seconds for the local
dnsmasq listener, tolerating refused connections during daemon startup. This
checks local readiness without waiting for a public DNS answer. A denied
connection fails immediately, and an unavailable listener prevents setup.
The foreground dnsmasq service uses `Type=exec` so systemd also tracks process
setup and executable failures before starting dependent services.

The namespace client resolver uses the existing private `10.0.2.3` endpoint,
translated only to dnsmasq on `127.0.0.1:53053`. This frontend has a bounded
10,000-entry cache and forwards cache misses directly to Stubby on
`127.0.0.1:53054`. Systemd-resolved is outside this application DNS path.
Stubby uses authenticated TLS-only upstreams and DNSSEC
validation. The installer renders the upstream IPv4 addresses, IPv6 addresses,
TLS names and port from `hosts/installer/identity.env` (`SYSTEM_NAMESERVERS_*`),
so site policy does not need to be duplicated in a preseed fragment. DNS1 uses
`SYSTEM_NAMESERVERS_IPV4_DNS1`, `SYSTEM_NAMESERVERS_IPV6_DNS1` and
`SYSTEM_NAMESERVERS_HOSTNAME_DNS1`; the corresponding `DNS2` and `DNS3` variables select
optional fallbacks. In public CA mode each enabled resolver requires a TLS hostname and at
least one address. An empty address disables only that resolver's transport
family; DNS A and AAAA queries remain supported. Leave all three values of each
optional resolver empty for a single resolver. `SYSTEM_NAMESERVERS_PORT` applies to all resolvers.
Both address families are enabled by default. With `round_robin_upstreams: 0`,
Stubby uses the ordered DNS1 endpoints (IPv4, then IPv6), then DNS2, then DNS3
when an upstream is unavailable; it does not distribute queries round-robin.
Stubby reads the distribution's root DNSKEYs from `/usr/share/dns/root.key`.
The trust-anchor setting uses getdns's scalar zone-file form; a filename inside
a YAML list is not a resource record and would leave the anchor list empty.
`SYSTEM_DNS_CACHE_SIZE="10000"` and `SYSTEM_DNS_CACHE_MIN_TTL="60"` in
`hosts/installer/identity.env` configure the local cache. Dnsmasq retains entries
for at least one minute, deliberately extending shorter upstream TTLs; longer
upstream TTLs remain unchanged. This can retain an earlier answer during a
short-TTL upstream change. The supported minimum range is 0–3600 seconds and
the cache-size range is 1–1,000,000 entries, validated before rendering.
Dnsmasq caches positive and negative answers, including
additional record types such as TXT, SRV and HTTPS through `cache-rr=ANY`.
It does not proxy the DNSSEC AD bit while caching; DNSSEC validation belongs
to Stubby. An expired or uncached answer cannot fall back to a host, DHCP or
VPN DNS server. TLS authentication failure remains a resolution failure.
Stubby withholds invalid DNSSEC answers for requests with checking enabled.
An explicit DNS Checking Disabled (CD) request retains the protocol's diagnostic
behavior; dnsmasq does not insert its unchecked answer into the shared cache.
Single-label and reverse queries also use this fixed upstream policy; private
VPN zones are available through the host resolver, not through the managed app
resolver. Application LAN restrictions remain enforced by the broker's packet policy.

### Public and custom DNS certificate trust

`SYSTEM_DNS_UPSTREAM_TLS_CA_CUSTOM_ENABLE="false"` is the default. Stubby uses
Debian's `/etc/ssl/certs/ca-certificates.crt` bundle. During installation, the
target-side configurator performs a TLS handshake to a configured numeric
address for each enabled DNS resolver, using its `SYSTEM_NAMESERVERS_HOSTNAME_DNSn`
as SNI and as the expected authenticated identity. It checks the public CA
chain, validity period and certificate DNS Subject Alternative Name (SAN);
Common Name alone is insufficient. It renders that verified expected hostname
as `tls_auth_name`. A certificate supplied by the remote endpoint cannot select
a different trusted hostname, and no certificate is trusted on first use.

The checks try IPv4 before IPv6 with bounded socket timeouts. One verified
address family per configured resolver is sufficient for an IPv4-only or
IPv6-only installer. Every configured endpoint remains in the ordered runtime
list, and Stubby authenticates its certificate again when connecting. If no
address of a resolver can complete a handshake, or its certificate fails
authentication, installation stops before publishing the new Stubby config.
The installer therefore needs connectivity to the configured TLS port and a
correct system clock. This checks TLS authentication, not a live DNS answer.

To use a private DNS CA, set in `hosts/installer/identity.env`:

```sh
SYSTEM_DNS_UPSTREAM_TLS_CA_CUSTOM_ENABLE="true"
SYSTEM_NAMESERVERS_TLS_SAN_CUSTOM="dns.lan.icramer.com"
```

Set the intended private resolver IPs in DNS1/DNS2/DNS3, and clear unused
resolver address fields. Custom mode uses this SAN hostname for every enabled
resolver; the public `SYSTEM_NAMESERVERS_HOSTNAME_DNSn` fields are ignored.
All custom resolvers must present certificates valid for that same name and CA.
In the private installer-root `/preseed.env`, add:

```sh
PRESEED_DNS_UPSTREAM_TLS_CA_NAME_CUSTOM="public_cert.crt"
```

Include `/public_cert.crt` at the root of the installer initrd alongside
`/preseed.env`. The name must be a basename including its extension, using ASCII
letters, digits, `_`, `-` and `.`; paths and command-line overrides are not used.
The installer checks root ownership, safe permissions, regular-file type and
single-link ownership before copying. The trust input can be a PEM CA bundle
or one DER CA certificate, at most 256 KiB. Private keys, leaf certificates,
duplicate CAs and expired/not-yet-valid CAs are rejected.

The normalized public CA material is installed as root-owned mode 0644 at
`/etc/stubby/ca/upstream-custom.pem`, beneath root-owned directories without
group/other write permission. That fixed path is rendered into `tls_ca_file`.
It is readable by Stubby's DynamicUser and explicitly allowed by its AppArmor
profile. Custom mode does not query public certificates or add the private CA
to the operating system's general CA bundle. Runtime TLS authentication and
DNSSEC remain required. The host's global resolver also reaches these upstreams
through its existing local Stubby connection; VPN-specific DNS policy remains
under the existing network manager.

The installed `upstream_recursive_servers` is a readable block list with one
entry per enabled IP, each containing `address_data`, `tls_port` and
`tls_auth_name`. `round_robin_upstreams: 0` preserves ordered failover. Build-time
validation checks the same endpoint ordering and trust paths without contacting
the public resolvers. CA filenames and certificate contents are initrd inputs;
neither belongs in the served installer repository.

Systemd-resolved remains available for the host and VPN-specific consumers,
including per-link DNS and route-only domains. A VPN setting `~.` therefore
changes host DNS without replacing the managed application upstreams.
Application data retains the existing host routing behavior, including VPN
routes. Stubby's encrypted connections also follow host routes and VPN firewall
policy; this resolver separation does not install physical-uplink routing or
override a VPN kill switch. Cached answers do not depend on VPN DNS scope, so
VPN DNS changes do not require cache invalidation.

After changing installed Stubby upstream or validation policy, validate its
configuration and restart `stubby.service`. `PartOf=stubby.service` restarts
the dnsmasq frontend too, replacing its cache before new queries are served.
SIGHUP to dnsmasq also clears its cache; it does not reload Stubby configuration.
The installer always selects the DNS client firewall overlay, including for
strict egress profiles. Its TCP TLS port is rendered from the same identity
policy as Stubby, and its destination allowlists are derived from the same
configured upstream addresses. No provider address or TLS name is copied into
the implementation or firewall template. This overlay adds no UDP TLS rule.
Applications never receive host resolver addresses. Managed packet transport
remains IPv4; the broker guards against IPv6 escaping through these links.
Direct TCP/UDP port 53 forwarding is blocked before both unpinned and pinned
application egress, so ordinary DNS cannot bypass the private resolver endpoint.
Application protocols carrying their own encrypted DNS, such as DoH over HTTPS,
retain the application's normal data routing and are not detected by this rule.

`STATIC_INSTALLER_NAMESERVER` is separate bootstrap DNS for Debian
Installer. It renders `netcfg/get_nameservers` for static and DHCP profiles in production,
lab and DMZ. The managed target interfaces use the global resolver instead of
publishing this bootstrap address as per-link DNS after boot. VPN-managed link
DNS and route-only domains remain under systemd-resolved policy.

In this global mode, `dns-nameservers` is intentionally absent from the managed
ifupdown stanzas. NetworkManager's ifupdown plugin may log
`No dns-nameserver configured in /etc/network/interfaces` at info level while
importing those unmanaged interfaces. Check `resolvectl status` for the global
`127.0.0.1:53054` server and `/etc/resolv.conf` for the `127.0.0.53` stub; adding
installer or LAN DNS servers to these stanzas would change the routing policy.
The generated interfaces file documents this handoff. The installed reader
accepts `MANAGED_NETWORK_DNS_MODE=global` or `link` and rejects per-link DNS in
global mode. The installer must render the DNS mode explicitly.

During installation, the generated policy is checked with
`network-run validate --staged-only` before enabling `network.service`.
This checks configuration and address/MAC syntax before target udev renames
apply. The boot unit still validates present adapters against the configured
MAC and interface type, while allowing a detached USB adapter. This validation
does not declare Internet access available or replace an online readiness gate.

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
Pinned leases tolerate a ten-second loss of the selected route while a carrier
or USB Ethernet adapter is recreated. The packet mapping remains fail-closed
while the route is absent; a different route revokes the lease immediately, and
a prolonged outage emits `network_route_changed` and releases it. This keeps a
recoverable link flap from killing a long-running qBittorrent process while
preserving route pinning.
The DNS frontend and Stubby use systemd's direct automatic restart mode, so a
temporary daemon failure does not stop every dependent veth lease. Explicit
service stops/restarts and exhausted restart limits retain dependency teardown.

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
