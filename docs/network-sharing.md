# Profile-controlled NFS network sharing

## Scope and deployment status

This addition targets the requested Debian Forky / systemd 261.2 installation.
It uses Debian binary packages, the existing late-command pipeline, the existing
managed nftables compiler, and the existing desktop authorization policy. It
does not compile software, create a second firewall manager, or change the
private Zoom/Discord Xwayland configuration.

All ten host profiles contain the same explicit NFS controls. Both roles and
both home binds are **disabled by default**. The installer always creates the
root-owned `/data/sharing` directory and a root-owned, non-secret
`/etc/network-sharing/config.json`, including when both roles are disabled.
Disabled roles do not install their NFS packages or add NFS mounts/exports.

See [the validation record](validation/network-sharing-20260930/README.md) and
[BUILD-STATUS.md](../BUILD-STATUS.md) before publication. Offline success is not
proof that a fresh Forky installation, the packaged NFS daemons, AppArmor
**enforcement**, or real network/filesystem failure behavior has passed. The
broad repository suite is not a passing release signal for this snapshot.

## Enable the intended hosts, not every profile

Edit the selected file in `d-i/forky/hosts/profiles/`. A server with its local
share visible at `~/Sharing/nfs-server` uses:

```sh
NFS_SERVER_ENABLE="true"
NFS_SERVER_BIND_ENABLE="true"
```

A client with a home bind uses:

```sh
NFS_CLIENT_ENABLE="true"
NFS_CLIENT_BIND_ENABLE="true"
NFS_CLIENT_TARGET_IP="192.168.50.212"
```

The IP above is the shipped **example**, not a discovered server. Replace it
with the real server address. That server must export this profile's NFSv4
root and admit the client's actual source address. An address allocated to a
server is not thereby allocated to a client: verify DHCP reservations/static
addresses separately. Both roles can be enabled on the same host. The installer
does not assign a new interface address or modify the existing network manager.

For a read-only client also set `NFS_CLIENT_READ_ONLY="true"`. Server-side `ro`
remains authoritative regardless of the client flag. After changing a profile,
run the build/check commands below and publish a consistent snapshot; do not
edit the generated payload manually. NFS settings must be double-quoted data
with, at most, `${PREVIOUS_VARIABLE}` expansion; command substitution, shell
backticks, forward references and duplicate NFS assignments are rejected by the
build-time gate. This gate validates the same scalar policy as the target
configurator without executing the profile shell.

## Profile reference

| Variable | Default and meaning |
| --- | --- |
| `NETWORK_SHARING_ROOT_PATH` | `/data/sharing`; always created, root-owned, normally mode 0755. A customized root must be strictly below `/data`, `/pool`, or `/srv`. |
| `NFS_SERVER_ENABLE` | `false`; install and configure the dedicated NFSv4 server. |
| `NFS_SERVER_PATH` | `${NETWORK_SHARING_ROOT_PATH}/nfs-server`; the only exported directory. |
| `NFS_SERVER_BIND_ENABLE` | `false`; bind the local server directory into the primary account home; requires the server role. |
| `NFS_SERVER_HOME_BIND_PATH` | `Sharing/nfs-server`; relative to `ACCOUNT_HOME`, never an absolute path. |
| `NFS_SERVER_DEPS` | `nfs-kernel-server nfs-common libnfsidmap1 keyutils nftables acl e2fsprogs`; required package closure is validated. Additional valid package names are allowed. |
| `NFS_SERVER_THREADS` | `8`; validated range 1-128. |
| `NFS_SERVER_RW_OPTIONS` | `rw,sync,subtree_check,root_squash,secure,sec=sys,fsid=0`; profile shorthand used to compose exports. |
| `NFS_SERVER_RO_OPTIONS` | `ro,sync,subtree_check,root_squash,secure,sec=sys,fsid=0`; read-only shorthand. |
| `NFS_SERVER_EXPORTS` | One fully expanded export line with the exact CIDRs below; one directory, no wildcard/DNS peers, no overlapping ranges. This line drives both exports and the server firewall allowlist. |
| `NFS_CLIENT_ENABLE` | `false`; install the NFS client and its managed automount. |
| `NFS_CLIENT_PATH` | `${NETWORK_SHARING_ROOT_PATH}/nfs-client`; local mountpoint, not the remote server path. |
| `NFS_CLIENT_BIND_ENABLE` | `false`; bind the client mount into the primary account home; requires the client role. |
| `NFS_CLIENT_HOME_BIND_PATH` | `Sharing/nfs-client`; relative home destination. |
| `NFS_CLIENT_TARGET_IP` | `192.168.50.212`; example RFC1918 IPv4 server, change for the installation. No hostname, public IP, IPv6, or CIDR is accepted here. |
| `NFS_CLIENT_EXPORT_PATH` | `/`; remote NFSv4 namespace path. The configured server's `fsid=0` directory is mounted as `IP:/`, **not** `IP:/data/sharing/nfs-server`. |
| `NFS_CLIENT_VERSION` | `4.2`; only `4.1` or `4.2`, with no silent downgrade to v3 or v4.0. |
| `NFS_CLIENT_READ_ONLY` | `false`; make the source and optional client home bind read-only locally. |
| `NFS_CLIENT_MOUNT_TIMEOUT` | `30`; initial mount job timeout in seconds, range 5-120; not an application I/O deadline. |
| `NFS_CLIENT_DEPS` | `nfs-common libnfsidmap1 keyutils nftables e2fsprogs`. |
| `NFS_ACCOUNT_UID` / `NFS_ACCOUNT_GID` | `1000` / `1000`; required existing primary account IDs on every peer. A mismatch aborts; users are never renumbered. |
| `NFS_SHARED_GROUP` / `NFS_SHARED_GID` | `nfs-sharing` / `2050`; same group name and numeric GID on all peers. An existing conflicting name/GID is rejected, never silently renumbered. |
| `NFS_INTERFACES` | `${MANAGED_NETWORK_ETHERNET_IFACE} ${MANAGED_NETWORK_WIFI_IFACE}`; existing explicit host interface names, not wildcard or loopback. Confirm these are the trusted interfaces. |
| `NFS_TCP_RMEM` / `NFS_TCP_WMEM` | `4096 131072 16777216` / `4096 16384 16777216`; ordered TCP minimum/default/maximum bytes. |
| `NFS_SOCKET_RMEM_MAX` / `NFS_SOCKET_WMEM_MAX` | `16777216` each; socket buffer ceilings. |

Paths deliberately exclude whitespace, shell metacharacters, `%` specifiers,
traversal and ambiguous separators. Escaped mount/automount unit names must
fit systemd's 255-character limit. Server/client paths must be separate
children of the sharing root. Home binds must be separate and have a dedicated
parent directory. Every boolean must be exactly `true` or `false`.

## Exact export and firewall policy

A non-power-of-two interval cannot be expressed as one exact CIDR. The shipped
policy uses the minimum aligned blocks covering the requested intervals,
including endpoints and **no adjacent addresses**:

| Requested IPv4 addresses | Access | Exact CIDR blocks |
| --- | --- | --- |
| `192.168.50.82-192.168.50.100` | Read/write | `192.168.50.82/31`, `192.168.50.84/30`, `192.168.50.88/29`, `192.168.50.96/30`, `192.168.50.100/32` |
| `192.168.50.112-192.168.50.122` | Read-only | `192.168.50.112/29`, `192.168.50.120/31`, `192.168.50.122/32` |
| `192.168.50.212-192.168.50.222` | Read/write server peers | `192.168.50.212/30`, `192.168.50.216/30`, `192.168.50.220/31`, `192.168.50.222/32` |

The final interval is interpreted as trusted read/write server peers, **not**
unsquashed root peers. All 41 addresses use `root_squash`, `secure`, `sync`,
`subtree_check`, `sec=sys`, and `fsid=0`; only `ro` versus `rw` changes.
`secure` requests reserved source ports and the client explicitly uses
`resvport`. Neither a reserved port nor an IP allowlist authenticates a hostile
machine. `sync` is chosen over asynchronous export acknowledgements. The
single `fsid=0` export avoids adding a second pseudo-root/crossmount policy.
The exported directory is a subdirectory of the data filesystem, so
`subtree_check` prevents guessed filehandles from bypassing the directory
boundary. This adds server lookup work and can cause stale filehandles when
open files are renamed. Exporting an entire dedicated filesystem could avoid
that tradeoff, but this change does not alter the storage layout.
Do not mount unrelated filesystems beneath this export expecting them to be
published: automatic cross-filesystem exporting is not enabled.

`hooks/target/etc/exports.tmpl` is rendered only for the server role. Its managed
block is installed into `/etc/exports`, preserving comments. Existing unmanaged
active exports, including `exports.d/*.exports`, are rejected rather than
silently sharing a pseudo-root or expanding access. There is no wildcard
export and no `no_root_squash`, `insecure`, `async`, or `crossmnt` option.

The server overlay admits TCP 2049 from those CIDRs on the chosen interfaces.
The client overlay permits TCP 2049 to the configured server `/32` only.
Both explicitly enable `enforce_allowlist` in the existing policy compiler.
For these service ports, regular-chain guards run after invalid-packet drops
and before established, loopback or local-hook accepts. A matching peer and
interface returns to normal filtering; every other address/interface, including
IPv6, is dropped. These guards never grant an early accept or bypass another
firewall owner's policy. Their restrictions also apply to existing TCP flows
when the managed rules are reloaded; no conntrack flush is required.
There are no new UDP, rpcbind, NFSv3, or IPv6 NFS accept rules. IPv4/IPv6 default
and established-connection handling remain the existing firewall's policy.
The repository's general outbound policy remains in effect for other ports;
the client guard enforces its NFS destination/interface allowlist even with
an accepting base output policy. Administrative local hooks and established
traffic cannot bypass either NFS guard. Active NFS with `NFT_PROFILE=none`
is rejected. NFS does not flush tables belonging to CrowdSec, Fail2ban or other
managers.

## Identity mapping and filesystem permissions

This implementation uses **AUTH_SYS (`sec=sys`)**, not Kerberos or RPC-over-TLS.
It supplies no transport encryption and cannot stop an allowed hostile client
administrator from presenting another user's numeric credentials. Use only a
trusted LAN, or separately provision and verify a trusted encrypted network.
Do not expose TCP 2049 directly to the Internet. A mutually authenticated
Kerberos/TLS deployment requires its own credentials and policy; none are
invented or silently substituted here.

The primary account is added to `nfs-sharing` GID 2050 (or the explicitly chosen
consistent group/GID). Coordinate numeric user UIDs as well as the shared GID
across hosts. `NFS_ACCOUNT_UID` and `NFS_ACCOUNT_GID` make the primary-account
contract explicit (1000:1000 by default); the installer checks the existing
account before package changes. Use the same account names, numeric IDs and
`SYSTEM_DOMAIN` on all peers. The NFS mapping domain is always derived as
`sharing.${SYSTEM_DOMAIN}` (lowercased and validated), with no independent
profile setting. Name mapping does not replace AUTH_SYS's numeric authorization.
The installer does **not** renumber existing users or recursively change file
ownership. Log in again after changing group membership on an existing system.

The server directory is root-owned, group `nfs-sharing`, mode **2770**. Its
access and default ACLs are replaced on that directory, removing inherited or
pre-existing named entries rather than retaining unintended grants. The
default ACL preserves group access for newly created shared content; individual
applications can still deliberately create restrictive modes. Existing child
content is not recursively rewritten. `rpc.mountd` uses `manage-gids=yes`, so
the server resolves supplemental membership from its own identity database.
The primary GID remains client-supplied; `manage-gids` does not authenticate
credentials or remove the trusted-client requirement of AUTH_SYS.
Provision all intended users/group memberships on the server, not just on a
client. Root-squashed anonymous users have no automatic permission to traverse
this group-only directory.

The client mountpoint and unused home bind endpoints are root-owned mode
**000** while unmounted, preventing ordinary users from accidentally depositing
local data at a disconnected mount destination. Once mounted, remote/export
permissions apply. An automount stub can be traversed sufficiently to trigger
mounting; errors/outages do not turn it into a writable local fallback.

Home binds use a dedicated root-owned `~/Sharing` parent, mode 0755, and empty
root-owned endpoints. After creating **all** enabled endpoints, the installer
sets the immutable flag (`chattr +i`) on each dedicated first-level parent.
Root ownership alone does not prevent the home owner from renaming that parent
and substituting a symlink that fstab generation would resolve elsewhere.
The immutable parent prevents that substitution without changing ownership or
mode of the home itself, or making the mounted export contents immutable.

The profiles include Debian `e2fsprogs` for `/usr/bin/chattr`; a configured
home-bind role must retain this dependency. Setting the flag requires a
supporting filesystem and the installer's `CAP_LINUX_IMMUTABLE` capability.
Failure aborts before managed fstab entries or the success record are written;
there is no unsafe fallback. Only the dedicated parent is locked, not the
export data, and this feature never runs when both home binds are disabled.

The account home itself must be a real, non-group/world-writable directory
belonging to the primary account. Existing user-owned
parents (for example an already-populated `~/Documents`), symlinks, writable
configuration ancestors and nonempty mount destinations are rejected. No user
files are covered or recursively chowned. This is a fresh, offline installation
contract, **not** a general-purpose live-home migration tool resistant to a
concurrently mutating account.

## Kernel, daemon and systemd configuration

When a role is active the installer writes:

* `/etc/idmapd.conf`: domain `sharing.${SYSTEM_DOMAIN}`, `No-Strip=none`,
  `nobody`/`nogroup` fallback and NSS mapping. Active unmanaged
  `/etc/idmapd.conf.d/*.conf` overrides are rejected.
* `/etc/modules-load.d/60-network-sharing.conf`: `sunrpc`, plus `nfs` and
  **`nfsv4`** for clients, and `nfsd` for servers; dependent kernel modules are
  resolved by modprobe.
* `/etc/modprobe.d/60-network-sharing.conf`: client `options nfs
  nfs4_disable_idmapping=0` and/or server `options nfsd
  nfs4_disable_idmapping=0`, as appropriate.
* Client `/etc/request-key.d/id_resolver.conf`: the packaged
  `/usr/sbin/nfsidmap` upcall, cache timeout 600 seconds. Other request-key
  handlers are not replaced. Server mapping is handled by the packaged
  `nfs-idmapd.service`; a client-only install does not start a server-bound
  idmapd service.
* `/etc/sysctl.d/60-network-sharing.conf`: TCP window scaling and receive
  autotuning enabled, validated read/write vectors and socket ceilings. The
  correct kernel key is `net.core.wmem_max`, not `net.core.wmen_max`.

These sysctls affect the host network stack, not just NFS. The default 16 MiB
ceilings are explicit policy, **not a benchmark-proven optimum**. They override
any earlier baseline buffer values only on hosts with an active NFS role.
An administrator should tune for actual bandwidth/latency/memory, then rebuild.
The normal subsequent kernel/initramfs installation path remains responsible
for applying the modprobe configuration to the installed boot environment.

Servers additionally receive `/etc/nfs.conf.d/60-network-sharing.conf`:
TCP 2049, eight configured worker threads, NFSv4.1/4.2 enabled, **v2/v3/v4.0**, UDP
and RDMA disabled. Both active roles mask `rpcbind.service`, `rpcbind.socket`,
`rpc-statd.service` and `rpc-statd-notify.service`; this is a deliberately v4-only
host policy and must not be combined with an unrelated legacy RPC/NFSv3 need.
The normal packaged NFS client target/server service are enabled offline.

Both roles require `network-sharing-identity.service` before use. This finite,
read-only check verifies the primary UID/GID/home, shared GID and membership,
nonprivileged anonymous identities, the exact mapping policy, the effective
`nfsidmap -d` domain, and enabled name mapping in the loaded role modules.
Clients also require the managed request-key upcall with no competing exact
`id_resolver` handlers; servers verify the effective v4-only daemon policy and
server-side `manage-gids` membership resolution using `nfsconf --dump`. The
check never changes identities, flushes keyrings or writes kernel state, and
keeps no process or cached success state between starts. Built-in/preloaded
modules that ignore the modprobe options fail closed and need the correct
boot parameters (`nfs.nfs4_disable_idmapping=0` and/or
`nfsd.nfs4_disable_idmapping=0`) before retrying.

The server drop-in is staged **before** package installation: inhibiting package
starts does not prevent maintainer scripts from enabling a unit for a future
boot. Its `AssertPathExists=` prerequisites require the NFS completion record,
the managed daemon configuration, the generated filter table, and the managed
nftables service override. An interrupted configuration therefore causes a
failed server start rather than a successful skip or unguarded package-preset
startup. The firewall override's existing syntax check and lifecycle dependency
remain mandatory. These are installation-completion guards, not protection
against a privileged administrator changing completed configuration.

The server unit requires the real export filesystem and the idmap service,
and is bound to both the managed firewall and idmap services. The mapper
requires `/proc/fs/nfsd` to be mounted before it starts. The client source
mount is also bound to the managed firewall service. Its start/reload overrides
require `exportfs -r` to succeed instead of inheriting the vendor unit's
error-ignoring command prefix. An export-refresh failure is therefore visible
to systemd and to the menu; it is not silently reported as success.
Both root helper services require and follow `apparmor-modes.service` before
reading their actual kernel AppArmor labels. An unavailable, unconfined or
complain-mode label fails the helper before any configuration processing; a
failed identity prerequisite prevents server/client startup. `AppArmorProfile=`
alone is insufficient when AppArmor is disabled. The LSM-specific process-label
interface is preferred, with the legacy interface used only when it is absent.
Mountd and idmapd have bounded
restarts and stop jobs, private temporary directories, protected home/system
paths, and other compatible systemd restrictions. Mountd retains `AF_NETLINK`
alongside its existing permitted families so nfs-utils can use kernel export
and AUTH_SYS group-cache upcalls rather than being forced into legacy fallback
by the service sandbox. The kernel-backed NFS server
retains its required host networking and NFS state access. The implementation
does not pretend it can isolate kernel nfsd workers with a generic userspace
sandbox or apply an untested capability allowlist to all nfs-utils binaries.
Stopping the firewall service stops the bound server; restarting/reloading the
firewall should be followed by checking the server state. Binding to a service
does not detect an administrator manually deleting rules from the kernel.

Package installation temporarily inhibits service starts and restores the
previous `policy-rc.d` exactly, including a previous symlink. Installer commands
use fixed absolute executables and argument arrays, bounded child waits, and
private staged assets from the pinned payload. Commands have their own process
group; timeout/error cleanup signals the still-owned group before reaping the
leader and restoring package-start inhibition. This prevents ordinary dpkg or
maintscript children from continuing after only apt has been killed. It is not
a sandbox for malicious packages or descendants that deliberately detach; the
trusted package policy and outer installer supervision remain required. A
package timeout is fatal and may require administrator repair of interrupted
dpkg state; the installer does not pretend it can roll back package scripts.
It does not mount shares, run
`exportfs`, start daemons, load modules or apply sysctls inside the installer.
Configuration writes are guarded and atomically replaced. An installation
failure aborts; this is not a transaction that rolls back every package or
file already installed. Do not boot/publish a partially failed installation.

### Mount options and ordering

Client fstab entries use `hard,proto=tcp,port=2049,resvport,sec=sys,vers=4.2`
(or explicit 4.1), `nosuid,nodev,noexec,_netdev,nofail`, an automount, the
configured initial mount timeout, and dependencies on `nfs-client.target` and
`nftables.service`. Both binds use `x-systemd.requires-mounts-for=` with the
**actual source path**, not a doubled sharing root or a literal variable name.
The client home bind also automounts and has a `BindsTo=` relationship to its
source mount, so stopping/disappearing source mounts tears it down.

There is deliberately no idle-unmount timer: an active bind can keep the
underlying filesystem busy. `nofail`/automount avoid making an absent server a
mandatory boot mount. `hard` is deliberate for data integrity. It can block
application I/O during server/storage outages, even after the initial mount
job's timeout has elapsed; `noexec` is also not a general content sandbox.
No `soft`, forced unmount, lazy detach, or filesystem-wide kill action is used.
Close files/applications before disconnecting. Review real shutdown behavior
under an outage in the acceptance test; kernel-blocked I/O is not magically
bounded by a userspace service timeout.

## Network Sharing desktop menu and authorization

Open **Computer Management -> Network & Remote -> Network Sharing**. It uses
the existing Fuzzel picker, its theme/category icon, and the existing optional
fzf backend. Back/cancel is non-destructive. The menu includes Sharing Status,
Connect/Disconnect, Check Connected NFS Clients, Start/Stop/Restart NFS Server,
Reload NFS Exports, Identity Mapping and RPC Diagnostics, Show Configured
Exports, Recent NFS Logs, and Sharing Help.

The menu always runs as the desktop user. It never invokes `sudo`, `pkexec`, a
shell, arbitrary mount arguments, or a user-entered hostname. It only controls
fixed packaged/report units and the installed configuration's validated mount
unit names. Disabled roles explain how to enable the installation profile;
clicking a menu entry cannot install packages or enable an unconfigured role.
Privileged unit changes go through the repository's existing active-local
administrator Polkit policy and graphical authentication agent. There is no
new permissive sudoers or Polkit rule. Check that agent on the real desktop;
a denied/cancelled authorization is an error, not an implicit success.

Disconnect, stop, restart and reload require confirmation with **Cancel** as
the default. Disconnect submits stops for both automounts and mounts, and
never forces a busy filesystem. A timed-out systemctl client is reaped; its
already-submitted PID 1 job may still complete, so inspect status before
retrying. Read-only status uses unit properties, not `ls`, `statfs`, `df` or
other operations on the remote mount. Configured exports are labelled as the
installed policy, **not** a live export listing. Journal visibility follows the
existing user's journal group permissions.

### Bounded diagnostics and AppArmor

Root-only kernel diagnostics run in the short-lived
`network-sharing-report.service`, not in the menu process. The fixed helper
reads NFS counters, mapping parameters and `/proc/fs/nfsd/clients/*/info`.
It never uses `showmount` (not an authoritative NFSv4 client inventory), reads
remote directories, expires clients, flushes mapping caches, or mutates kernel
state. A host-network view is retained for `/proc/net/rpc`; it does not create
network sockets. The service has no capabilities, no allowed IP traffic,
restricted syscalls/address families, protected kernel/system/home paths,
bounded start/stop time, 16 tasks, 96 MiB memory and a CPU quota.

At most 128 numeric client records and 8192 bytes per kernel diagnostic input
are collected. Remote client names are treated as untrusted text and controls
are stripped. A timestamped report is atomically published root/shared-group
0640 in `/run/network-sharing` mode 0750. A failed refresh never returns an
old report as fresh. The UI limits displayed rows/width and identifies
truncation. Authorized group members can inspect the bounded JSON file for
more detail without granting them root access.

The client list reports **kernel NFSv4 lease/client records**, not an exact
live TCP connection count. A record may outlive a connection; an unavailable
kernel interface or denied read is shown as unavailable, not zero clients.

`etc/apparmor.d/network-sharing` supplies separate menu, report and identity-check
profiles, with confined systemctl/journalctl and nfsidmap/nfsconf child profiles
and the existing confined picker transition. Explicit, peer-limited termination and child-completion
signal rules let the menu reap its command children without granting it
authority to kill arbitrary processes. It is registered in the existing required system-policy
inventory and follows `DESKTOP_APPARMOR_STATE`; a profile set to complain is
**not** enforcing. The report and identity-check services explicitly request
their AppArmor profiles and refuse to work without their own enforcing labels.
Selecting desktop complain mode therefore prevents a subsequent NFS start
or diagnostics refresh until the NFS profiles are enforcing again; it does
not stop already running kernel exports or existing mounts. The identity
helper and its `nfsidmap -d` child use the strict NSS abstraction for local
identity lookup, with explicit IP and netlink denials matching their systemd
address-family restrictions. Only the running process's read-only AppArmor
label attributes are added to the helper policies.
Parser success alone cannot demonstrate enforce-mode interoperability. There
is no newly invented daemon AppArmor policy for mountd/idmapd/nfsd; their added
isolation is provided by the compatible systemd drop-ins described above.

## Rebuild, reruns and administrator changes

From the repository root:

```sh
python3 -B tools/check_network_sharing.py
python3 -B -m unittest discover -s d-i/forky/tests -p test_network_sharing.py -v
make build
make check
python3 -B tools/check_preseeds.py
make audit
```

The normal builder includes the NFS profile gate. `make build` regenerates
`preseed.cfg`, `payload.manifest` and `payload.tar.gz`; those three must match
the source tree before serving it. The delivered archive includes them. Run
`make test` and the complete release validator as well; do not ignore a failed
release gate merely because the focused NFS checks pass. A full suite can take
longer than the validator's default per-suite timeout; choose an adequate
`tools/validate.py --test-timeout` on the release host rather than suppressing
tests. Serve only after reviewing destructive disk choices and credentials.

An identical offline configurator rerun is idempotent. A changed saved profile
is rejected, rather than leaving stale exports, mounts or firewall rules.
For a live deployment change, schedule maintenance, close share users, stop the
relevant mounts/automounts and services through PID 1, back up the current
configuration and data, and review every affected managed artifact. Coordinate
exports, source/bind units, fstab markers, identity mapping, group IDs, module
options and firewall rules together. Verify no old active mount/export survives
and check the new effective state before reopening access. Reinstalling from
a rebuilt profile is the supported deterministic path; this patch intentionally
provides no automatic live-role migration/removal command. Never simply delete
`config.json` to defeat the changed-profile guard.

For removal of an optional home bind, first stop its mount and automount units,
remove their managed fstab entries and related unit drop-ins, run
`systemctl daemon-reload`, and confirm that no active mount or startable old
bind definition remains. Only then may an administrator clear the dedicated
parent's immutable flag, for example `chattr -i -- /home/mcramer/Sharing` for
the default account. Do not recursively clear attributes or touch share data.
Unlocking the parent while root-managed binds still exist reopens the path
redirection vulnerability. Partial installation failures can leave the parent
locked; inspect and remove any bind definitions before the same cleanup.

## Live acceptance before enabling production sharing

Use disposable hosts/VMs and disposable files, matching the actual target
kernel/packages/systemd 261.2. Confirm the disabled-profile case still creates
`/data/sharing` without new NFS mounts/packages. Exercise server-only,
client-only, both roles, and each bind setting. Then check:

1. Inspect effective `nfsconf`, `exportfs -v`, nftables rules and
   `systemctl cat` output; verify TCP 2049 only, correct interface/source CIDRs,
   no v2/v3/UDP/RDMA service exposure, and no unintended inherited overrides.
   Check `nfsidmap -d`, the installed domain/group/UIDs, module parameters,
   `getent group nfs-sharing`, sysctls and `findmnt` options/dependencies.
2. From actual distinct permitted source IPs, verify allowed RW create/read/
   rename/remove, RO read but failed create/remove, and root-squash denial.
   Confirm ordinary group members can collaborate with correct numeric owners.
   Probe adjacent excluded addresses such as .81, .101, .111, .123, .211 and
   .223. Never change the live management host's address just to run this test.
3. Reboot with the server absent, trigger both client access paths, restore the
   server, then disconnect with closed and deliberately busy disposable files.
   Verify no local fallback writes or hidden user files, correct bind teardown,
   and understood blocked-I/O/shutdown behavior. Check the server does not
   export an underlying empty directory when its source filesystem is absent.
   Inspect `lsattr -d` on each dedicated home-bind parent. As the ordinary
   account, verify parent rename/removal is denied, including with the share
   disconnected and after reboot. Verify normal file operations inside a
   permitted mounted share still work. Check `getfacl` on the export root has
   no inherited named access/default grants; test initial ACL cleanup using
   disposable directories only.
4. In an **enforcing** AppArmor session, try every menu action, including both
   successful and denied/cancelled authorization, missing journal access,
   empty/unavailable/stale client records, and report-service failure. Inspect
   AppArmor denials and service results; do not switch to complain to claim a
   pass. Check runtime report owner/group/mode and resource limits.
5. Stop/fail the managed firewall service and confirm server teardown, then
   restore/check it deliberately. Verify existing firewall managers, ordinary
   networking, labwc lifecycle, and Zoom/Discord private-only Xwayland behavior
   have not regressed. Record actual package/kernel/systemd versions and
   acceptance evidence with the release.

## Primary technical references

These upstream/Debian references explain the semantics used by the code; their
presence is not evidence of target runtime acceptance:

* Debian `exports(5)`: https://manpages.debian.org/testing/nfs-kernel-server/exports.5.en.html
* Debian `nfs.conf(5)`: https://manpages.debian.org/testing/nfs-common/nfs.conf.5.en.html
* Debian `nfs.systemd(7)`: https://manpages.debian.org/testing/nfs-common/nfs.systemd.7.en.html
* Debian `nfsidmap(8)`: https://manpages.debian.org/testing/nfs-common/nfsidmap.8.en.html
* Debian `rpc.mountd(8)`: https://manpages.debian.org/testing/nfs-kernel-server/rpc.mountd.8.en.html
* Debian `rpc.nfsd(8)`: https://manpages.debian.org/testing/nfs-kernel-server/rpc.nfsd.8.en.html
* Debian Forky nfs-common file list: https://packages.debian.org/forky/amd64/nfs-common/filelist
* systemd `systemd.mount(5)`: https://www.freedesktop.org/software/systemd/man/latest/systemd.mount.html
* Linux IP sysctl documentation: https://docs.kernel.org/networking/ip-sysctl.html
* e2fsprogs `chattr(1)`: https://man7.org/linux/man-pages/man1/chattr.1.html
* ACL project `setfacl(1)`: https://man7.org/linux/man-pages/man1/setfacl.1.html
* systemd fstab generator: https://www.freedesktop.org/software/systemd/man/latest/systemd-fstab-generator.html
* nfs-utils server unit: https://github.com/linux-nfs/nfs-utils/blob/master/systemd/nfs-server.service
* nfs-utils mountd protocol handling: https://github.com/linux-nfs/nfs-utils/blob/master/utils/mountd/mountd.c
* nfs-utils kernel cache handling: https://github.com/linux-nfs/nfs-utils/blob/master/support/export/cache.c
* Python `subprocess` process/session and timeout semantics: https://docs.python.org/3/library/subprocess.html
