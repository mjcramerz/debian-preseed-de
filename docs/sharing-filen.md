# Shared desktop storage and Filen CLI

## Current installation contract

This is the configuration-format-3 implementation for new Debian Forky / systemd
262 installations. It replaces the separate NFS server/client home bind mounts.
Existing installations with a saved format-2 profile are rejected by the offline
configurator; changing only their version number is not a migration.

The installer creates these fstab records, using the selected account and paths:

```fstab
/data/sharing /data/sharing none bind,shared,nosuid,nodev,noexec 0 0
/data/sharing /home/ACCOUNT/Sharing none rbind,rslave,nosuid,nodev,noexec,x-systemd.requires-mounts-for=/data/sharing 0 0
```

The first bind makes `/data/sharing` a distinct mount point and marks it shared.
The recursive home bind receives existing and future mounts and unmounts below
that source. Its slave propagation prevents mounts made through the home view
from propagating back into the source tree. Both records mount at boot, including
when both NFS roles are disabled. Other future submounts also appear in the view.
These are mounts managed by PID 1 in the system mount namespace.

`NETWORK_SHARING_ROOT_PATH` and `NETWORK_SHARING_HOME_BIND_PATH` are explicit in
every host profile; their defaults are `/data/sharing` and `Sharing`. The home
destination is one visible directory below `ACCOUNT_HOME`. It is root-owned,
empty before mounting and protected with the existing immutable-directory
mechanism. The installer rejects symlinks, pre-existing user-owned destinations
and conflicting unmanaged fstab records. It does not recursively change user
data. The desktop package set includes `e2fsprogs` for `chattr`.

## NFS and nfsmnt

`NFS_SERVER_ENABLE` and `NFS_CLIENT_ENABLE` retain their profile choices:

- `btrfs-de-p15s.env` enables the server.
- `btrfs-de-flex-duo.env` enables the client, using `192.168.50.82:/`.
- The other profiles keep both NFS roles disabled.

The server stores and exports only its configured `NFS_SERVER_PATH`, normally
`/data/sharing/nfs-server`. The client mounts only its configured
`NFS_CLIENT_PATH`, normally `/data/sharing/nfs-client`. Their home paths are
ordinary locations in the propagated view; they have no separate mount units.
The old `NFS_*_BIND_ENABLE`, `NFS_*_HOME_BIND_PATH` and
`NFS_MNT_*_BIND_HOME_OPTS` settings are retired.

Run `nfsmnt` as the configured desktop account. It validates the source fstab
record and systemd mount properties, probes the numeric server's TCP port with
a three-second timeout, then submits **one** `systemctl start` for the source
NFS mount. The existing active-local administrator Polkit rule authenticates
that operation. There is no second home-bind authorization and no cached or
passwordless authorization rule. Cancellation or a failed/skipped mount returns
failure. The source must report active/mounted before success is printed.

The NFS source remains `noauto`, TCP-only, hard-mounted, `sec=sys`, and protected
by the existing firewall, identity-service, `nosuid,nodev,noexec`, and mount-job
timeout policy. Its generated dependencies include the shared root and home
view, establishing startup order **root -> home view -> NFS client**. Shutdown
uses the reverse dependency order. The power coordinator validates format 3 and
queues only those owned mount units. The mounted source's read-only policy also
governs its propagated home view. It does not make unrelated shared storage
read-only. No autofs, idle unmount, forced unmount or new mount helper is added.

The existing UID/GID, NFSv4 mapping, export CIDRs, root squashing, server ACLs,
firewall, and port settings remain in effect. TCP reachability is not export
authorization; hard NFS I/O can still block during a server outage. The earlier
[NFS policy background](network-sharing.md) and its linked validation records
describe the unchanged protocol policy and historical implementations.
The configured NFS numeric UID/GID agreement is required only when an NFS role
is enabled. With both roles disabled, the shared home view uses the existing
desktop identity and still validates its home and unique UID mapping.

## Filen profile settings

Filen installation runs only in the selected desktop role. Every host profile
contains the following non-secret controls:

| Setting | Shipped value / purpose |
| --- | --- |
| `FILEN_CLI_VERSION` | `0.0.36`, the upstream stable TypeScript/Bun CLI release providing continuous sync. |
| `FILEN_CLI_ARCHITECTURE` | `amd64`; must equal the target dpkg architecture. |
| `FILEN_CLI_URL` | Explicit versioned upstream Linux x64 release asset. |
| `FILEN_CLI_SHA256` | `be690d94d3310187dc7b4fe46b3e49becfb327c29ac64d49cfe73252c7c3c04a`. |
| `FILEN_CLI_MAXIMUM_BYTES` | `201326592`; maximum downloaded bytes. |
| `FILEN_CLI_PRIV_ENABLE` | `true`; install/configure the private account. |
| `FILEN_CLI_OFFSEC_ENABLE` | `true`; install/configure the offsec account independently. |
| `FILEN_CLI_PRIV_SYNC_MODE` | `twoWay`. |
| `FILEN_CLI_OFFSEC_SYNC_MODE` | `twoWay`. |
| `FILEN_CLI_PRIV_REMOTE_PATH` | `/`; existing remote directory for this account. |
| `FILEN_CLI_OFFSEC_REMOTE_PATH` | `/`; existing remote directory for this account. |

Both accounts can run together. Setting one enable flag to `false` omits that
account's service identity, directory, credentials, policy and bookmark on a new
installation. Both `false` skips CLI installation. These switches are installer
selection, not a live account-removal tool. Version, architecture, asset URL and
SHA-256 form one pin and must be updated together. The installer supports the
published amd64 or arm64 asset format; each configured URL and hash must match
its architecture. There are no source builds or automatic CLI updates.

The upstream [release assets](https://github.com/FilenCloudDienste/filen-cli/releases/expanded_assets/v0.0.36)
publish the pinned hash. The installer checks HTTPS and each redirect origin
before requesting it, bounds hops, time and bytes, checks SHA-256 and ELF
architecture, then atomically installs root-owned `/usr/local/bin/filen`.
Download data arriving after the 300-second download deadline is rejected;
individual reads have at most a 15-second socket timeout, and the complete
target installer has a separate 420-second timeout with five-second kill
escalation. New public code/configuration directories receive explicit
mode 0755 even under the installer's private umask. Before any offline service
enablement, the installed wrapper is compiled as every enabled service UID with
its primary GID and no supplementary groups. This catches inaccessible module
parents that a root-only compilation would conceal.
The hash establishes consistency with the selected publisher release bytes;
this workflow does not claim a vendor signature. `cli.sh` is not executed or
used as installation policy.

The supported [sync modes](https://docs.filen.io/docs/cli/syncing/) are:

| Mode | Direction and deletion behavior |
| --- | --- |
| `twoWay` | Propagates changes, moves and deletions in both directions. |
| `localToCloud` | Applies local changes and deletions to cloud storage. |
| `cloudToLocal` | Applies cloud changes and deletions locally. |
| `localBackup` | Uploads local changes without propagating local deletions. |
| `cloudBackup` | Downloads cloud changes without propagating cloud deletions. |

The selected remote directory must already exist. The wrapper recognizes the
CLI's missing-directory error and returns failure instead of leaving an empty
sync set running. JSON sync registries keep spaces, Unicode and colons in
remote paths out of the CLI's literal-pair parser.

## Credentials and account isolation

The protected d-i `/preseed.env` input supplies exactly these six mapped names:

```text
PRESEED_FILEN_PRIV_EMAIL
PRESEED_FILEN_PRIV_PASSWORD
PRESEED_FILEN_PRIV_2FA_SEED
PRESEED_FILEN_OFFSEC_EMAIL
PRESEED_FILEN_OFFSEC_PASSWORD
PRESEED_FILEN_OFFSEC_2FA_SEED
```

The existing protected credential reader checks the source file. Enabled
accounts require nonempty single-line values. The reader preserves UTF-8 and
literal punctuation without shell re-evaluation; TOTP seeds must decode as
base32 before installation continues. Secrets go
through a private target staging directory, then root-only mode-0600 files in
mode-0700 `/etc/credstore/filen-private` and `/etc/credstore/filen-offsec`.
Staging is removed on exit. Secrets are not profile/template values or payload
inputs and are not arguments to `env`, Perl, Filen or `oathtool`.

PID 1 supplies each service only its own read-only credentials through
`LoadCredential`. The Moo/MooX Perl daemon waits at most 180 seconds per attempt
for the packaged timesyncd synchronization marker, generates a fresh six-digit
SHA1 TOTP through `oathtool` with the seed on stdin, and passes the email,
password and current code only in its dedicated UID's Filen child environment.
This uses the pinned CLI's documented [environment authentication](https://github.com/FilenCloudDienste/filen-cli/blob/v0.0.36/src/app/auth.ts).
The parent does not retain those values in its environment or print upstream
output, credentials or filenames. The supervisor and CLI share their account's
UID and AppArmor profile, so both can read that account's service credential
view. The isolation boundary is between accounts and the desktop UID; the seed
is omitted from the CLI environment, rather than made inaccessible to its UID.

| Account | System service / UID | Local tree | Private state |
| --- | --- | --- | --- |
| Private | `filen-sync@private.service` / `filen-private` | `/data/sharing/filen-private` | `/var/lib/filen-private` |
| Offsec | `filen-sync@offsec.service` / `filen-offsec` | `/data/sharing/filen-offsec` | `/var/lib/filen-offsec` |

Each non-login service UID owns only its own tree. Named default ACL entries
grant both that service UID and the configured desktop UID access, including
children created by either account. Neither
daemon receives membership in the other's group. Root-owned configuration,
sync registries and Perl modules stay outside these writable trees. Separate
named AppArmor profiles, private temporary/device views, protected home and
system filesystems, empty capability sets, namespace restrictions, disabled
core dumps and narrow writable paths constrain the services.

The Perl process remains the supervisor of the continuous CLI child. Its
startup observation is bounded to 180 seconds; it emits only fixed event
categories. Error classification uses complete messages from the pinned CLI,
including its exact ANSI error wrapper. Error words inside valid remote paths
do not become authentication failures. After output EOF the supervisor checks
worker state once per second. PID 1 retains the whole cgroup and supplies bounded
stop/escalation.
Unexpected worker exits retry with systemd's capped 60-second-to-15-minute
backoff; invalid configuration (78) and outcome-unknown (79) do not retry
automatically. The CLI uses its own independent sync database and
`--skip-update`; repeated logins do not share a desktop Secret Service.

GTK bookmarks for `Sharing`, enabled NFS locations and enabled Filen trees are
written into the desktop skeleton before its existing copy to the account's
GTK configuration. Filen bookmarks use `~/Sharing/filen-private` and
`~/Sharing/filen-offsec`, which expose the actual directories through the bind.
The shared document AppArmor abstraction grants data access to these two Filen
trees through both paths, including files owned by the service UID. It grants
no executable permission or access to service credentials and state.

## Acceptance boundary

The source changes and pure payload generation do not establish native runtime
acceptance. Follow [test-isolation.md](test-isolation.md): execute fixtures and
native checks only in an explicitly prepared disposable Forky environment with
its own kernel/state and no host shares, devices, managers or sockets.

Required gates include the focused netkit/NFS/shutdown/Filen fixtures, packaged
Perl and native CLI startup, AppArmor enforcement and loaded mode reconciliation,
fstab generation and actual mount/unmount propagation, one client authorization,
both accounts running concurrently, TOTP login, credential/error-log redaction,
network loss/recovery, long-running memory behavior, bounded cgroup termination,
and a fresh unattended install through firstboot. Retain native application and
private Zoom/Discord regression checks. No Xwayland implementation or eligibility
changes are part of this work.

The current review findings, serialized source fingerprint and remaining gates
are recorded in [the follow-up evidence](validation/sharing-filen-review-20261017.md).
