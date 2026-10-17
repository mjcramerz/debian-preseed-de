# October 17 supplied log review

## Scope and execution boundary

Base commit: `154d21c3037dc07ac3fc9074c1337407ff75641c`.
The initial checkout was clean. All 53 files under `todo/`, including the
hidden October 13 `.~` journal, were inventoried and inspected as data;
23 files are empty. Duplicate journal, application, security and kernel
records were correlated rather than treated as separate failures.

No tests, test imports, native syntax or policy parsers, installed helpers,
package operations, network changes or service operations were executed.
`AGENTS.override.md` and `docs/test-isolation.md` require a prepared disposable
environment, which has not been provided. The fixtures described below are
authored but unexecuted. Python AST parsing is source inspection only.

The installation target remains Forky with Python 3.14 and systemd 262.
The supplied journal identifies Tailscale 1.104.1 and the CrowdSec log identifies
1.8.2~rc1. These are log snapshot versions, not a live installed-package audit.
The referenced `debian-preseed-de-audit.md` is absent from this checkout.

## Bitwarden initialization

`todo/bitwarden:1-18` contains two sets of nine cross-device hard-link warnings.
The full application log also contains the successful copy fallbacks. The
vendor binary and account directories are on different mounts; hard links
cannot cross that boundary. Even matching underlying filesystems do not make
a hard link across separate bind mounts valid.

The persistent launcher now prepares missing `.bitwarden_desktop_proxy` files
before starting Bitwarden, in the same nine directory mounts already exposed
by its sandbox. `BITWARDEN_NATIVE_MESSAGING_PATHS` is shared by the mount list
and initializer. This retains the original mount order and directory set.

The initializer reads the root-owned, executable `/opt/Bitwarden/desktop_proxy`
only when a copy is missing. It bounds the source read, detects modification
during reading, walks destination components with directory FDs and
`O_NOFOLLOW`, and publishes a complete private copy without replacing an
existing file. A competing publication wins without being overwritten.
Temporary copies are removed on handled failures; published files and their
directories are synchronized. Existing valid proxies retain their bytes,
inode and mode. The exact additional Firefox and Flatpak file grants are in
the existing `labwc-app` AppArmor profile; Chromium configuration paths already
have the required account-state grants.

**Limit:** the upstream Bitwarden manifest refresh explicitly unlinks an
existing destination before attempting its hard link. Consequently this
initializer does not guarantee removal of Bitwarden's later `EXDEV` warnings.
The application performs its own copy fallback afterwards. Patching or
suppressing vendor diagnostics has not been introduced.

Upstream behavior was inspected in
[Bitwarden native messaging](https://github.com/bitwarden/clients/blob/main/apps/desktop/src/main/native-messaging.main.ts),
particularly `linkOrCopy()`. This is upstream source evidence; the supplied
logs do not identify an exact Bitwarden package version.

## Ethernet hotplug

`todo/ifup:41-52` shows IPv6 bring-up racing removal of `eth0`, followed by
ifup's exit status 1. `todo/managed/system/usb/usb.log:80-103` records the
Realtek USB adapter disconnecting and being enumerated again, including a
change from a high-speed to a SuperSpeed USB bus. The evidence includes actual
USB device removal, not only Ethernet carrier loss.

`network-ifup-hotplug` runs the native `/usr/sbin/ifup --allow=hotplug IFACE`.
It changes ifup status 1 to a successful expected-removal outcome only when
the interface no longer exists afterwards. Failure with a present or replaced
device, other exit codes and terminating signals retain failure/cancellation
semantics. Device identity reads are bound to a sysfs directory FD; no
numeric process identity or shell command interpolation is used.

The installed drop-in changes only `ExecStart`. The packaged unit's type,
`BindsTo`/`After` device dependencies, `ExecStop=ifdown`, `RemainAfterExit`,
timeouts and process-group ownership remain in effect. The generated
`allow-hotplug` Ethernet stanza, Wi-Fi ownership and link metrics are unchanged.
Ethernet still goes down on removal and is configured again on reconnect.
No link is held up to avoid an error status. No fresh-install cleanup or
migration calls were added.

The installer stages the helper as root-owned mode 0755 and the drop-in as
0644. The existing installed network verification boundary rejects missing,
linked, incorrectly owned or writable assets, unresolved tokens and a changed
drop-in delegate before enabling the managed network boot unit. The helper has
its own AppArmor attachment and retains native ifupdown policy for its child.

The offload messages in `todo/ifup:4-10,28-33,37-43` are driver capability
reports from the existing broad `ethtool -K` request, repeated by the IPv4 and
IPv6 post-up hooks. Those messages alone are not evidence of ifup failure.
No driver settings or performance defaults were changed to hide them.

The packaged contract was inspected in
[Forky ifupdown's service source](https://sources.debian.org/src/ifupdown/0.8.45%2Bnmu1/debian/ifup%40.service).
That source version is not a claim about the exact package on the logged host.

## Tailscale private netkit namespace

The user approved a private **netkit** uplink while keeping the physical
Ethernet/Wi-Fi devices managed on the host. Application veth leases, addresses,
interface names and firewall ownership are unchanged. No macvlan, replacement
Tailscale binary, source compilation or Xwayland change is introduced.

The supplied journal shows veth-only changes causing endpoint rebinds and DNS
reapplication. Upstream 1.104.1 has no Linux interface-exclusion setting.
Bubblewrap cannot filter route-netlink interfaces in a shared network namespace;
a private network namespace is therefore the actual visibility boundary.

The installed `tailscale-netkit` supervisor owns the following topology:

```text
host Ethernet / Wi-Fi
          |
   owned forwarding / NAT
          |
host tailscale0 (netkit primary, host tailnet addresses)
          |
private ts-uplink (netkit peer) -- private tailscale0 (TUN) -- tailscaled
```

Only loopback, the private netkit peer and the daemon's own TUN are present in
its network namespace. Physical devices stay on the host. The host-facing
netkit primary retains the configured `TAILSCALE_INTERFACE` name so existing
SSH, Syncthing and tailnet interface allowlists retain their meaning.
The transit networks are `169.254.253.0/30` and `fd6b:bbad:cd4e:104::/126`;
setup rejects overlaps, existing ownership of table 52, reserved rule
priorities/protocol and an existing owned-table name before mutation.

### Namespace, SSH and authority

The constructor pins network and mount namespace descriptors. It enters the
private network namespace **before mounting fresh sysfs**, so the daemon does
not receive the host's interface directories. Bubblewrap builds a read-only
root with private writable DNS state, temporary storage and the native local
API/state directories. Host D-Bus, resolved and systemd manager sockets are not
passed into that tree. The host PID namespace is retained; AppArmor limits
process-file access. This is not a claim of a private PID or user namespace.

Bubblewrap always sets `no_new_privs`. A direct daemon descendant could not
acquire the wider AppArmor label required to restore a host SSH session.
Instead its only construction payload hands the supervisor pinned private
mount/root descriptors and exits. The supervisor then starts the packaged
daemon in that tree under an explicit named AppArmor transition. It closes all
namespace/root descriptors before the native daemon exec. This construction
handoff requires native verification; AST inspection alone does not prove it.

The daemon profile explicitly denies `CAP_SYS_ADMIN` and host namespace handles.
All four profiles in `usr.sbin.tailscaled` follow the existing
`DESKTOP_APPARMOR_STATE` selection through `modes.conf.tmpl`. Both `enforce` and
`complain` are accepted; neither installation nor runtime dispatch requires an
enforce label. Complain mode remains available for denial diagnostics through
the central mode policy. Its private login/su mounts point to the fixed
`tailscale-ssh-host` helper. After Tailscale's normal SSH authentication and
account selection, that named transition restores the pinned host network and
mount namespaces **and the host root directory**, closes its handles and execs
the distribution login/su with unchanged arguments. Native environment
filtering and PAM remain in the vendor path. The server profile is explicitly
entered by the constructor rather than attached to every package-binary exec;
this lets an authenticated host SFTP session re-exec the vendor's embedded
SFTP child with the account's ordinary host policy.

The bridge supports the vendor's normal login/su SSH behavior. A tailnet policy
forcing deprecated SSH behavior v1 can bypass login/su and is not covered by
this host-session bridge. That policy is not selected anywhere in this repo;
its absence must be confirmed in native acceptance. No tailnet-admin policy was
changed. Authenticated host sessions intentionally regain host networking.
The bridge is an explicit privileged host-session boundary, not a guarantee
that a compromised root SSH daemon has no indirect host authority.

### Routing, physical changes and DNS

The supervisor mirrors only the private daemon's table-52 routes and self
addresses. Unicast routes use the private peer and the correct tailnet source
address. Throw routes preserve exit-node LAN exceptions; unreachable/blackhole
routes preserve address-family blocking. Cleanup explicitly removes owned
non-unicast routes because deleting a link does not remove those routes.
A private iif-specific rule delivers decoded packets for the host's own
addresses ahead of the private local-address rule. Host outer-transport rules
use main routing and a terminal unreachable rule to avoid recursion when an
exit-node default exists and the physical route disappears.

A two-second supervisor poll observes only the two configured physical
identities, their addresses/default routes, and private Tailscale state.
Physical changes update the netkit MTU and request the vendor's local-API
`debug rebind`; application veth events do not reach the daemon's netlink
monitor. This introduces polling and up to roughly two seconds of observation
latency plus command time. No measured CPU or throughput claim is made.

Private bootstrap DNS is DNATed only from the exact transit peer to the
existing loopback application DNS cache, which already forwards through
Stubby. The daemon can change only its private `/etc` DNS files. With
`TAILSCALE_ACCEPT_DNS=false`, no host link-DNS operation is performed. With it
true, the supervisor mirrors only MagicDNS service addresses/search domains
onto the host-facing netkit link and reverts that link on cleanup. It never
passes a private interface index to the host resolved manager.

The selected Tailscale firewall overlay now adds narrowly scoped base-filter
rules for this transport and bootstrap DNS. A separate `inet tailscale_netkit`
table owns source checks, transport-only forwarding constraints, physical-link
UDP DNAT and physical-link masquerading. It never flushes shared tables. UDP
transport ingress matches local destinations on the two configured physical
interfaces. NetworkManager leaves the owned primary unmanaged. IPv6 forwarding
and RA acceptance are configured for those physical interfaces; existing global
reverse-path filtering and application-veth policy are retained.

### Installation, recovery and lifecycle

The late installer stages the two helpers, JSON, NetworkManager/sysctl files,
modules and service override before activation. The offline `validate-target`
gate reads files only: it checks identifiers, JSON types, unresolved tokens,
root ownership/modes/non-writable parents, exact service delegates, required
distribution executables, Python namespace/pidfd APIs and installed boot
configurations containing `CONFIG_NETKIT=y` or `m`. It does not start services,
query a manager, alter networking or load AppArmor policy. Slash-delimited
sysctl keys preserve literal dots in configured interface identifiers. The addon explicitly
requests the packaged runtime tools through the existing signed APT path.

The owning unit retains the Mullvad `ExecCondition`. Dependencies order and
bind it to nftables, the DNS cache and AppArmor; explicit dependency restarts
propagate through `PartOf`. The supervisor and daemon remain in the owning
service cgroup. Commands have bounded input/output, streaming/final-wait
deadlines and a separate termination budget. Signals use pinned pidfds;
missing identity evidence has no numeric-PID signal fallback.

Only `ExecStopPost` removes networking, after checking that the complete bounded
service cgroup subtree contains only the cleanup process, including systemd
262's possible `.control` subgroup. Cleanup and startup share one ownership
lock. Recovery state binds the primary's alias/ifindex, nft table comment and
exact route-rule selectors. Foreign/replaced identities are retained, not
removed. Cleanup has an aggregate deadline; failed or uncertain recovery keeps
`/run/tailscale-netkit/state.json` and reports a distinct outcome. Exit 78
represents an invalid/unavailable contract; exit 79 represents uncertain
termination/recovery. Neither automatically restarts. Confirmed command
failures can restart after owned cleanup. This is runtime lifecycle cleanup of
new owned resources, not migration cleanup for retired fresh-install assets.

The namespace redesign is implemented and staged, but **native acceptance has
not been executed**. Kernel/iproute2 netkit operations, Bubblewrap descriptor
handoff, both address families, NAT/filter syntax, both selected AppArmor modes, boot,
SSH/PAM/SFTP, DNS changes, exit nodes, Mullvad exclusion and failure recovery
remain mandatory isolated gates.

Primary references:

- [Tailscale 1.104.1 monitor](https://github.com/tailscale/tailscale/blob/v1.104.1/net/netmon/netmon.go)
  and [address enumeration](https://github.com/tailscale/tailscale/blob/v1.104.1/net/netmon/state.go).
- [Upstream exclusion request](https://github.com/tailscale/tailscale/issues/1552),
  still open when inspected.
- [Linux network namespaces](https://man7.org/linux/man-pages/man7/network_namespaces.7.html).
- [Bubblewrap namespace options](https://github.com/containers/bubblewrap/blob/main/bwrap.xml).
- [systemd 262 interface restrictions](https://github.com/systemd/systemd/blob/v262/man/systemd.resource-control.xml).
- [Tailscale SSH process launch](https://github.com/tailscale/tailscale/blob/v1.104.1/ssh/tailssh/incubator.go).
- [Linux netkit implementation](https://github.com/torvalds/linux/blob/master/drivers/net/netkit.c).

## Namespace interface renaming

The app-veth broker obtains the fixed private name from the rendered
`namespace_interface` policy. On acquisition it moves the pool peer into the
application namespace and renames it to that fixed name, normally `eth0`.
On release it restores the pool peer name for reuse. This gives every
application the same private interface name irrespective of its pool slot;
it has no inherent performance or isolation benefit. The kernel's rename
record does not imply that the physical host Ethernet adapter was renamed.
Neither interface naming nor veth lifecycle was changed by this patch.

## Audited executable lookup failures

The four failed audited exec calls have errno `ENOENT`, followed by successful
execution from a later PATH directory. They are not AppArmor permission errors.
The continuation removes the avoidable failed lookups at their callers:

- `auditd.log:1010-1014`: swayidle internally uses `execvp("sh", ...)`. Its
  existing user service now searches `/usr/bin:/bin` before `/usr/local/bin`.
  The idle arguments, timing and existing absolute helper paths are unchanged.
- `auditd.log.1:8111-8117,8160-8166,8177-8183`: GNU timeout searches PATH for
  `vdirsyncer`. The calendar wrapper now resolves that command once with
  `command -v` and passes the quoted result to timeout. Existing PATH selection,
  arguments, deadlines, private logs and process-group cancellation are retained.

Both assets already have explicit desktop staging and verification entries.
The existing AppArmor profiles already authorize the selected distribution
executables. No additional policy grants are required. The change has been
inspected as data; swayidle and calendar synchronization have not been executed.

Primary source for swayidle's internal shell invocation:
[swayidle main.c](https://github.com/swaywm/swayidle/blob/master/main.c).

## Remaining log coverage and disposition

| Evidence | Finding and disposition |
| --- | --- |
| `todo/.~` | Historical October 13 snapshot: Tailscale bootstrap ends in `NeedsMachineAuth` and explicitly reports pending admin approval. Current bootstrap already retains state and retries without reusing the key. Approval cannot be manufactured by installer code. Waypaper falls back to all outputs when no enumerator is available; the log alone does not establish broken wallpaper selection. |
| `todo/journalctl`, `managed/apps/apps.log` | Duplicate Bitwarden/Ethernet/Tailscale evidence above. Vivaldi reports a missing Proton VPN extension and blocks a NoScript icon that is not exported by the extension's manifest. Current managed policies do not install Proton VPN. Changing profile state or relaxing extension security is not justified by these records. Foot reports a terminal child receiving HUP during close. |
| `managed/network/veth.log` | Recorded lease acquisitions/releases; no failure record. |
| `managed/security/apparmor/{apparmor,modes}.log` and audit logs | Profile load/mode records; no AppArmor `DENIED` or `ALLOWED` violation record. The four failed `ENOENT` PATH probes are removed at their callers as described above; no permission relaxation was needed. |
| `managed/security/crowdsec/*` | Console enrollment/synchronization is pending; local API responses are 674 HTTP 200 and 12 HTTP 201. The bouncer log has no failure record. The qBittorrent log is absent before the application starts; file discovery polling is enabled. Repeated grok registrations are upstream parser warnings. These do not establish a local engine or firewall bouncer outage. |
| `managed/security/nftables/nftables.log` | Accept logs and 19 inbound TCP ACK drops on high ports. No failed ruleset operation is recorded. These records do not justify opening ports or weakening the firewall. |
| `managed/security/auth/auth.log`, `fail2ban/fail2ban.log` | Session activity and a newly created Fail2Ban database, without an authentication or service failure. |
| `managed/system/{kernel,system}.log`, `usb/usb.log` | Ethernet removal above; USB-C UCSI `GET_PDOS` failures and an xHCI dequeue warning require hardware/kernel/firmware reproduction. Bluetooth lacks an identity file on first startup; generating replacement keys is not a justified repair. Martian packets coincide with dual-link transition; the records do not justify weakening source validation or allowing local-source spoofing. |
| `managed/system/initramfs/*`, `timeshift/timeshift.log`, `zram/zram.log` | Boot, snapshot and zram activity; no failed operation found. |
| Empty model, antivirus, integrity, scanner, storage and fwupd logs | No evidence of either successful execution or a failure; empty logs are not acceptance results. |

The global Labwc missing-Xwayland diagnostics reflect the intentionally absent
global Xwayland binary. The private Zoom/Discord eligibility and implementation
remain unchanged, as requested.

## Unexecuted acceptance gates

The new incident fixtures cover the nine copies, repeat launch, deleted-copy
repair, symlink rejection, publication failure and competing publication;
ifup removal, replacement, ordinary failure, signals, exact arguments and
fixture-only identity reads. Existing network readiness fixtures now stage
the new assets and reject missing/writable/linked/unrendered assets and altered
service delegates. These fixtures have not run.

The netkit fixture also exercises construction delegates, startup and cleanup
for both selected desktop modes while rejecting any direct profile-label read.
It mocks external operations and has not run; it does not establish native
AppArmor acceptance.

Required isolated native checks include Forky Python 3.14 and systemd 262;
AppArmor compilation and startup/SSH/recovery under both `enforce` and `complain`;
a real USB Ethernet removal during IPv6 DAD;
cable carrier loss/reconnect and manual Wi-Fi switching; native Bitwarden
launch and browser native messaging across the actual mount boundary; and
the native/private Zoom/Discord launch and shutdown regression invariants.
Tailscale's zero-veth visibility and host integration require the isolated
native gates above; the design is implemented but those gates have not run.

## Executed serialization and static inspection

After reading the Makefile, `tools/build.py` and `tools/publication.py`, the
permitted pure serialization command completed successfully:

```sh
/usr/bin/env -i PATH=/usr/bin:/bin LC_ALL=C.UTF-8 /usr/bin/make build 'PYTHON=/usr/bin/python3 -I' SHELL=/bin/sh
```

The final build produced 1,805 payload members containing
34,633,937 source bytes. Independent standard-library archive/hash
inspection found exact source/manifest/archive agreement, the complete expected
payload file set, normalized member metadata, and matching preseed archive,
manifest and bootstrap-source pins. Nothing was extracted or executed.

Source-only AST parsing completed for 10 changed Python sources/fixtures.
The JSON template was substituted as data for all ten production profiles and
parsed with the standard JSON parser. These are static inspections, not runtime
test results. `git diff --check` completed. AST comparison against HEAD found
`APPS` and `WAYLAND_COMPAT_APPS` unchanged; all 13 Bitwarden persistent
directories retain their original order. Only the Bitwarden preparation call
changed an existing sandbox function. No Perl/shell/AppArmor/systemd native
validator was run.

The source fingerprint below hashes sorted `<file SHA-256>  <relative path>\n`
records for `d-i/forky`, including fixtures and excluding the three generated
products, private input names and interpreter caches. Generated-product hashes
and fixture hashes bind this evidence to the recorded source snapshot.

| Item | SHA-256 |
| --- | --- |
| `payload.manifest` | `a5abecf4daea6bfbf148211f9bd35e2fb8547693e4b14e2661852d3c86085cde` |
| `payload.tar.gz` | `098b5dbf84d7f3ecc2e4e34564ed9e8eaaa96d514e7a1ffa6349651d51b4cb8f` |
| `preseed.cfg` | `db37a9b368f8d487ff67b5f8437ea19779634e93ec4737764e8990438fd5ab56` |
| `d-i/forky` source fingerprint | `047c3993e286b0ffd07481113839796245dc7017d57de25c2f648fea1c3553cf` |
| `test_apparmor_incidents_20261004.py` | `2b72a686f5958e0b3de050c35509e80958b6dd8bf38fb902f85c89a8dfffa54d` |
| `test_boot_runtime_20260913.py` | `74b19a515d7c31688a91fcec6452ee8d9befe14dcadb53b7c632fa82f0a62f0c` |
| `test_tailscale_netkit_20261017.py` | `9792edf4f639d31713c36d29d4ed5399fa3170133c5718603edc2726809b1923` |
| `test_todo_network_incidents_20261017.py` | `aea196f870beb94f0edb31c6b5962512959ad0596b1e2564bcb70d274942be63` |

Independent agent reviews could not start because the runtime rejected their
encrypted context. No independent review result or test result is claimed.


No disposable image was executed, so no target image identity or tested package
version exists for this revision. The target acceptance gates above remain open.

## Changed paths

- `d-i/forky/classes/class-addon/tailscale.cfg`
- `d-i/forky/hooks/target/etc/NetworkManager/conf.d/75-tailscale-netkit.conf.tmpl`
- `d-i/forky/hooks/target/etc/apparmor.d/desktop-wrappers.tmpl`
- `d-i/forky/hooks/target/etc/apparmor.d/system-wrappers.tmpl`
- `d-i/forky/hooks/target/etc/apparmor.d/usr.sbin.tailscaled`
- `d-i/forky/hooks/target/etc/modules-load.d/50-tailscale.conf`
- `d-i/forky/hooks/target/etc/nftables/services/tailscale.yml.tmpl`
- `d-i/forky/hooks/target/etc/skel-desktop/.config/systemd/user/swayidle.service`
- `d-i/forky/hooks/target/etc/sysctl.d/92-tailscale-netkit.conf.tmpl`
- `d-i/forky/hooks/target/etc/systemd/system/ifup@.service.d/40-device-lifecycle.conf`
- `d-i/forky/hooks/target/etc/systemd/system/tailscaled.service.d/override.conf.tmpl`
- `d-i/forky/hooks/target/etc/tailscale/netkit.json.tmpl`
- `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/network/ManagedNetwork/Validator.pm`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/profiles.py.tmpl`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/sandbox.py`
- `d-i/forky/hooks/target/usr/local/libexec/labwc-calendar`
- `d-i/forky/hooks/target/usr/local/libexec/network-ifup-hotplug`
- `d-i/forky/hooks/target/usr/local/libexec/tailscale-netkit`
- `d-i/forky/hooks/target/usr/local/libexec/tailscale-ssh-host`
- `d-i/forky/hooks/target/usr/local/sbin/nft-policy-generate.py`
- `d-i/forky/payload.manifest`
- `d-i/forky/payload.tar.gz`
- `d-i/forky/preseed.cfg`
- `d-i/forky/scripts/late/network.sh`
- `d-i/forky/scripts/late/security.sh`
- `d-i/forky/scripts/late/tailscale.sh`
- `d-i/forky/tests/test_apparmor_incidents_20261004.py`
- `d-i/forky/tests/test_boot_runtime_20260913.py`
- `d-i/forky/tests/test_tailscale_netkit_20261017.py`
- `d-i/forky/tests/test_todo_network_incidents_20261017.py`
- `docs/todo-log-review-20261017.md`
