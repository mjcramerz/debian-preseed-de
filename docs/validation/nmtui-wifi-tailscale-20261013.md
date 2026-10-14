# Native nmtui Wi-Fi and Tailscale bootstrap — 2026-10-13

## Final requested contract

The latest user corrections supersede the earlier ifupdown-only Wi-Fi design.
Wi-Fi must be selectable through native `nmtui`. A bounded firstboot scan is
authorized, but association remains manual. IPv4 and IPv6 remain Ethernet +1;
the Wi-Fi CIDR input constrains the IPv4 range and never supplies the host
address. Gateway and DNS follow Ethernet's existing policy.

All ten files in `d-i/forky/hosts/profiles/` now contain these empty overrides:

```sh
WIFI_INTERFACE=""
WIFI_ESSID=""
WIFI_SECURITY=""
WIFI_CIDR=""
WIFI_PASSPHRASE=""
```

A nonempty profile value wins. An empty value reads the corresponding
`PRESEED_WIFI_INTERFACE`, `PRESEED_WIFI_ESSID`, `PRESEED_WIFI_SECURITY`,
`PRESEED_WIFI_CIDR`, or `PRESEED_WIFI_PASSPHRASE` from the protected d-i root
`/preseed.env` through the existing canonical reader. No private input file was
read during this implementation. No example passphrase was copied into source.
Profile files are published installer inputs; keep actual credentials in the
private file when overrides are unnecessary.

`auto` selects the detected physical Wi-Fi adapter; a concrete installer
interface selects its MAC before the existing target rename to `wifi0` (or the
configured managed name). Invalid private input fails rather than being treated
as a missing SSID. Explicitly empty private security means open. Missing security
also selects open. Supported security is open, WEP raw keys, legacy WEP
passphrases, `wpa` for WPA2 Personal, and `sae` for WPA3 Personal.

Neither `PRESEED_WIFI_GATEWAY` nor `PRESEED_WIFI_NAMESERVERS` is consumed.
For Ethernet `192.168.50.88/24`, a constraint of `192.168.50.1/24` admits Wi-Fi
`192.168.50.89/24`; the `.1` is not used as Wi-Fi's address. An incompatible range,
overflow, subnet escape, duplicate address, or gateway collision fails. IPv6
increment uses full-width byte arithmetic and retains the Ethernet prefix.

## Ownership and lifecycle

The explicit unmanaged list now contains Ethernet only. Wi-Fi has a managed
NetworkManager device section and no ifupdown stanza. The native static keyfile
is prepared privately at `/etc/network/managed-wifi.nmconnection`, mode 0600.
It contains manual IPv4/IPv6, metric 200, autoconnect disabled and the existing
random MAC privacy policy. Ethernet retains ifupdown and metric 100.

Before NetworkManager starts, the helper changes only its persisted Wi-Fi radio
preference to off. A separate firstboot unit performs one bounded scan, matches
`SSID-HEX` against the exact configured bytes, and publishes the private profile
into `/etc/NetworkManager/system-connections/` only when visible. Missing adapter,
missing SSID, or an absent SSID records a skip. The radio is returned to off after
the scan, including a scan failure. The marker prevents repeat scans after a
completed firstboot attempt; actual command failures have two bounded attempts.

Typing `nmtui` uses a small installed `/usr/local/bin/nmtui` wrapper. This explicit
user action prepares the saved profile if firstboot skipped it, enables the radio
and opens `/usr/bin/nmtui`. The packaged program is unchanged. The desktop Wi-Fi
actions use the same helper and terminal flow. Native nmtui owns SSID/security
editing and secret prompting. For another SSID, edit **Managed Wi-Fi** while
retaining Manual addressing and leaving automatic connection unchecked; creating
an unrelated new profile in native nmtui does not inherit this installer's policy.

Root-owned configuration reads reject symlinks, nonregular files, multiple links,
unsafe parents, unexpected modes and oversized input. Writes are private and
atomic. Scan output is limited to 256 KiB and 35 seconds; subprocesses receive
fixed argument arrays and a minimal environment. AppArmor grants are scoped to
the prepared/live keyfile, radio state, completion marker, lock, native commands
and interface metadata. Systemd stage/enable/verification calls are explicit.

## Existing veth, proxy and DNS path

Native Wi-Fi explicitly retains IPv4 forwarding for the existing app-veth path;
the existing nftables policy continues to control allowed traffic. Its metric
applies to connected prefix and default routes. The broker follows the kernel
FIB and VPN policy, accepts either physical uplink through the same lease/NAT
code, and rejects linkdown/no-carrier routes. Existing namespace 3proxy settings,
veth reservation identities, private address allocation and nftables guards are
unchanged. Managed application DNS remains veth DNS DNAT → dedicated dnsmasq →
Stubby's authenticated resolver. Host global DNS remains resolved → Stubby;
global mode does not add installer LAN DNS to the Wi-Fi keyfile. Link DNS mode
copies Ethernet's configured nameservers. Protected application namespaces remain
IPv4-only; the host has the configured IPv6 addresses on both physical links.

Primary behavior references: [NetworkManager ownership rules](https://www.networkmanager.dev/docs/api/latest/NetworkManager.conf.html),
[IPv4 routing and forwarding](https://www.networkmanager.dev/docs/api/latest/settings-ipv4.html),
[IPv6 route metrics](https://www.networkmanager.dev/docs/api/latest/settings-ipv6.html),
[native keyfiles](https://www.networkmanager.dev/docs/api/latest/nm-settings-keyfile.html),
and [upstream SSID-HEX field](https://github.com/NetworkManager/NetworkManager/blob/main/src/nmcli/devices.c).
The Debian source index identified NetworkManager 1.58.1-1 for Forky; installed
target binaries were not executed or queried.

## Current journal and Tailscale

Current `todo/journalctl`: 212,514 bytes, 1,617 physical LF records, SHA-256
`bb68928a2100b4c3378cca60b1e39403c06d380532374615d84ef7e542f8d900`.
The complete file was read as data; failure records and Tailscale transitions
were correlated without executing its contents.

- Lines 1113 and 1127 show registration with `machineAuthorized=false` and
  transition to `NeedsMachineAuth`.
- Line 1520 reports `HaveNodeKey=true`; lines 1525–1527 report successful UDP,
  IPv4 and IPv6 network checks from the installed system.
- Lines 1560–1563 show pending approval being converted into `1/FAILURE`.

Pending approval now removes the consumed installer auth key, retains node state
and the incomplete status, and exits 75. The bootstrap uses `Type=exec`,
`SuccessExitStatus=75`, and `RestartForceExitStatus=75` with its existing 15-minute
spacing and eight-start bound. `RuntimeMaxSec=15min` retains the process limit for
the exec service. Joined/pending state is checked before auth-key normalization,
so approval checks do not reuse the key. A completion marker is written only for
a joined Running state. General failures remain failures. Pending approval skips
the redundant network diagnostic dump.

The machine still needs tailnet administrator approval. A pre-approved auth key
can make future authorized registrations unattended; the repository cannot
change an auth key's server-side approval properties. See
[Tailscale device approval](https://tailscale.com/docs/features/access-control/device-management/device-approval).

Other current error records: the two initial Tailscale health messages describe
startup transitions; lines 1286–1287 concern the deliberately absent global
Xwayland executable, whose private Zoom/Discord policy is preserved; lines
1434–1435 report Waypaper's monitor enumeration fallback to All. The supplied
journal does not establish a wallpaper rendering failure. Those messages were
not silenced or represented as repaired runtime behavior.

## Validation and limits

- Static AST parsing of the runtime Python helper and three changed Python test
  files succeeded. No repository modules were imported or executed.
- Network input template and production map match all 31 fields. All nine native
  profile markers and both NetworkManager ownership markers have production maps.
- Static inventory confirms all five empty overrides in each of ten profiles.
- Source tracing confirms static address generation feeds host CIDR policy and
  the existing veth/firewall/DNS consumers; no private gateway/DNS reader exists.
- Guarded fixtures were updated for keyfiles, both DNS modes, security variants,
  IPv6 carries, IPv4 range rejection, profile precedence, SSID matching, scan
  failure cleanup and Tailscale deferred status. **They were not executed.**
- Independent review agents failed initialization because of runtime encrypted
  content hydration errors. The root agent performed integration review.
- No disposable environment was available. No native Perl/shell/NetworkManager,
  AppArmor, systemd, networking or GUI validation ran. No host configuration,
  service, manager, radio, route, firewall, package state or credential was changed.

The permitted serialization command completed with **1,755 payload files**:

```sh
/usr/bin/env -i PATH=/usr/bin:/bin LC_ALL=C.UTF-8 /usr/bin/make build PYTHON='/usr/bin/python3 -I' SHELL=/bin/sh
```

Before/after metadata comparison across 2,288 checkout paths found changes only
in the three permitted generated artifacts. The full archive was read as data
without extracting or executing it: all 1,755 regular members, totaling
**33,986,455 source bytes**, match current source bytes and manifest hashes.
Archive paths, normalized modes/ownership/timestamps, private-input exclusions
and all three preseed/bootstrap pins match. There are **zero active
`CPUAccounting=` assignments** in the payload. `git diff --check` passed.
HEAD comparison of private Xwayland, app-veth identity/firewall policy, dnsmasq,
Stubby and namespace 3proxy sources found no changes. No software was compiled.

| Artifact | SHA-256 |
| --- | --- |
| `payload.tar.gz` | `296d7405752b9b5f54488056b8e0f03361de7ab0644a276517bacaeb76b59053` |
| `payload.manifest` | `366153ee2d29572701e07c86656fd039c9c75c93683d3fde35ed13cc60a7279d` |
| `preseed.cfg` | `91d0494950157855cac2404ecf6c42fb9e7905c86276221ec22b0d2789392f8f` |

This establishes source/artifact consistency. Fresh installation, firstboot
radio behavior, native nmtui editing and activation, AppArmor transitions,
systemd deferred status, and live dual-link/veth/DNS failover remain unverified.

## Changed paths for this follow-up

- `hooks/target/etc/NetworkManager/conf.d/90-network-unmanaged.conf.tmpl`
- New `hooks/target/etc/NetworkManager/system-connections/managed-wifi.nmconnection.tmpl`
- New `hooks/target/etc/systemd/system/NetworkManager.service.d/30-wifi-manual.conf`
- New `hooks/target/etc/systemd/system/managed-wifi-firstboot.service`
- `hooks/target/etc/network/host.conf.tmpl`
- `hooks/target/etc/apparmor.d/{desktop-wrappers,system-wrappers}.tmpl`
- New `hooks/target/usr/local/bin/nmtui` and updated `hooks/target/usr/local/libexec/network-wifi-configure`
- `LabwcNetworkControlAction/{Client.pm.tmpl,Root.pm}` and `ManagedNetwork/Validator.pm`
- All ten `hosts/profiles/*.env`
- `scripts/common/credentials.sh`
- `scripts/desktop/components/{target-assets,services}.sh`, `scripts/desktop/verify.sh.tmpl`
- `scripts/late/{network.sh,network-generate.pl}` and network input/assets list
- Removed obsolete ifupdown Wi-Fi authentication fragments and the interim private
  supplicant template; native NetworkManager now owns authentication.
- `scripts/firstboot/assets/etc/systemd/system/tailscale-bootstrap.service.tmpl`
- `scripts/firstboot/assets/var/lib/firstboot/bin/tailscale-up`
- `tests/{test_boot_runtime_20260913,test_initrd_credentials,test_native_contracts_20260923}.py`
- `payload.tar.gz`, `payload.manifest`, `preseed.cfg` after generation

All source paths above are relative to `d-i/forky/`; this report is outside the
published payload. Earlier power, CPU-accounting and other incident fixes remain.
