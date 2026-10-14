# Wi-Fi IPv6 +1 and Ethernet route preference — 2026-10-13

## Later native nmtui integration

The [native nmtui Wi-Fi follow-up](nmtui-wifi-tailscale-20261013.md) supersedes the
Wi-Fi owner and activation details here. Ethernet+1 IPv4/IPv6, metric preference
and the existing application network/DNS security boundary are retained. This
report's artifact hashes and checks describe its earlier source snapshot.

## Contract

- When both managed adapters are configured, Wi-Fi IPv4 and IPv6 are exactly
  Ethernet +1 within the same subnet and with the same prefix length.
- Ethernet uses metric 100 and Wi-Fi metric 200 for both default routes and
  connected prefix routes, in both address families.
- Routes on a managed adapter without carrier are ignored by the host FIB.
- Both physical uplinks use the existing protected application veth path.
- Wi-Fi remains down at boot; only an explicit user action activates it.

For example, Ethernet `192.168.50.56/24` produces Wi-Fi `192.168.50.57/24`, and
Ethernet `2001:db8::56/64` produces Wi-Fi `2001:db8::57/64`. IPv6 increments are
numeric across all 128 bits: `2001:db8::ffff/64` produces `2001:db8::1:0/64`.

## Findings and implementation

The installer already passes `link_address_offset()` (Ethernet 0, Wi-Fi 1) to
both address allocators. Its IPv6 allocator uses bounded byte arithmetic and
rejects overflow, gateway collisions and subnet escape. That allocation was
preserved. The earlier logs already showed host Ethernet `::88` and Wi-Fi `::89`.

The installed reader previously enforced the IPv4 relationship, but not the
IPv6 relationship or complete IPv6 stanza values. `ManagedNetwork/Validator.pm`
now validates both configured IPv6 CIDRs, numeric adjacency, matching prefixes
and subnet membership, using 16-byte arithmetic without floating-point address
conversion. It also checks exactly one IPv6 stanza per adapter and its address,
prefix, gateway, metric and per-link DNS where applicable.

`network-wifi-configure` now checks the same IPv6 relationship before requesting
credentials, publishing authentication or executing adapter commands. Its
existing IPv4 checks and private configuration ownership remain unchanged.

The default-route metrics already existed. Forky's ifupdown 0.8.45+nmu1 applies
that option to default gateway routes, leaving connected prefix routes without
the same preference. The two interface templates now set the address's prefix
route metric with a fixed `ip -4/-6 address change <managed-CIDR> dev <managed-iface>
metric <100|200>` post-up hook. The generator supplies both new values explicitly.
The hooks modify only the generated managed address; they do not flush routes,
change policy-routing rules or start another network manager.

Both templates also set per-interface `ignore_routes_with_linkdown=1` before
activation. This permits Wi-Fi routing when Ethernet loses carrier despite a
retained lower-metric Ethernet route, and allows Ethernet preference to resume
on carrier return. These settings apply only to the managed adapters; no
host-wide sysctl default was changed. Wi-Fi's boot activation remains absent,
and IPv6 DAD remains enabled.

Primary sources reviewed as data:

- [Forky ifupdown package source](https://sources.debian.org/src/ifupdown/0.8.45%2Bnmu1/inet.defn)
  and its [IPv6 method](https://sources.debian.org/src/ifupdown/0.8.45%2Bnmu1/inet6.defn).
- [ip-address metric documentation](https://manpages.debian.org/testing/iproute2/ip-address.8.en.html)
  defines the priority of the prefix route associated with an address.
- [Kernel link-down route documentation](https://docs.kernel.org/networking/ip-sysctl.html)
  and [IPv6 sysctl implementation](https://github.com/torvalds/linux/blob/master/net/ipv6/addrconf.c).

## Veth routing and security path

The app-veth broker uses the kernel's selected IPv4 route, including existing
VPN policy. It does not hard-code physical interface names or create a separate
Wi-Fi path. It now rejects `NO-CARRIER`, route `linkdown`, and known down
operational states, while retaining valid VPN interfaces with `UNKNOWN` state.
Malformed route flags/operational-state data fail with controlled errors.

Existing route-change handling retains each application's namespace, slot,
private address and veth pair. For pinned leases, it quiesces the host endpoint,
atomically changes the selected interface and SNAT/peer-DNAT maps, removes only
that application's stale conntrack entries, and restores the endpoint. Unpinned
leases continue through host routing and masquerade. DNS retains the same
private veth resolver path for either physical uplink.

Application namespaces continue to use their existing protected IPv4 packet
path. IPv6 host addressing does not enable a second namespace egress path:
existing namespace IPv6 disabling and nftables rejection of non-IPv4 veth traffic
remain unchanged. Application reservations, VPN policy, firewall grants,
capabilities, private Xwayland and the ten-second power flow were preserved.

## Installation route

- `network-assets.list` already stages both interface fragments.
- `network-generate.pl` supplies the added CIDR/metric placeholders and renders
  `interfaces.d/50-network`, host policy and NetworkManager unmanaged matches.
- The installed Perl reader runs before network boot enablement and at boot.
- Desktop staging installs `network-wifi-configure` at 0755 through the existing
  authorized action; existing ifupdown execution policy handles native hooks.
- `configure_target_app_veth` stages the broker at 0755 and its existing service
  executes that path. No new daemon or service was introduced.

## Guarded regression changes

Updated the two existing guarded modules for IPv6 address/prefix/gateway/metric/
DNS drift, carry across byte/hextet boundaries, reversed adapter ordering,
non-byte-aligned subnet escape, `.56`/`.57` allocation, connected-route metrics,
per-interface link-down policy, pre-prompt rejection by the Wi-Fi helper,
carrier-state validation, VPN route preservation, and Ethernet/Wi-Fi/Ethernet
lease transitions with unchanged namespace/slot identities.

No fixture was executed. `AGENTS.override.md` requires a prepared disposable
environment without access to host state; none was available. Four changed
Python files were AST-parsed as source data without importing repository code.
No Perl/shell parser, policy validator, systemd manager, network command or live
host action was executed. Independent read-only review was attempted but failed
initialization with an encrypted-content hydration error; no child review is
claimed.

Generation-only command:

```sh
/usr/bin/env -i PATH=/usr/bin:/bin LC_ALL=C.UTF-8 /usr/bin/make build PYTHON='/usr/bin/python3 -I' SHELL=/bin/sh
```

It exited 0 and reported `built 1757 payload files`. Before/after checkout
metadata showed mutations only to the three build-owned installer artifacts.
All 1,757 regular archive members (33,968,475 source bytes) match their
canonical source bytes and manifest hashes. Archive paths, normalized metadata,
private-input exclusions and all three preseed/bootstrap checksum pins were
checked as data without extraction or execution.

The IPv4 template has 14 placeholders and IPv6 has eight; each set exactly
matches its explicit generator map. Four changed Python sources were parsed
with the standard-library AST parser, without imports/execution.
`git diff --check` exited 0. No active `CPUAccounting=` directive remains.
Four private Xwayland paths and three veth policy/identity paths were compared
with HEAD and remain byte-identical.

| Generated product | SHA-256 |
| --- | --- |
| `payload.manifest` | `a428c541008944d11a5b54f43247c444c8d48392b7d7656d9674a41366d6a100` |
| `payload.tar.gz` | `74bbed2d167a8c80ffd7ce34f7a5b1e2cbd81395533a326d582ce8454caff213` |
| `preseed.cfg` | `19f7f50205d2b39d6245fc2b5153fbd73b8d70149e262e3691c96c01c0e2980f` |

This supersedes the artifact snapshot in the preceding Wi-Fi-down report.
Runtime fixtures and native integration remain unexecuted.

## Changed paths in this follow-up

- `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/network/ManagedNetwork/Validator.pm`
- `d-i/forky/hooks/target/usr/local/libexec/network-wifi-configure`
- `d-i/forky/hooks/target/usr/local/sbin/app-veth`
- `d-i/forky/scripts/late/network-generate.pl`
- `d-i/forky/scripts/late/templates/network/inet4.tmpl`
- `d-i/forky/scripts/late/templates/network/inet6.tmpl`
- `d-i/forky/tests/test_boot_runtime_20260913.py`
- `d-i/forky/tests/test_kernel_veth_networking.py`
- This report and regenerated `d-i/forky/{payload.tar.gz,payload.manifest,preseed.cfg}`.

This establishes source/payload consistency, not a fresh-install or live
dual-uplink failover result. No installed host was reconfigured. Link/carrier
failover is implemented; it does not introduce active Internet-health probing.
