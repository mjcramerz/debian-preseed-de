# Persistent local APT policies and Labwc power handoff

Date: 2026-09-12. This report describes only the changes made to the supplied
`debian-preseed-de.zip` for the four requested objectives. Earlier reports and
validation records elsewhere in this repository are retained as historical
material, not new test results.

## Delivered scope

The global `94-local-apt-vendor-policy` dpkg pre/post-invoke hook is removed.
Package transformation now belongs to the local repository publisher, before a
package can enter the signed published index. The public command is
`local-apt-init`; the old `apt-local-repo` executable is no longer shipped.
All active APT source inputs are normalized into vendor-named deb822 files.
Power and logout use authenticated, UID-scoped preparation followed by a
PID-1-owned worker, while suspend preserves the running desktop.

The complete source tree, regenerated payload archive, payload manifest and
preseed pins are supplied together. No application, kernel, compositor,
wlroots, or other software was compiled. `tools/build.py` serializes deployment
archives and checksums; it is not a software compiler. Package fixtures and
repacked `.deb` archives were likewise assembled without executing upstream
maintainer scripts or compiling their contents.

## 1. Package policies before repository publication

`usr/local/libexec/local-apt-repository` is the single publication boundary for
manual imports, inbox processing, refreshed downloads, supported vendor
adapters, and index rebuilds. It validates and applies the effective package
policy before constructing the repository record and signed index. Refresh
also checks already published records for changed mandatory policy, even when
there is no newer upstream download.

The root-owned registry is:

```text
/usr/local/share/software/package-policies.json
```

It supplies mandatory ChatGPT policy. Per-package policy is retained in the
repository catalog under `/var/lib/software`, alongside the package's upstream
identity and policy digest. Exact upstream archives are retained privately as
`/var/lib/software/upstream/PACKAGE/SHA256.deb`. Reapplication starts with these
verified original bytes, not an already edited archive. Local revisions and
`X-Local-Policy-SHA256` distinguish repackaged publications from upstream bytes.
Custom policy survives subsequent automatic downloads and adapter updates.

ChatGPT's required policy removes the existing X11/Xwayland/NVIDIA/CUDA and
related dependency patterns; removes packaged vendor APT sources and keys;
drops upstream maintainer scripts/triggers that could recreate them; and places
the managed defaults, AppArmor profile, desktop entry and icon inside the
package before publication. The replacement **package-local** postinst calls
`local-apt-vendor configure-chatgpt` to finalize that package's installed assets.
It is not a global dpkg hook and does not run on unrelated package transactions.
Mandatory registry rules cannot be weakened by a per-package policy override.

The unrelated existing `95-labwc-desktop-apps` desktop-entry synchronization hook
is intentionally retained: it is not a vendor APT/dependency rewriting hook.

### Command examples

```sh
sudo local-apt-init --init
sudo local-apt-init --list
sudo local-apt-init --status
sudo local-apt-init --inspect /root/incoming/example.deb
sudo local-apt-init --add /root/incoming/example.deb --yes \
    --remove-depends xwayland,example-optional-driver \
    --remove-vendor-apt --drop-maintainer-script postinst
sudo local-apt-init --show example:amd64
sudo local-apt-init --policy example:amd64
sudo local-apt-init --remove-depends example:amd64 xwayland
sudo local-apt-init --remove-vendor-apt example:amd64
sudo local-apt-init --reapply example:amd64
sudo local-apt-init --refresh
sudo local-apt-init --rebuild
```

Use `--url HTTPS_URL` on import to select the supported automatic update source.
`--set-policy PACKAGE ROOT_OWNED_POLICY.json` validates and merges explicitly
provided policy fields, then republishes a new local revision. For example:

```json
{
  "remove_depends": ["xwayland"],
  "remove_depends_patterns": ["example-driver-*"],
  "remove_vendor_apt": true,
  "drop_maintainer_scripts": ["postinst"],
  "remove_paths": ["/usr/share/example/unwanted-file"],
  "automatic": true,
  "url": "https://downloads.example.invalid/example.deb"
}
```

The example URL is deliberately nonfunctional; substitute an approved upstream
URL. Policy input must be a regular, root-owned, non-group/world-writable file.
`remove_paths` names exact archive entries, not a recursive directory-removal
command. `--rebuild` regenerates indexes and enforces mandatory policy;
`--reapply` explicitly republishes a package revision from its retained original.
None of these commands installs a package. Normal `apt upgrade` remains separate.

`--remove-vendor-apt` removes source/key files **inside that package**. It is not
permission to erase unrelated live repositories. Potential source/key recreation
in retained maintainer scripts is detected conservatively and rejects publication
unless the administrator explicitly reviews and drops the offending scripts.
This lexical check is not a proof against arbitrary malicious shell code. Dropping
scripts or required dependencies can break vendor functionality; inspect and test
custom policies before deploying them.

Archive handling rejects unsafe paths, duplicate members, problematic link
relationships, special device members and oversized expanded data. Repacking
never runs upstream package scripts. Removing an archive's dependency declarations
does not remove an actual binary runtime dependency.

The refresh service keeps `NoNewPrivileges=true`. Its fetch-only Perl bridge and
Discord archive validator inherit the repository AppArmor profile, avoiding an
NNP-incompatible privilege-widening transition. This inherited context does not
receive ChatGPT's package-local installation permissions.

## 2. Rename and installation wiring

The installed public executable is `/usr/local/bin/local-apt-init` (0755).
Installer staging, `local-apt-refresh.service`, its AppArmor attachment, tests
and current documentation refer to it. The Python backend remains the private
`/usr/local/libexec/local-apt-repository` implementation.

On explicit initialization, narrowly recognized legacy managed hook/entrypoint
contents can be retired. Customized legacy files cause a refusal rather than
blind deletion. A legacy package that was already rewritten but has no retained
original must be imported again from an authentic original `.deb` before its
policy can safely be reapplied. The implementation does not guess original bytes
from an already edited package.

For new installations, deploy the entire regenerated repository atomically.
Updating the served source tree does not itself update existing installed hosts.
For those hosts, stage the changed root-owned helpers, Python module inventory,
units, policy assets and AppArmor profiles through the existing deployment
mechanism before calling `local-apt-init --init`. Do not overlay the whole target
skeleton onto a live filesystem. Reload the affected service/profile definitions
using the established administrator procedure. This work did not create a general
live-host migration/deployment tool.

## 3. Vendor-normalized APT sources

`finish-install.d/95-normalize-apt` invokes the staged
`/usr/local/libexec/local-apt-normalize-sources` after the existing APT
modernization step. It examines `/etc/apt/sources.list`, all active `.list` and
`.sources` files in `/etc/apt/sources.list.d`, and the known misplaced Debian
source files. The real directory is `/etc/apt`, not `/etc/aot`.

For installed vendors, the output names are:

```text
/etc/apt/sources.list.d/debian.sources
/etc/apt/sources.list.d/microsoft.sources
/etc/apt/sources.list.d/vivaldi.sources
/etc/apt/sources.list.d/mise.sources
/etc/apt/sources.list.d/xanmod.sources
/etc/apt/sources.list.d/mullvad.sources
/etc/apt/sources.list.d/apt-local-repository.sources
```

A vendor file can contain several stanzas: combining vendors into files does not
collapse different suites, repositories, components or trust settings into one
invented repository. Microsoft Edge, VS Code and Microsoft product repositories
share `microsoft.sources`; equivalent Edge definitions are deduplicated.
Architecture selections are merged only when other source semantics agree.
Unknown vendors receive deterministic hostname-based names. Vendors absent from
the input do not get invented repositories or empty placeholder files.

Signed-By, extra deb822 options, multi-URI/multi-suite inputs and explicit disabled
stanzas are preserved. A key-path difference is accepted only when the key bytes
or extracted fingerprint sets agree. Conflicting signing identities fail before
active source files are rewritten; the normalizer never resolves this by adding
`Trusted: yes` or dropping signature verification.

Exact original files and inactive APT backup artifacts are retained outside the
active source directory under `/var/lib/apt/source-normalization`. Output files
are replaced atomically individually; this is not a crash-atomic whole-directory
transaction. Repeated normalization is idempotent. The existing local repository
signing key filename `managed-external-software.gpg` is retained deliberately to
avoid unnecessary key migration; only the source file has its new canonical name.

## 4. Authenticated power, logout, isolation and recovery

The Waybar menu routes through `labwc-power-settings` and `labwc-admin-action`.
Polkit authorizes only the exact fixed root helpers. Machine actions require a
fresh administrator authentication for a sudo-group user; no AUTH_ADMIN_KEEP
cache or broad systemctl authorization is introduced. Self-logout has its own
fixed helper and cannot be changed into a privileged machine action. The invoking
UID is taken from pkexec and revalidated, not trusted from arbitrary menu input.

The root helper starts `labwc-admin-action@UID-ACTION.service`. This system service
survives termination of the caller's compositor, panel and user manager. Its
worker retains NNP, a CAP_KILL-only bounding set and the existing system-service
sandbox. Fixed system utilities inherit the worker's AppArmor profile rather
than attempting PUx transitions forbidden under NNP. Explicit local system-bus,
process-inspection and signaling permissions support the worker's fixed actions.
Home documents and recovery descriptors are handled only by the unprivileged
session helper, not parsed or evaluated by root.

### Reboot, poweroff and logout

After authorization, the worker checks the session and blocks machine actions
when another interactive account is logged in. It asks a separate transient user
service to prepare the desktop. Preparation puts a launch barrier in place,
records allowlisted launcher descriptors, and requests normal Wayland window
closure. Applications receive their normal save/hot-exit opportunity. The helper
waits up to 120 seconds for both windows and marked application service cgroups
to disappear. A save dialog, an unclosed tray application, an unsupported nested
Cage session or a failed protocol query aborts teardown instead of guessing that
it is safe to kill the program.

Only after successful preparation does it clear clipboard/primary selection and
managed history, stop selected orphan session services, stop
`labwc-session.target` and the compositor, terminate the invoking UID's logind
sessions/user manager/slice, and clean up remaining processes of that exact UID.
It refuses the final power action if processes still remain. Filesystems are
synced before the single-force machine action. Logout uses the same preparation
and UID cleanup without powering off or rebooting.

A single `systemctl --force reboot` or `systemctl --force poweroff` bypasses the
normal shutdown transaction, **not PID 1 itself**. Double force is never used.
The desktop preparation does not promise application-level draining of every
system daemon whose normal ExecStop may be skipped by forced shutdown.

### Suspend

Suspend takes a separate path: start the forking locker through a transient user
service, wait for the swaylock readiness/lock check, and issue
`systemctl --force suspend`. It does not close documents, clear the clipboard,
stop the session or terminate applications. It retains systemd's sleep path and
existing driver/GPU sleep hooks; it does not write `/sys/power/state` directly.
A lock failure blocks suspend.

### Application isolation and next-login recovery

The managed native and generic launchers retain their transient user service
model and session ownership. Added/updated paths use cgroup lifetime and
control-group kill mode, mark applications for handoff, and honor the launch
barrier. Standalone qBittorrent, Mullvad GUI, imported FocusWriter documents and
Labwc Settings now route through the appropriate isolated launch paths. The
existing dedicated Foot server and infrastructure services are not rewritten;
terminal shells and arbitrary user-invoked commands are not intercepted or
replayed as applications.

`labwc-session-restore.service` runs after the compositor's established autostart
readiness. It reopens supported application launch descriptors through the same
isolated wrappers. State is stored under `~/.local/state/labwc-session` with a
0700 directory and 0600 files, no-follow checks, bounded JSON and atomic writes.
Descriptors can contain private argv/working-directory information; this is not
an encrypted state store. Unsupported shells and executable paths are rejected.
Failed restore handoffs retain retryable descriptors.

**This is not a universal checkpoint of unsaved application memory.** VS Code's
native hot exit is enabled for new homes; FeatherPad's last-session restoration
is enabled and restarted without stale initial file operands; FocusWriter keeps
its native session behavior. Gnumeric and other applications may require the
user to answer a normal Save dialog. An unnamed buffer cannot reliably be saved
to an invented filename without application cooperation. Exact restoration of
all documents, cursor positions and newly created windows depends on each
application's session support. The wrapper will not press Discard, fabricate
keystrokes, or SIGTERM an application as a substitute for saving it.

New skeleton preferences do not overwrite existing user settings. Existing homes
must deliberately merge the Code/FeatherPad preferences and receive the new
restore unit through the normal desktop deployment process. Tray applications
must be quit using their native Quit action if closing a window leaves them
running. Nested Cage applications must be closed before requesting teardown.

## Validation actually performed

Current logs are in `validation/` next to this report.

| Check | Result |
| --- | --- |
| `tools/tests` | 109 tests passed, including 45 new policy/source/power regressions |
| Installation-fix regressions | 34 passed |
| Configuration safety | 19 passed |
| Session lifecycle | 22 passed |
| D-Bus broker regressions | 16 passed |
| NVIDIA power regressions | 13 passed |
| Shell parsing | 267 shell files; 545 parser checks passed |
| Changed/new Python syntax | 16 files passed AST parsing |
| Payload/pin freshness | Passed; 1,257 payload files regenerated |
| Changed AppArmor profiles | Names-only parsing passed; no kernel load/enforcement test |
| Root worker/refresh and restore units | Offline configuration verification passed, man-page lookup disabled |
| Whitespace/diff check | Passed |

Power tests mock systemctl, loginctl, process signals and compositor operations;
no real power transition or root-user cleanup is performed in tests. Repository
tests use local fixtures; they do not establish availability or runtime behavior
of every live upstream vendor service.

The complete original desktop test collection is **not claimed green**. The
70-test desktop sandbox suite has 68 passes, one skip and one failure because the
uploaded baseline lacks `todo/apparmor.log`; the same incident test fails on the
unmodified original tree. The profile provenance test reports 13 original host
profile/hash-ledger mismatches, reproduced on the unmodified original tree. The
focused current payload-freshness assertion passes. No host profiles or historical
migration ledger were changed to hide those failures. Four original Perl vendor
tests cannot run their assertions because this environment lacks `Moo.pm`.
An attempted broad installer-suite run and a later full repository-integrity run
exceeded their time bounds; neither is counted as a pass. These limitations are
included rather than replaced with invented success results.

### Installed-host acceptance still required

Use a disposable VM or lab host with the target Debian/systemd/AppArmor versions.
Verify package policy persistence over two genuine vendor releases, same-version
policy revision, signed APT installability, and normalizer trust preservation.
Verify each listed desktop entry owns an isolated transient application cgroup.
Exercise new/unsaved documents in Code, FeatherPad, FocusWriter and Gnumeric;
resolve and cancel save dialogs; test tray/nested-app refusal, cancelled polkit
authentication and a second logged-in user. Check successful logout/relogin and
reboot restoration, suspend/resume with GPU hooks and a ready lock screen, and
AppArmor denial logs in enforcing mode. No booted unattended installation, real
force reboot/poweroff/suspend, or hardware acceptance test was possible here.

## Primary reference material used during review

- systemd systemctl documentation: https://www.freedesktop.org/software/systemd/man/latest/systemctl.html
- systemd shutdown semantics: https://www.freedesktop.org/software/systemd/man/latest/systemd-shutdown.service.html
- Kernel no-new-privileges semantics: https://docs.kernel.org/userspace-api/no_new_privs.html
- systemd v257 local user-bus transport implementation: https://github.com/systemd/systemd/blob/v257/src/libsystemd/sd-bus/sd-bus.c
- Code hot exit: https://code.visualstudio.com/docs/editing/codebasics
- FeatherPad native close/save behavior: https://github.com/tsujan/FeatherPad/blob/master/featherpad/fpwin.cpp
- FeatherPad last-session reopening: https://github.com/tsujan/FeatherPad/blob/master/featherpad/singleton.cpp

`changes.tsv` records changed source paths and before/after SHA-256 digests against
the supplied archive's committed baseline. Documentation/validation under this
report directory is excluded from that ledger to avoid self-referential hashes.
