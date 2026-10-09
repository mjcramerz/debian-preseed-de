# Installed startup repair — 2026-10-09

**Latest capture:** the [LPL-746 namespace-read follow-up](lpl746-namespace-read.md)
covers the subsequently supplied `apparmor.log`, `fail`, `journalctl` and complete
installer-state folder: **45 files, 8,936 physical lines**. Its source policies,
regression results and generated payload are recorded separately below that
link. The LPL-948 results, transcript and hashes in this directory retain their
historical values.

## Earlier LPL-948 capture

This earlier record covers the LPL-948 capture and the final requested interface
names. It supersedes the current-state conclusions of the
[2026-10-08 record](../installed-startup-20261008/README.md), which retains the
earlier 91-file capture and its original validation evidence.

## Evidence read

Every line of the five files supplied at that point was read. The inventory contains file
hashes and line counts; no capture was rewritten. Earlier `todo/managed/`
evidence was reviewed in the preceding record and was absent from that
supplied tree.

| File | Lines | Observed result and disposition |
| --- | ---: | --- |
| `todo/fail` | 7 | Podman helper version warning repaired. Fail2ban reports successful startup. Public Xwayland absence is consistent with private Zoom/Discord use. One atomic eDP-1 EBUSY event remains hardware acceptance. |
| `todo/journalctl` | 1,161 | Broker, Podman API, NFS, Tailscale, Waybar and Crystal Dock start. The Vivaldi launch fails in the common namespace supervisor; fixed through shared confinement. IPv6 NTP retries are followed by successful IPv4 synchronization. Journal-to-syslog forwarding missed 66 messages; the supplied journal retains the diagnostic sequence. |
| `todo/vivaldi` | 71 | Opening the Bubblewrap init's PID namespace is denied; SIGTERM cleanup is also denied, leaving the constructor alive while temporary bind sources disappear. This is a shared launcher path, not a Vivaldi-only setting. |
| `todo/apparmor` | 4 | The broker's inherited ip/nft process cannot read immutable iproute2 group, route-table and realm lookup files. Read permission is added for the package directory. |
| `todo/apparmor1` | 3 | Exact capability-19 and reciprocal TERM denials identify the common client capability rule and labwc-app/app-bwrap signal pair. |

Total: **1,246 lines**. The original uncommitted source changes were inspected
and retained; preservation is recorded separately from the explicitly requested
identifier changes and startup repairs.

The user additionally supplied two duplicate LPL-550 exec denials for
`/usr/bin/tar` in `labwc-wrap-desktop-files`. These direct-message records are
separate from the five-file inventory. They identify the package metadata
fallback described below and are covered by the final policy update.

## Integrated repairs

### Boot pool and fixed names

The privileged `app-veth.service` creates **32 separate pairs at boot**, before
binding its control socket or sending `READY=1`. Its start ordering precedes
the greeter and Podman API service. No app request creates a host adapter.

Host names are **`veth0-app` through `veth31-app`** and never change during a
lease. Idle peers are `veth0-peer` through `veth31-peer`. Only the namespace
peer receives the private guest name `eth0` after being moved into the caller's
namespace, then returns to its idle peer name during reclamation. There is no
per-application host rename or app-name abbreviation table. Current and future
authorized managed policies use the same fixed-slot mechanism; application
identity is retained in structured lifecycle events.

All endpoints start DOWN. Gateway addresses and host route-localnet/reverse-path
settings are configured at boot. Namespace ownership, credentials, FD type,
host-namespace rejection and the finite lease limit remain enforced. Lease
firewall updates commit before interfaces come up and before payload gates open.
Cleanup lowers the host and guest endpoints, flushes guest addresses, returns
the peer, and removes exact lease elements. Failure retains the default-deny
guards for recovery.

Native testing found that this iproute2 veth creation path ignores an inline
alias. The boot batch now sets the ownership tag explicitly after creation,
before assigning addresses. Recovery accepts tagged service endpoints, or an
interrupted creation only when both exact reserved idle names are mutually
paired, untagged, DOWN, veth devices and address-free. Foreign tags, active
untagged links, missing peers, configured addresses and unrelated devices are
preserved.

The NetworkManager exclusion lists **all 64 names literally**. The primary
[NetworkManager configuration reference](https://networkmanager.dev/docs/api/latest/NetworkManager.conf.html)
specifies that interface globbing supports only `*` and `?`, so bracket ranges
are not used. The host firewall and broker guard use the same exact host-name
set; other Netavark interfaces retain their existing policy.

### Shared AppArmor and Podman

The common client abstraction permits `sys_ptrace` mediation for inspecting
the caller-owned child namespace. Linux grants the namespace creator
capabilities in that descendant user namespace; this AppArmor permission adds
no capability in the initial host namespace. Existing explicit ptrace peer
rules still restrict inspection. This distinction is documented in
[user_namespaces(7)](https://man7.org/linux/man-pages/man7/user_namespaces.7.html).

The labwc-app parent can send TERM/KILL to app-bwrap, and the child can receive
those signals from that parent. Other existing supervisor/child signal pairs
remain present. The package's immutable `/usr/share/iproute2/` lookup directory
is read-only in the broker profile. Forky's resolved ip executable and the
exact root-owned Netavark namespace endpoint retain their prior corrections.

The Podman adapter's `--version` probe returns successfully without importing
the namespace client, opening a namespace or requesting administrative work.
The helper ABI, rootless Netavark bridge ownership, qBittorrent TCP/UDP forwarding,
Discord RPC, systemd-resolved DNS, and Codex/ChatGPT Podman Unix API bindings are
covered by the integration selection.

### Desktop package metadata fallback

For a new package without `md5sums`, `labwc-wrap-desktop-files` falls back from
the control archive to `dpkg-deb --contents`. That native command invokes
`/usr/bin/tar` while retaining the wrapper's profile. The executable was missing
from the inherited decompression/helper rule. The narrow change adds `tar` to
`/usr/bin/{gzip,tar,xz,zstd} rix`; it retains the same domain, capabilities and
filesystem limits. No unconfined transition is introduced.

The compiled rule reader confirms read/execute permission for the actual tar
path. Existing native fixtures build metadata-only packages with and without
`md5sums`, including an archive filename with spaces, and execute the real
inspection path in private state directories. These are package fixtures,
not software compilation, package installation or loaded-policy enforcement.

Active artifacts use `app-veth`: the service, helpers, AppArmor policy and client
abstraction, configuration, socket directory, systemd ordering, nft table,
installer functions, debug/logging references and corresponding tests. Source
runtime display behavior is preserved. One Zoom/Discord policy include follows
the renamed common network abstraction; private-display runtime code is unchanged.

## Validation

Exact command arguments and observed outcomes are recorded in `results.json`;
the integration transcript is in `contracts.log`.

| Check | Observed scope and result |
| --- | --- |
| 12-module integration selection | **593 tests: 541 passed, 52 skipped**, no failures/errors. |
| Later tar/AppArmor package selection | **32 tests passed, no skips**, covering the effective tar grant, inherited execution syntax and native metadata fallback. |
| Kernel networking selection | **61 tests**, including native creation of 32 fixed DOWN pairs, gateway addresses, stable names/indexes, tagged and interrupted-create recovery, a real blocked Bubblewrap init with pidfd inspection, and native nftables syntax/transactions. One packet fixture is skipped. |
| AppArmor | **46 files parse** in a disposable tree with kernel loading and cache writes disabled. Effective file rules cover iproute2 lookups, the resolved ip binary, and the Netavark endpoint. |
| Shells | **350 files, 711 parser checks pass**. |
| Preseeds | **59 files pass**, including private debconf command read-back. |
| Logging | **18 contracts pass**; native rsyslog 8.2608 configuration parser accepts the rendered private tree. Target account/group values are modeled for this parser; no collector starts. |
| Installer snapshot | Builder and `--check` pass; all **1,725 archive members** are read back against source bytes, manifest hashes and archive metadata; preseed pins are checked. |
| Preservation | Unrelated initial source hashes, requested identifier-only changes, deleted user sources and private-display sources are verified separately. |

The 52 skips are **44 root-owned filesystem fixtures**, **6 unavailable private
session-bus fixtures**, **1 missing historical audit capture**, and **1 isolated
packet fixture blocked by denied sysctl writes**. No denied operation was retried
through an alternate privilege path. A local UDP fixture models resolved in that
packet test; it would not establish actual resolved DNS or Internet behavior.

## Installed-target acceptance still required

The repository and generated installer snapshot are updated. These checks do
not establish a deployment or successful GUI launch under the installed host's
enforced policy. Local validation uses systemd 262; the requested installed
target is Forky/systemd 261.2. The changed unit properties predate that target,
but no live systemd 261.2 session was exercised here.

An existing installation with the earlier `managed-veth` artifacts needs the
matching service/helper/client/configuration/profile updates and retirement of
the old broker and renamed configuration files as one deployment. Updating only
Vivaldi, only the broker binary, or only a policy file leaves incompatible
dependencies. The source installer stages the matching set for a fresh target.

Acceptance on the installed target should establish:

1. The app-veth service is ready and all `vethN-app` adapters exist **before any
   managed app starts**; NetworkManager leaves the 64 pool endpoints unmanaged.
2. Native, privacy, qBittorrent, Codex, ChatGPT, Zoom/Discord and Podman paths start
   under enforced AppArmor without the supplied capability/file/TERM denials.
3. DNS uses the resolved extra listener and host VPN/search policy; ordinary
   outbound traffic, tracker TCP/UDP forwarding, Discord RPC and Podman bridges
   work with no namespace-to-namespace or host-service exposure.
4. Normal exit, failed launch, user stop and broker restart reclaim endpoints
   without renaming or recreating host adapters during app leases.
5. Real desktop document downloads, portals, NFS, USB/power flows and tray behavior
   retain their established behavior. Root-owned fixture skips require target
   checks for those privileged filesystem operations.

The single eDP-1 atomic EBUSY record at journal line 1045 occurs after the
compositor and desktop services start. This capture has no corresponding
output-helper mutation trace or compositor exit. Existing output transactions
log begin/end and retry with fresh state after rejection. The hardware cause is
unverified; there is no evidence-grounded driver/modesetting change to apply
from this capture. Public Xwayland remains absent by the private-only design;
Zoom and Discord retain their private compatibility path.

No software was compiled from source, kernel policy loaded, host network
changed, service restarted, desktop launched, or live deployment performed.
