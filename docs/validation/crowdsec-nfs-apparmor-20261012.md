# CrowdSec and NFS AppArmor incident review — 2026-10-12

## Initial capture and failure correlation

Read all files in the initial `todo/` capture: 49 files, 3,569,064 bytes and 22,656 lines.
Twenty-three files are empty; this does not establish scanner or service success.
There are ten distinct denied audit events, representing six request signatures.
Repeated records across audit, kernel and AppArmor logs are the same incidents.
No credentials, authentication conversations or full execution arguments are
reproduced here.

| Captured request | Cause and source correction |
| --- | --- |
| crowdsec-firstboot: capability dac_read_search | Add the specific capability already requested by the confined root helper. Existing file mediation remains in force. |
| crowdsec-firstboot: create /tmp/checkfsfile3728739017 | Coraza's filesystem check creates and removes a random probe. Add owner-only rw for /tmp/checkfsfile[0-9]*, with no broad /tmp write grant. |
| network-sharing//systemctl: read /proc/sys/fs/nr_open, by both forked agents | systemd's agent-fork preparation inspects the file-descriptor ceiling. Add read permission at this exact sysctl path. |
| network-sharing//systemctl: execute systemd-tty-ask-password-agent | Permit inherited execution inside the existing unprivileged child profile; cover its request files, reply sockets and TTY lifecycle. |
| network-sharing//systemctl: execute pkttyagent | Permit inherited execution; cover PolicyKit D-Bus registration/callbacks and Polkit 127's agent-helper socket. No privileged helper execution or additional capability is granted to this profile. |

`todo/managed/security/crowdsec/crowdsec.log:434` records the fatal AppSec
filesystem check. `todo/journalctl:1200` records the config-test failure, followed
by bootstrap failure and engine shutdown. The helper correctly refuses to mark
the unfinished bootstrap complete. Policy failure blocked that validation before
the restart/bouncer/CAPI sequence could finish. The existing owned-acquisition
rollback is retained.

`todo/nfs` reports the two denied agent executions for each mount.
`todo/journalctl` records the primary desktop agent authenticating the requests,
the identity check completing, the source mount succeeding and the home bind
succeeding. The terminal capture also ends with both mounts reported mounted.
The observed defect is the missing fallback-agent policy; this capture does not
show a failed NFS source mount or a failed home bind.

## Dependency review

systemd 262 checks for a controlling terminal before forking its password and
Polkit agents, even if the wrapper captures output and supplies `/dev/null` as
stdin. The children reopen `/dev/tty`; systemctl terminates and reaps them at
completion. The policy therefore includes same-profile signal permissions for
cleanup and Polkit's terminal signal restoration. The primary desktop agent is
preserved and pkttyagent remains a fallback. Password replies use UNIX datagram
sockets; that socket type is allowed alongside the existing UNIX streams.
[systemd 262 agent fork implementation](https://github.com/systemd/systemd/blob/v262/src/shared/exec-util.c),
[Polkit-agent launch](https://github.com/systemd/systemd/blob/v262/src/shared/polkit-agent.c).

Polkit 127 uses `/run/polkit/agent-helper.socket` to delegate PAM to its
socket-activated service. The child receives only that socket path and the
PolicyKit registration/conversation interfaces. No pkexec, setuid helper,
mount executable or unrestricted executable transition is added.
[Polkit 127 authentication session](https://github.com/polkit-org/polkit/blob/127/src/polkitagent/polkitagentsession.c).

CrowdSec 1.8.1's upstream dependency manifest selects Coraza 3.7.0. Its
`IsDirWritable` implementation uses `CreateTemp(dir, "checkfsfile")`, then closes
and removes the file. The supplied denial matches this packaged runtime probe.
No build flag or source compilation is introduced.
[CrowdSec dependency manifest](https://github.com/crowdsecurity/crowdsec/blob/v1.8.1/go.mod),
[Coraza filesystem probe](https://github.com/corazawaf/coraza/blob/v3.7.0/internal/environment/default.go).

## Installation ownership and regression coverage

- `scripts/late/core.sh` stages the firstboot policy to `/etc/apparmor.d/firstboot`;
  the existing logging renderer resolves its LOG tokens.
- `scripts/late/security.sh` includes network-sharing in the managed profile
  inventory and stages the canonical policy. Existing mode enforcement and
  service dependency gates are retained.
- Existing gated incident tests now cover the observed file/capability grants,
  inherited agent execution, socket/request paths and signal dependencies.
  Native FileRule assertions include unrelated-path, write and owner boundary
  rejection cases. No test reads `todo/` as a runtime fixture.
- Production Xwayland policy and runtime code are unchanged.

## Verification boundary and remaining evidence

Source and supplied logs were inspected as data; changed Python tests were
AST-parsed and whitespace was checked. No tests, discovery, repository validation
runner, AppArmor parser/load, service action, mount or package operation ran on
the development host. No disposable test environment was available, so the new
regressions and kernel enforcement have not been exercised.

The supplied logs also contain USB-C UCSI driver errors. They do not identify a
repository configuration defect or establish an appropriate driver/firmware fix.
The compositor's missing generic Xwayland message is consistent with the
existing private-only Zoom/Discord policy and is left unchanged. The initial
CrowdSec CAPI-disabled and absent qBittorrent-log messages occur before the
bootstrap/application setup completes. No additional AppArmor denial signature
was found in the supplied capture.

Rebuilding the publication files changes the installer snapshot. It does not
load new policy or restart CrowdSec on the already-installed captured machine.
Live installed-target verification remains outstanding after controlled policy
deployment.

Final generation command: `make build PYTHON=/usr/bin/python3`, exit status 0,
1,744 payload files. A before/after metadata inventory found exactly
`d-i/forky/payload.tar.gz`, `payload.manifest` and `preseed.cfg` changed during
generation. Data-only archive inspection matched every member to current
source and its manifest hash, checked deterministic archive metadata and
confirmed both preseed pins. The archive contains both corrected policies.

## Follow-up: fatal network-sharing signal parser error

The next installation reported `unknown signal "tstp"` in network-sharing.
The added lifecycle rule used the newer upstream alias rather than the signal
name accepted by the packaged parser. The previous data-only grant assertions
copied that spelling and did not establish parser compatibility.

The policy now uses `stp` for SIGTSTP. The send/receive permissions and exact
`labwc-network-sharing//systemctl` peer remain the same. `stop` is a different
signal and is not substituted. Both AppArmor v4.1.0's parser mapping and Debian's
packaged policy grammar specify `stp`; newer upstream master also accepts `tstp`.
[AppArmor v4.1.0 signal mapping](https://gitlab.com/apparmor/apparmor/-/blob/v4.1.0/parser/signal.cc),
[Debian AppArmor policy grammar](https://manpages.debian.org/unstable/apparmor/apparmor.d.5.en.html).

The existing gated incident module now checks every explicit signal set in the
canonical target policies, abstractions, local fragments and firstboot policy
against this compatible signal vocabulary, including bounded realtime names.
The dependency assertion also expects the corrected `stp` spelling. These
regressions have not been executed on the development host.

Data-only inspection covered 98 production policy/fragment files: 294 signal
rules, 182 explicit sets and 17 distinct signal names. Every name is accepted by
the compatibility vocabulary; no other unsupported signal spelling was found.
The changed test module was AST-parsed without importing it, and the isolation
gate remains before runtime fixture imports. Native parser and installed-target
checks remain unexecuted.

After this correction, `make build PYTHON=/usr/bin/python3` completed with exit
status 0 and 1,744 payload files. The generation metadata comparison again found
only the three permitted products changed. Every archive member matches current
source bytes and its manifest hash; deterministic metadata and preseed pins
match. The packaged network-sharing policy contains `stp` and no `tstp` token.

## Latest capture: LPL-953, 23:36–23:43 CEST

The user replaced `todo/` with a new capture. Read every regular file as data:
94 files, 9,500,059 bytes, 47,704 physical lines, including 22 empty files. Some
audit records contain an ASCII group separator before the UID annotations;
Python `splitlines()` treats that character as another line. References and
line totals in this section count actual LF separators instead.

The supplied target reports systemd 262-1 and kernel 7.2.10-x64v3-xanmod1.
The primary AppArmor log contains 1,197 events: 426 STATUS events and 771 DENIED
events. The STATUS records consist of two AppArmor initialization notices, 417
profile loads and seven replacements; they are not failed requests. Denials
have 257 distinct exact requests and reduce to three dependency classes:

| Denied dependency | Events / distinct requests | Source correction |
| --- | --- | --- |
| desktop-launcher: nmtui reads /run/udev/data/n&lt;ifindex&gt; | 765 / 255 | Read only /run/udev/data/n[0-9]* in the existing launcher profile; no writes or block-device records. |
| network-sharing//systemctl: password agent creates /run/user/1000/systemd/ask-password/ | 1 / 1 | Owner-only rw on the request directory, while ask.* files remain read only and sck.* replies retain write-only access. |
| network-sharing//systemctl: pkttyagent reads /proc/12317/fdinfo/3 | 5 / 1 | Owner-only read access to numeric fdinfo entries under the existing PROC/pid tunables. No process-memory or fdinfo write grant. |

Evidence starts at `todo/managed/security/apparmor/apparmor.log:427` for nmtui,
`:1192` for the directory creation and `:1193` for fdinfo. No other denial
profile, request mask or operation appears in this capture. The primary log's
SHA-256 is `fb3280aecb8995553efe15875ed45c67a53e5836db259df75352c5fccf5fc04e`.

`todo/nfsmnt:4` reports the failed password-directory watch. Lines 6–7 report
Polkit's caller-PID assertion, and line 8 reports a denied source mount. This
capture does show a failed NFS attempt. systemd 262 calls mkdir before installing
the user watch; Polkit 127 reads its own pidfd's fdinfo to resolve the caller PID
before validating its invariants. Both operations were blocked by the policy.
Existing owner stat/cgroup reads, agent execution, TTY, socket, D-Bus and cleanup
signal permissions remain in the child profile. The compatible `stp` spelling
is retained. No direct privileged mount command or authentication bypass is
introduced.
[systemd 262 password watcher](https://github.com/systemd/systemd/blob/v262/src/tty-ask-password-agent/tty-ask-password-agent.c),
[Polkit 127 process identity](https://github.com/polkit-org/polkit/blob/127/src/polkit/polkitunixprocess.c),
[Polkit caller invariants](https://github.com/polkit-org/polkit/blob/127/src/programs/pkttyagent.c).

`todo/journalctl:1593` also records failed authentication through the desktop
agent. Its cause is not established by the log: there is no evidence that
credentials were correct or that the prompt completed successfully. Repairing
the broken fallback agent does not establish a successful authorization, remote
export mount or home bind. The active/local/sudo authorization boundary and
source-before-bind ordering are preserved.

### Accounting for other audit failures

Read all four rotated audit files. Their 901 failed syscall records include the
same 771 AppArmor denials. The other 130 comprise 46 ENOENT executable searches,
80 ENOENT cleanup unlink attempts and four ENOTEMPTY directory-removal attempts.
The executable paths are unsuccessful PATH candidates for bwrap, nmtui, sh,
vdirsyncer, systemctl and dbus-update-activation-environment. These records alone
do not establish a failed final executable lookup. Native startup logs show
the relevant desktop services and programs running. No missing executable or
absent cleanup path is granted additional privilege to suppress audit records.

### Other log findings and disposition

- CrowdSec bootstrap now completes: `todo/journalctl:1407` records completed
  CAPI registration, `:1409` pending Console approval and `:1411` status=pass.
  The native bouncer log records nftables initialization. The Console-sync
  errors at crowdsec.log:821 and :845 occur before/during enrollment pending
  external approval; no token or approval action is manufactured.
- The qBittorrent logfile warning occurs before application launch. The staged
  acquisition polls its exact log path every ten seconds, and the launcher
  binds the persistent profile to /home/user, matching FileLogger's path.
- Installer download logging exposed signed redirect query strings. The
  downloader now logs only effective_host after removing userinfo, paths,
  queries and fragments. URL validation errors no longer print the rejected
  URL. The real transport URL and host validation remain unchanged. Existing
  captured logs are not rewritten.
- `todo/managed/apps/apps.log:172` onward has ten GTK accelerator-group
  assertions immediately after qBittorrent starts. All five canonical native
  menus already declare GtkAccelGroup and reference it on their nested menus.
  A similar assertion is reported for dynamically populated application trays
  in upstream Waybar issue 5224. This is a possible source, not a confirmed root
  cause of this machine's warning. No tray removal, source compilation, new
  library shim or log suppression is introduced.
  [Upstream GTK/tray report](https://github.com/Alexays/Waybar/issues/5224).
- Three eDP-1 DRM EBUSY atomic-commit failures occur at apps.log:136, :147 and
  :168. The capture does not show a compositor crash or identify a safe renderer,
  kernel or firmware correction. They remain unresolved; no generic legacy-KMS
  workaround or graphics-policy change is asserted to fix this hardware.
- UCSI errors, the firmware's I2C speed correction and the SPI dummy-regulator
  warning appear in firstboot/data/dmesg-warnings.txt:6–19. The capture does not
  establish a repository fix. A single tailscale0 martian-source message is at
  :34; later Tailscale setup and DERP connectivity succeed. No global routing
  protection is relaxed from that one record.
- AppArmor reload warnings from Mullvad and Zoom are package-maintainer actions
  inside the installation chroot. At boot, the captured loaded-mode check
  passes and all profile load/replacement records have STATUS, not DENIED.
- The snapshot's systemd-analyze status=1 says boot had not finished. status=3
  for target reports includes a pending multi-user target. The security status=4
  report queries absent ssh/sshd units on this client-only installation. The
  separate failed-unit listing is empty. These diagnostic exit codes do not
  establish failed installed services.
- Initial Bluetooth identity-file and Tailscale state warnings are first-start
  records. Fail2ban's new-database message and netavark's inactivity exit are
  initialization/lifecycle messages. Empty scanner logs provide no scan result.
- Generic Xwayland remains absent as required; private Zoom/Discord policy is
  unchanged.

### Installation wiring and regression evidence

The existing system profile inventory stages network-sharing to
/etc/apparmor.d/network-sharing as 0644. The existing desktop inventory stages
desktop-utilities through the same managed-mode flow. No new staging route or
mode override is needed. software.sh.tmpl remains the canonical late-stage
downloader source.

The isolated incident fixture records every one of the 257 exact file requests,
with counts accounting for all 771 denials. Native FileRule regression assertions
cover the observed reads and directory creation, and reject writes, unrelated
paths and incorrect owners. An existing isolated external-software test module
now exercises synthetic signed/query/userinfo/fragment URLs and verifies that
logging leaves the transport URL unchanged. These tests have not been run.

Only static source/log inspection, Python AST parsing and artifact generation
are permitted in this checkout. No native parser, tests, validators, policy
loads, systemd/D-Bus actions, mounts or package operations were executed.
Native policy acceptance and the actual installed NFS authorization/mount
remain unverified. The GTK/DRM/firmware findings above remain explicitly open.

Latest generation: `make build PYTHON=/usr/bin/python3`, exit status 0, 1,744
payload files. A fresh before/after metadata inventory found exactly the three
permitted products changed during generation. All archive members match current
source bytes and manifest hashes; deterministic metadata and archive/manifest/
bootstrap preseed pins match. The packaged policies contain all three latest
grants and the compatible signal spelling. The packaged downloader logs only
effective_host. Tests, the redacted incident fixture and todo logs are excluded
from the published installer archive. No generated product is stale after these
source changes.

### Waybar network button permissions

Both Waybar layouts launch `labwc-terminal -e nmtui` on left click. The terminal
attaches to desktop-launcher, where the network-device udev read grant above
applies. NetworkManager 1.58.1 is recorded in todo/journalctl:366. The existing
desktop-launcher profile now permits system-bus messages only to NetworkManager
within its object namespace, plus its ObjectManager interface at
`/org/freedesktop`. This covers activation, deactivation, radio controls,
connection editing, device notifications and SecretAgent password callbacks.
The bus-daemon grants cover NameOwnerChanged notifications and the
GetConnectionUnixUser query that libnm requires before registering a password
agent. The standard dbus-strict abstraction supplies bus connection and name
lookup operations.

The root enumeration and daemon-identity query are confirmed in the matching
[libnm 1.58.1 client](https://github.com/NetworkManager/NetworkManager/blob/1.58.1/src/libnm-client-impl/nm-client.c)
and [secret agent](https://github.com/NetworkManager/NetworkManager/blob/1.58.1/src/libnm-client-impl/nm-secret-agent-old.c)
sources. NetworkManager's existing active-local/admin Polkit policy continues to
authorize changes. The right-click menu keeps its existing nmcli transitions and
fixed-purpose privileged helpers.

The guarded incident module adds synthetic D-Bus requests for discovery,
activation, editing, radio changes and password callbacks, with negative peer,
bus and path cases. These assertions have not been executed. Native parser
acceptance and an actual installed Wi-Fi connection remain unverified; no host
policy, services or networking were changed.

After the network-policy change, generation completed with exit status 0 and
1,744 payload files. A before/after inventory of 2,357 repository files found
only the three permitted products changed during the build. Every archive
member matches its current source bytes and manifest hash, with unique paths
and deterministic metadata; the three preseed hash pins match. The native rule
regression method parses as Python data and its fixture imports remain behind
the isolation gate. The changed source/test/artifact whitespace inspection is
clean. These are static inspections and generation results, not executed tests.
