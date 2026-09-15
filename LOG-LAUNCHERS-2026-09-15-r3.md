# Debian unattended desktop: launch and policy follow-up, r3

Date: 2026-09-15. Baseline: `debian-preseed-de-fixed-20260915-r2.tar.gz`.

## Release status and scope

This release implements the requested single `app-` scope drop-in, fixes the
Mullvad launcher handoff and user-namespace incompatibility, corrects Chromium's
outer AppArmor profile flags, and covers the additional recorded AppArmor access
families. The two specific Waybar GTK diagnostic floods are coalesced, not
repaired inside the Waybar binary. Bitwarden's missing refresh token remains an
explicit credential-state warning, not a falsely successful operation.

These are source-level corrections with offline regression and packaging checks.
No fresh installation, live graphical session, target-kernel AppArmor enforcement,
or successful real Mullvad/Chromium GUI launch has been demonstrated in this
container. The Computer Management menu's status-2 failure remains unresolved
because the supplied capture does not establish its cause. It is not relabeled
as successful cancellation.

No kernel, driver, compositor, application, or native test program was compiled.
AppArmor checks used names/preprocessing modes only, without loading policy or
writing caches. No application is switched to an unconfined or no-sandbox mode.
No credential is fabricated, erased, or moved to a plaintext password store.
The user's excluded Codex `.system` repair is not implemented.

All 1,867 original repository files remain. Of the 1,963 r2 files, 1,959 remain;
the only four removed files are the now-obsolete application-specific scope
drop-ins, removed at the user's explicit request. Existing file modes are
unchanged. Eight existing production source/policy files and one existing test
module changed; the three generated installer artifacts were regenerated.
A new configuration file and a new regression module were added, together with
this report and validation evidence. `validation/log-launchers-20260915-r3/`
contains the source patch, change hashes, input census, and check results.

This report supersedes the four-prefix scope strategy in the r1/r2 reports.
Those historical reports are retained, not rewritten to claim broader success.
The earlier firstboot, Tuta private-bus, Spotify supervisor, Timeshift, Foot,
FocusWriter, RetroArch, and private Xwayland changes are retained.

## Input coverage

Every byte of each of the six new inputs was read. Their names, sizes, SHA-256
hashes, and physical LF-delimited line counts are recorded in
`input-review.json` in the validation directory. This pass covers 28,262 such
lines across the six files. Audit control separators are not counted as additional
physical lines. The separate application extracts overlap the journal; they are
not independent extra incidents.

| Input | Physical lines | Main evidence |
| --- | ---: | --- |
| `chromium(1)` | 7 | Managed launch reaches Chromium; Wayland format-table FD is missing. |
| `journalctl` | 3,887 | Firstboot success, both Chromium crashes, Mullvad reconnect flood, Bitwarden warning, Tuta/Waybar and other messages. |
| `kernel-audit.log` | 92 | Successful service, BPF, and authorized sudo audit activity; no new access denial in this extract. |
| `mullvad-vpn` | 73 | GUI starts but refuses the daemon socket's apparent ownership. |
| `tuta-waybar` | 14 | Seven occurrences each of two Waybar GTK acceleration-group assertions. |
| `apparmor(2).log` | 24,189 | 380 status records and 23,807 complain-mode access records, plus two boot-command lines. |

Deduplicating the AppArmor access records by audit identity and all parsed fields
removes 10 exact repetitions, leaving 23,797 access records. These are not 23,797
independent bugs. There are six parent-profile families and many repeated reads
or inherited null-profile records. No record in this new AppArmor capture is
labeled `DENIED`; that does not mean enforce-mode permissions are complete, or
that disconnected-path errors cannot affect execution.

No raw copies of the new logs or account secrets were added to the served
repository. The source patch includes policy paths, not credential contents.

## 1. One drop-in for every app-prefixed scope

The installed template is now exactly:

```text
d-i/forky/hooks/target/etc/skel-desktop/.config/systemd/user/app-.scope.d/50-session-labwc.conf
```

Its effective settings are:

```ini
[Unit]
Requisite=labwc-session.target
After=labwc-session.target
PartOf=labwc-session.target

[Scope]
KillMode=control-group
TimeoutStopSec=20s
SendSIGKILL=yes
```

`desktop/components.sh` stages this one asset at mode 0644. The previous files
under `app-bitwarden-.scope.d`, `app-code-.scope.d`,
`app-com.vivaldi.Vivaldi-.scope.d`, and `app-org.chromium.Chromium-.scope.d`
were removed from the source and regenerated payload. The real staging fixture
was updated to assert the single asset, rather than merely testing a hard-coded
string in an unused file.

Systemd's dash-prefix drop-in lookup makes this apply to `app-*.scope`, including
the `app-mullvad-vpn-24857.scope` seen in the new log. It does not apply to all
scope names or change service sandbox properties. It intentionally requires an
active Labwc session for app-prefixed scopes in the managed desktop account.
More-specific local drop-ins can still override settings; those must be checked
on an existing installation. [S1]

This binds application-created scopes to the session lifetime. It does not
prevent a Chromium/Electron application moving out of its launching service's
cgroup, and does not claim that every service-only security property follows that
move. Process namespaces are not changed by this drop-in.

## 2. Mullvad: repair both stages of the launch

### Observed failure

At 16:15:30 the Fuzzel path reports `pkexec must be setuid root` followed by
`Mullvad daemon start was cancelled or failed (status 127)`. The existing wrapper
attempted authorization before handing off to the host user manager.

A later terminal-launched attempt starts the daemon and GUI, but the GUI reports
`Failed to verify root ownership of socket`. The complete journal contains 1,974
lines with that ownership error. It also reports secondary version-info failures
because no daemon connection was established.

The generic application's filesystem/IPC isolation properties implicitly require
a user namespace in a user manager. The documented per-user UID mapping omits
root. This explains why a genuinely host-root-owned daemon socket can appear
unowned by root to the GUI. The same namespace boundary also prevents the early
polkit launcher from acquiring host-root credentials. [S2]

### Implemented change

`/usr/local/bin/mullvad-vpn` now validates the managed Wayland session and enters
a canonical transient `labwc-wayland-mullvad-vpn-<32 hex digits>.service` before
attempting polkit authorization. Its recursion guard checks actual unified
`/proc/self/cgroup` membership, not an environment flag. The host-stage wrapper
also checks `/proc/self/uid_map` and fails explicitly if root is still remapped.
A caller-supplied marker cannot skip the handoff.

`generic.py` omits the three namespace-inducing properties only for:

- the Wayland bootstrap command `/usr/local/bin/mullvad-vpn`; and
- the Electron vendor command `/opt/Mullvad VPN/mullvad-vpn`.

The prior terminal and Timeshift exceptions are unchanged. Same-basename files
in `/tmp`, altered paths, and using the wrong generic launcher kind do not receive
the new exceptions. Normal filesystem permissions and AppArmor still apply.

Polkit authentication, the root helper's checks, the bounded authorization
command, session prerequisites, cgroup cleanup, journal capture, and Electron's
own sandbox remain. The GUI stays an ordinary user process. The daemon socket is
not chowned, made world-writable, or trusted without ownership verification.
Neither global X11 nor `--no-sandbox` is introduced.

The corresponding wrapper policies permit the observed inherited PTY use and the
new handoff/UID-map read. The privileged helper needs the authenticating user's
PTY without an owner qualifier because it runs with root fsuid; the user wrapper
has owner-qualified PTY access.

Tests cover production cgroup/UID-map predicates, pre-authorization handoff,
spoofed environment markers, already-running daemon behavior, cancellation,
wrong root mappings, canonical-path matching, and refusal of sandbox-disabling
Electron arguments. These are fixture tests, not a real authorized GUI launch.

## 3. Chromium: the missing Wayland descriptor is a profile-header defect

The capture shows the same failure in both requested GPU modes: the application
starts, logs `file descriptor expected ... format_table(hu)`, and subsequently
exits with `status=5/TRAP`. At the corresponding time, AppArmor reports
`file_receive`, `error=-13`, and `Failed name lookup - disconnected path` for
`dev/shm/wlroots-...` under the package profile `chromium`.

This is distinct from simply lacking another `/dev/shm` file rule: the shared
Electron runtime already permits the owner's `/dev/shm/**` access. The outer
profile needs the disconnected/deleted-path flags. Upstream AppArmor's
`path_name()` returns a path-resolution failure after auditing it, so an
`ALLOWED` complain-mode label is not proof that this path-resolution error was
bypassed. This mechanism is consistent with the captured missing FD. [S3]

The late installer now passes `/target/etc/apparmor.d/chromium` through the same
existing guarded profile-header normalizer used for other package browsers. It
adds `attach_disconnected` and `mediate_deleted` to the actual outer `chromium`
profile. It does not put ineffective flags in a local include. The normalizer
preserves legitimate existing flags and attachment paths, rejects symlinks,
ambiguous/duplicate headers, unsupported permissive forms and oversized input,
and is idempotent. The configured managed complain/enforce choice remains
controlled by the existing mode-management policy.

Two recorded Crashpad reads are covered with owner-qualified, read-only
`@{PROC}/[0-9]*/mem` access in `local/chromium`. This does not bypass ptrace or
ordinary kernel access checks and is not claimed to repair the crash itself.
The disconnected-path correction addresses the earlier launch-path defect.

No GPU-mode workaround, driver change, Xwayland fallback, coredump suppression,
or conversion of SIGTRAP into success was made. Chromium launch and enforce-mode
FD reception still require verification on the installed kernel. A later vendor
package replacement of the outer profile must also retain/reapply the managed
flags; the local include alone is insufficient.

## 4. Additional AppArmor coverage and profile transitions

| Parent profile | Deduplicated access records | Disposition |
| --- | ---: | --- |
| `managed-desktop-launcher` | 21,197 | Read-only package metadata and managed repository browsing; specific owner repository metadata/account edits; missing git-core execution inheritance. |
| `managed-codex-wrapper` | 2,059 | Four missing `git-ssh` transitions and their null descendants. |
| `managed-labwc-chatgpt` | 535 | One missing `git-ssh` transition and its null descendants. |
| `chromium` | 4 | Two disconnected FD receives and two Crashpad reads. |
| `managed-mullvad-vpn` | 1 | Inherited user PTY, with duplicate log record removed. |
| `managed-mullvad-daemon-start` | 1 | Inherited authenticating-user PTY in the root helper. |

There are 2,871 null-descendant records: 2,055 under the Codex wrapper, 534 under
the ChatGPT wrapper, and 282 under the desktop launcher's git-core execution.
Those children should execute under the intended profile, not gain individual
allow rules for transient `//null-...` names.

### Git identity wrapper

The two affected callers now explicitly transition to the named
`managed-git-ssh` profile. The new profile is **not attached globally** to the
executable: unrelated terminal invocations retain their previous attachment
behavior. It permits the existing identity checks, account metadata, public key,
read-only verification of the protected key/blob files, the managed SSH-agent
socket, and user-systemd D-Bus operations needed by the existing helper.

The wrapper itself is unchanged: it still verifies ownership, directory modes,
link counts and the socket, and starts the established key-loading service rather
than gaining a new decrypt/credential-writing path. The profile grants neither
INET networking nor host capabilities. Explicit lifecycle signals are permitted
on both the sending callers and receiving helper, so a new exec transition does
not accidentally prevent timeout/shutdown cleanup.

### Terminal/package/repository access

The desktop-launcher profile gains read-only access to the recorded apt list,
cache and dpkg metadata paths. It gains no apt/dpkg database write permission.
`/usr/lib/git-core/git` now inherits the intended launcher profile rather than
creating a null-profile cascade.

The observed `/data/codex/usr/` repository is readable. Additional writes are
owner-limited to its `.git` metadata and the exact recorded `auth.json`,
`config.toml` and `.config.toml.swp` account-edit paths. The patch does not add
write or execution access to the Codex `.system` subtree, run a system-skills
installer, or relax the dedicated Codex runtime profile's `.system` restrictions.
The new read-only repository rule also covers ordinary browsing beneath that
root; it is not a `.system` write workaround.

All six recorded parent-profile families have an explicit disposition. That is
an evidence-coverage statement, not a claim that arbitrary future application
behavior has been permitted. No blanket file, capability, or unconfined execution
rule was added.

## 5. Tuta-triggered Waybar GTK diagnostics: mitigation, not a binary fix

The supplied extract names **Waybar** and two GTK functions:
`gtk_widget_set_accel_path` and `gtk_widget_add_accelerator`. Each asserts that its
acceleration group is valid. The new capture does not show a fresh Tuta tray-name
D-Bus denial. The existing private Tuta proxy's specific StatusNotifierItem OWN
permission and filtered watcher access remain unchanged.

Waybar's upstream tray implementation contains explicit GtkAccelGroup setup to
avoid this missing-group condition, and an upstream issue reports the same
assertion family. That is supporting context for the component diagnosis, not
proof that a particular packaged binary on this laptop contains the correction.
No unverified vendor-version pin or locally compiled Waybar is supplied. [S4][S5]

The existing `labwc-panel-run` coalescer now recognizes only those two exact
assertion messages with the Waybar GTK prefix. It retains the first original
record on each stream, groups repeats across changing timestamps/PIDs, and emits
repeat counts periodically and at shutdown. Other GTK critical messages,
continuation text, unrelated process prefixes, stdout/stderr separation and the
real process exit status are preserved. Bitwarden warnings are not filtered.

This limits journal flooding while preserving evidence. It does not initialize a
missing GtkAccelGroup inside the already-built Waybar process, guarantee menu
functionality, or prevent an upstream tray crash. A packaged upstream fix and a
real Tuta tray-menu replay remain the acceptance boundary. The tray is not
disabled and fatal GTK behavior is not globally masked.

## 6. Bitwarden's refresh-token warning

The warning occurs once at 16:25:37.989. The journal then reports a connected
notification WebSocket and vault unlock processing. The message is not itself a
transient-service start failure, and there is no Bitwarden AppArmor access denial
in this new capture. It also is not safe to assert that the missing refresh token
is always harmless: it can affect continued authentication when refresh is
needed.

The repository already launches Bitwarden after/requiring the ready
`labwc-kwallet-portal.service`, which owns `org.freedesktop.secrets` using a
`Type=dbus` unit and a post-start readiness check. The existing Electron setting
remains `--password-store=gnome-libsecret`. New regressions explicitly verify
those choices and that the warning is not filtered or mapped to a successful
exit status.

The available evidence does not establish why this account lacks a refresh token.
No missing credential can be reconstructed from this message. On the installed
account, verify that the secret-service/keyring is available and unlocked. When
the warning persists for an authenticated account, normal reauthentication is a
reasonable recovery step after confirming the vault is synchronized and no
unsaved changes will be lost. Do not delete the vault, auth files, or keyring as a
blanket installer repair. Capture follow-up diagnostics without exposing access
tokens, refresh tokens, passwords or secret-service item contents.

## 7. Other messages: explicit disposition

| Message family in the supplied files | Classification and action |
| --- | --- |
| `firstboot.service: Deactivated successfully` at 15:48:31 | Success in this boot. Earlier firstboot metadata fix retained; no new firstboot failure inferred. |
| CrowdSec `status=pass enrollment=enrolled`, followed by service completion | Successful bootstrap. No disabling or success masking. |
| `secondboot.service: multiple trigger source candidates for exit status propagation ..., skipping` | Diagnostic about choosing a trigger's status, not proof that the secondboot service failed. No blanket dependency removal. |
| Computer Management menu twice returns status 2, then a fatal message | Unresolved. The capture does not distinguish a child/menu error from any cancellation condition that could use that status. Existing nonzero handling remains; no arbitrary `SuccessExitStatus=2`. |
| VS Code says switches are unknown but still passed to Electron/Chromium | CLI forwarding notices; no rejection of the actual launch shown. Existing native graphics flags retained. |
| Vivaldi missing search JSON, NoScript resource blocked by extension web-accessibility rules, WidgetHost rejection | Vendor/extension diagnostics, not a demonstrated AppArmor path failure in this capture. No invented files, extension-security bypass or speculative driver edit. |
| Tuta Buffer deprecation and WebAssembly experimental warning | Vendor runtime diagnostics. No application code or runtime recompilation. |
| Tuta vault key absent and then generated on first use | Initialization message, not proof of a secret-service denial. Preserve the real vault and keyring. |
| Tuta updater says APPIMAGE is not defined | Managed extracted application is not launched as its original AppImage; do not fabricate APPIMAGE or add no-sandbox. Managed update path retained. |
| Bitwarden native-messaging hard-link gives EXDEV and explicitly copies instead | Expected cross-filesystem fallback when the copy succeeds. No mount/permission weakening to force hard links. |
| Bitwarden optional Brave/Helium integrations absent | Explicit optional-browser skips, not failed application starts. |
| Bitwarden environment config times out and emits previous config | Application-side fallback; no evidence here establishing a repository defect. Retain diagnostic if persistent. |
| Cloudflare MCP AuthRequired/OAuth failures | Actual per-account authentication requirements. The installer cannot supply those account tokens and does not bypass authorization. |
| Codex cannot replace `.system` directory | Excluded at user request. No .system cleanup, permission broadening or installer repair. |
| Bluetooth missing first-run identity; Tailscale missing fresh state, cleanup probe and then cleared health warnings | Initialization/transition evidence, not grounds to disable either service. Continued failure would need a new capture. |
| Mullvad missing cached version info/default configuration during daemon startup | First-run cache/state initialization; distinct from the fixed GUI UID-view incompatibility. |
| Mullvad reports no cgroups for split-tunneling rules | Feature-availability warning; split-tunneling operation is not validated by this patch. No global cgroup/kernel rewrite. |
| Hyprpolkitagent QML/style warning | UI/library diagnostic. Authentication remains required; no polkit removal. |
| Missing global `/usr/bin/Xwayland`, compositor continues without it | Expected boundary of this repository's private-only Xwayland design. Do not install/enable global Xwayland. |
| Kernel audit service success, BPF LOAD/UNLOAD and successful sudo log-reading/copying | Audit activity, not a new failure or evidence of unauthorized escalation. The audit feed remains enabled. |

Previous r1/r2 hardware/firmware/vendor residuals are not newly claimed fixed by
this review. The absence of an older error from these narrower inputs is not
proof that it cannot recur.

## 8. Validation results and limitations

The selected completed test modules contain **406 tests: 381 passed and 25 were
skipped** across **14 modules**. This includes:

- 29 new r3 launch, policy and diagnostic tests;
- 23 existing incident regression tests, updated only for the requested generic
  scope staging;
- 8 passing r2 follow-up tests and its one skipped live proxy test; and
- the selected boot, desktop integration, installation, hardening, lifecycle,
  Git/debugging, security-refactor and scoped keyring suites.

The skipped checks include 23 target-runtime boot checks unavailable in this
container, the live filtered-bus test without `xdg-dbus-proxy`, and a real SSH
agent exercise without installed OpenSSH client binaries. Skips are not passes.

An attempted broader run timed out during the first legacy HTTP/BusyBox bootstrap
portability test. Its fixture process group was explicitly stopped and its result
is recorded as incomplete, not zero failures. This pass does not establish a
fully green whole-suite run or claim that the unrelated legacy failures described
in r2 have disappeared. Two native-compiler test modules were excluded entirely.
The validation directory lists the discovered modules and the actually completed
ones separately.

Additional checks:

| Check | Result |
| --- | --- |
| Managed AppArmor sources | 34 files, 231 profile names, names/preprocessing pass; includes resolved against available parser/base abstractions. |
| Shell parser checks | 277 files, 565 checks pass. |
| Preseed checks | 59 files pass; all four generated command values survive private debconf read-back unchanged. |
| Source syntax inventory | Python AST and nonexecuting shell syntax checks pass. The detailed inventory distinguishes binary/config/template-only entries from validated syntax. |
| Installer build and build --check | Pass; 1,287 payload files, current payload/manifest/preseed pins. |
| Independent payload inspection | Every path, content hash, byte sequence and execute-bit-derived packaged mode matches source. |
| Preservation | All original files retained; only the four requested obsolete r2 scope files removed; no existing mode drift. |
| Private Xwayland | Six dedicated files and three guard-profile blocks match both r2 and the original upload byte-for-byte. |

The optional `shellcheck` executable is unavailable. Perl and template entries
are not falsely counted as runtime-validated by the source inventory. No new Perl
runtime source is modified in r3. Passing policy parsing is not passing kernel
mediation; passing mocks is not successful hardware/GUI integration.

## 9. Deployment and acceptance

Publish the complete r3 snapshot atomically. Do not mix its source scripts with
r2's payload, manifest or preseed. The downloadable archive contains the complete
repository, not a binary patch or a live-system installer.

**An existing laptop is not changed by extracting this archive.** Fresh installs
receive the staged changes. Retrofitting a running installation requires applying
the changed canonical scripts/modules and policy files with their existing
root-owned modes, applying the guarded Chromium outer-profile flag change, and
reloading policy through the established managed path. Do not run a whole
installer late hook against a live filesystem as an improvised repair.

For an existing desktop account, copying only the file into `/etc/skel-desktop`
is insufficient: the user manager reads the account's current
`~/.config/systemd/user/` tree. Install the generic
`app-.scope.d/50-session-labwc.conf` there as well. Retire the four old managed
`50-labwc-session.conf` files only after checking/backing up any local edits;
leave unrelated drop-ins alone. Run `systemctl --user daemon-reload`. Stop/reopen
the affected applications, and use a full logout/login to verify session cleanup.
Existing processes and learned null-profile children do not become a clean replay
merely because source files were replaced.

Acceptance checks on the target:

1. Launch Mullvad from Fuzzel with the daemon stopped. Normal polkit authorization
   must start it; cancellation must not launch the GUI or become success. Repeat
   with the daemon already running. Confirm no recurring root-socket rejection.
   Do not alter the daemon socket's owner or mode to make this test pass.
2. Launch Chromium in both configured GPU modes. Confirm a real window and no
   format-table FD failure, disconnected-path event, or SIGTRAP. Check the actual
   package outer profile for both flags and use the configured AppArmor mode.
3. Inspect `systemctl --user show <actual-app-scope> -p DropInPaths -p After
   -p Requisite -p PartOf -p TimeoutStopUSec`. It must reflect the generic file and
   Labwc target. Test an app prefix beyond the previous four, and verify that all
   relevant app scopes disappear after logout.
4. Exercise Git identity status/unlock through the affected wrappers, plus
   read-only package queries and repository browsing. With AppArmor enforcing,
   check for new missing permissions rather than relying on complain-mode labels.
   Do not test or repair the excluded Codex `.system` operation.
5. Open Tuta, exercise its tray menu repeatedly, and check both tray operation and
   the coalescer's first occurrence/repeat summaries. A remaining GTK assertion or
   broken menu is an upstream runtime issue still requiring a packaged fix, not a
   passed functional test merely because fewer log lines appear.
6. Check Bitwarden's secret-service availability, normal authenticated startup,
   and continued session refresh. A repeat of the token warning is a credential
   incident to investigate, not something this installer fabricates a value for.
7. Reproduce the Computer Management submenu issue with its direct child stderr
   and the exact action taken, distinguishing explicit cancellation from launch
   failure. Its unknown status-2 cause is not covered by a success assertion here.

Useful non-secret checks include:

```sh
systemctl --user --failed
systemctl --user status labwc-kwallet-portal.service
systemctl --user list-units 'app-*.scope'
systemctl --failed
```

Do not publish unredacted application logs when they contain session URLs or
credentials. Check the archive SHA-256 before deployment; the separate delivery
verification JSON records the complete archive's verified file and mode coverage.

## Technical sources

Source evidence consists first of the six uploaded files identified in
`input-review.json` and the actual r2/original archives identified in
`changes-from-r2.json`. The following upstream material supports the mechanism
analysis; it is not substituted for the laptop's logs or runtime verification:

- [S1] systemd.unit dash-prefix drop-in lookup:
  `https://manpages.debian.org/unstable/systemd/systemd.unit.5.en.html`
- [S2] systemd.exec user-manager namespace requirements and root UID mapping:
  `https://manpages.debian.org/unstable/systemd/systemd.exec.5.en.html`
- [S3] Linux AppArmor file mediation, especially `path_name()` and its caller:
  `https://raw.githubusercontent.com/torvalds/linux/master/security/apparmor/file.c`
- [S4] Waybar tray item implementation and GtkAccelGroup initialization:
  `https://raw.githubusercontent.com/Alexays/Waybar/master/src/modules/sni/item.cpp`
- [S5] Upstream Waybar GTK_IS_ACCEL_GROUP issue:
  `https://github.com/Alexays/Waybar/issues/5224`

Retrieved 2026-09-15. Upstream tip source is mechanism evidence, not a verified
version-to-version match to the installed XanMod kernel or Waybar package.
