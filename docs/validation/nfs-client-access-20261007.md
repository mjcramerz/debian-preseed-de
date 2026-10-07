# NFS client access and automatic mounting — 2026-10-07

## Request and observed causes

The client must permit ordinary-user navigation, connect through its managed
NFS source and home bind, and use no `noauto` client mount options. This repair
is limited to the shared client policy, installer directory modes, menu retry
behavior, their existing tests and documentation. It preserves Debian binary
packages, server access restrictions and private Zoom/Discord Xwayland.

Three repository causes were reproduced before changing production sources:

1. Both client fstab option strings contained `noauto`, and the shared target
   validator required that flag. Neither mount received a boot target link.
2. The remote client mountpoint and unmounted home client endpoint were created
   mode 000. An ordinary account could not navigate them when no mount existed.
3. Connect returned before requesting any mount job when the invoking login
   lacked the shared supplementary GID, even though the managed account
   database and mount authorization have their own checks.

The supplied October 7 LPL-697 log shows modules `nfs`/`nfsv4` loading and
`nfs-client.target` becoming active. It contains no source/home mount job or
NFS server rejection. That target prepares support services; its active state
does not establish an NFS mount. The `nfsrahead` non-NFS-device messages do not
provide evidence that the configured share connected.

Four selected regression methods failed against the old sources, with six
failing subcases covering both option strings, default/custom home endpoints,
native mount generation and the stale-login retry.

## Implemented contracts

| Contract | Source and resulting behavior |
| --- | --- |
| Automatic client mounting | `hosts/installer/hosting.env` uses `auto` on both client entries. `Settings.from_environment()` requires it and rejects `noauto`. All ten profiles use this shared policy. Enabled roles and server addresses remain profile-controlled. |
| Source before home bind | The home bind retains `x-systemd.requires-mounts-for=` for the actual configured source and its `BindsTo=`/`After=` drop-in. The NFS source retains client-target, managed firewall and identity-check requirements. |
| Safe disconnected navigation | The installer creates both client endpoints root:root mode 0755, empty. Ordinary users may list/enter them, with no group/other local write bit. Server data ownership, mode 2770, ACLs and root squashing remain authoritative once mounted. |
| Authorized retry | Connect submits the source job, waits for success, then submits the home bind. Stale process group membership no longer suppresses the mount request. Normal active-local administrator authorization and the managed identity prerequisite still apply. |
| Safe disconnect | Home bind stops before source; a failed/busy home stop prevents a source stop. No forced/lazy unmount is added. |
| Existing consumers | Saved configuration remains format 2 and diagnostics remain format 1. Identity/report helpers and the power worker continue using the same validated mount names. No automount metadata or trigger is added. |

There is no new resident process, retry timer, autofs layer or source
compilation. `nofail` keeps the share from being required for boot; the configured
initial mount command timeout remains. If the server is absent at boot, the
client endpoints remain readable and empty; Connect retries when it becomes
available. Established `hard` mounts can still block application I/O during
an outage. This repair cannot make an unavailable server accessible.

Systemd v261 documents automatic target dependencies for `auto`, their omission
for `noauto`, and the absolute-path source requirement used by the bind.
See the [versioned upstream mount documentation](https://github.com/systemd/systemd/blob/v261/man/systemd.mount.xml)
and [unit dependency documentation](https://github.com/systemd/systemd/blob/v261/man/systemd.unit.xml).

## Validation performed

All commands below were run from the repository root. No live mount, export,
firewall load, kernel-module load, service start or package installation was
performed.

| Check | Observed result |
| --- | --- |
| Selected regression methods before/after the source fix | Before: four methods, six failing subcases. After: all four methods passed without skips. |
| `timeout --signal=TERM --kill-after=5s 180s python3 -B -m unittest discover -s d-i/forky/tests -p test_network_sharing.py -v` | 135 methods in 4.334 seconds; 114 passed, 21 root-only private filesystem methods skipped. |
| `python3 -B tools/check_network_sharing.py` | All ten profiles validated with the target configurator's policy. |
| Final menu format/rejection test (`-k load_config_rejects_legacy`) | One method passed after the final error-message clarification. |
| AST parsing of all three changed Python files | Passed, with no bytecode writes. |
| `python3 -B tools/build.py` | Built 1,704 payload files; updated payload, manifest and preseed pins. |
| `python3 -B tools/build.py --check` | Snapshot, pins and preseed current. |
| `python3 -B tools/check_shells.py` | 350 shell files, 711 parser checks passed. |
| `python3 -B tools/check_preseeds.py` | 59 preseed files passed; all four generated command values survived private debconf read-back unchanged. |
| Payload member comparison with a private pre-task inventory | Exactly the three intended NFS payload members changed. Every other member and all archive modes/link targets were preserved. |
| `git diff --check` | Passed. |

The native fstab generator read a private fixture, producing real source and
home `.mount` files and both `remote-fs.target.wants` links, with `auto`, no
`noauto`, the 30-second source timeout, the correct source requirement and the
identity/firewall/client-target dependencies. No `.automount` or `.path` unit
was generated. The server home bind retained its local filesystem target link.

The ordinary-user navigation fixture exercised actual chmod, directory listing
and cd under umask 0077 for both default and nested custom home paths. Only
trusted-parent/root-ownership operations were simulated; this fixture is not
evidence that root-owned target installation was executed. The 21 skipped
methods cover that separate private root-owned filesystem boundary.

The executed suite also validates native AppArmor parsing/effective document
path permissions, native NFS configuration reading, profile/firewall policy,
ordered menu failure handling and identity/helper confinement. Those are
offline parses or controlled/mocked fixtures, not running-daemon or enforcing
desktop acceptance. Existing EncodingWarning messages remain in unmodified
helpers/tests and did not fail these checks. The broad repository suite was
not rerun or declared passing.

Validation host: Debian forky/sid, Python runtime 3.14.8, systemd package 262-1,
nfs-common 1:3.1.1-1, AppArmor 4.1.8-2, util-linux 2.42.4-1. The requested
deployment target remains Forky/systemd 261.2; versioned upstream semantics
were checked, but that exact target was not booted here.

Payload SHA-256 after rebuilding:
`d1b2a27da4b4a40ce1571f6d07d4b9790421206456c4f8b5b672de3e43761ac4`.

## Installed-client application and remaining acceptance

LPL-697's existing fstab, root-owned directory modes and menu helper are not
changed by a repository rebuild. Follow the [format-2 client repair procedure](../network-sharing.md#existing-format-2-client-using-noauto-and-mode-000-endpoints)
to stop home/source mounts in order, confirm they are unmounted, update only
the two client endpoints/options and the saved policy/helper, reload PID 1 and
reconnect. Preserve protected home parents and server data; do not chmod a
mounted export or defeat the changed-profile guard. Older autofs clients have
a separate documented cleanup procedure.

On actual client/server hosts, confirm both active mount-table entries use the
same NFS source, ordinary desktop-user read/write behavior matches the export,
initially unavailable-server behavior is understood, and reboot reconnects.
If a submitted mount actually reports access denied, verify the client's real
source IP against the server allowlist and inspect identity/ACL/AppArmor
diagnostics. The supplied excerpt does not establish any of those as a current
server-side cause. No relaxed export, firewall or AppArmor policy is provided
as a workaround.
