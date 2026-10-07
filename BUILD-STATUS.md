# Build status - 2026-10-07 desktop runtime and qBittorrent networking

The [desktop runtime validation record](docs/validation/desktop-runtime-20261007.md)
covers all 48 TODO files and the complete uncommitted integration. qBittorrent
uses packaged slirp4netns in a private network, with TCP and UDP forwarding on
the profile-selected port and active IPv4 route. Startup readiness, concurrent
launch IPC and cancellation are bounded. Mounted torrent storage has scoped
sysfs metadata reads and no raw block-device access.

Mako login and D-Bus activation share one systemd service through the canonical
package-maintenance producer. Ctrl+Win+L enters the host user-manager namespace
before applying the unchanged strict root policy check. ChatGPT's standard save
directories and cold document-portal mount have matching sandbox and AppArmor
write permissions.

The focused suites ran 120 tests: 116 passed and 4 were skipped for actual-root
fixtures or the unavailable host TUN device. Real Unix IPC/API, flock, dash/ash
publication and inert Bubblewrap startup/cancellation fixtures were exercised;
route replies, portal transport and successful network readiness used mocks.
All 45 managed AppArmor policy files parse offline and their named transitions,
includes and staging references pass. All 711 shell parser checks pass.

The rebuilt 1,704-member payload, manifest and preseed pins are current. Archive
read-back matches every source file and manifest entry. Exactly 15 payload
members changed; member names and all archive metadata are preserved. All 14
members named for private Xwayland/compatibility are unchanged; the shared
network supervisor's new peer mode is selected only by qBittorrent. The
private-Xwayland suite's unchanged sys_ptrace assertion also fails in HEAD.

No software compilation, host policy load, desktop restart, router change or
deployment occurred. Local verification uses Forky/systemd 262; the requested
target remains Forky/systemd 261.2. External incoming TCP/UDP, private-tracker
seeding, actual ChatGPT downloads and desktop enforcement need installed-target
acceptance. The supplied eDP-1 atomic EBUSY failures are investigated but remain
unverified on hardware; no speculative modesetting change was introduced.

## Previous snapshot record - 2026-10-07 gtkgreet power actions

The [greeter power validation record](docs/validation/gtkgreet-power-20261007.md)
identifies the supplied LPL-697 failure: pkexec rejected the `_greetd` account's
inherited SHELL before either Reboot or Shutdown reached the root worker. The
fixed-function greeter frontend now unsets SHELL at that boundary. The account
retains its nologin shell and the existing active/local authorization. Both
buttons reach the shared package-aware, cleanup-verified single-force worker.

Failed helper starts/jobs now leave a visible Reboot failed / Shutdown failed
label and a structured journal event. Confirmation timers are cancelled when
replaced or submitted, and retries require a new confirmation. First-boot
validation now checks the environment correction as well as the existing
single-force, identity and confinement contracts.

All 60 focused tests pass without skips: 35 greeter/button/dispatch tests,
11 force and first-boot gate tests, and 14 shutdown/storage tests. GTK, Polkit
authentication and PID-1 operations were replaced by controlled fixtures;
the real button controller and isolated copies of the shell helper chain were
executed. ShellCheck reports no diagnostics for the edited frontend. All 711
shell parser checks and all 59 preseed/private read-back checks pass.

The 1,704-member payload, manifest and preseed pins are current. Only
labwc-greeter-power, greetd-power-action and 04-validation.sh.tmpl changed in
the payload during this task; all other members and archive modes/link targets
were preserved, including Waybar's worker, earlier NFS/GitOps fixes and private
Xwayland. No software compilation, privileged helper execution against host
Polkit, live power action, service restart or deployment occurred. LPL-697
requires the two installed helper updates described in the record. A real
greeter reboot/poweroff on Forky/systemd 261.2 remains deployment acceptance;
the verification host uses systemd 262. Earlier broad-suite findings remain
outside this focused repair.

## Previous snapshot record - 2026-10-07 NFS client access and automatic mounting

The [NFS client validation record](docs/validation/nfs-client-access-20261007.md)
covers the reproduced inaccessible mode-000 client endpoints, both `noauto`
fstab entries, and the Connect action's refusal when a login had stale group
membership. Both client mounts now require `auto`, have generated boot links,
and retain the actual NFS source prerequisite for the home bind. Disconnected
client endpoints are navigable root-owned mode 0755 without ordinary-user local
write access. Connect remains an authorized, ordered retry.

The focused NFS suite ran 135 tests: 114 passed and 21 root-only private
filesystem fixtures were skipped under this workspace's ordinary account.
The navigation fixture exercised real directory modes and cd/list access;
root ownership was simulated there. All ten NFS profiles, all 711 shell parser
checks and all 59 preseed/private read-back checks pass. The 1,704-member
snapshot, manifest and preseed pins are current. Compared with the snapshot
at the start of this NFS task, only hosting.env, network-sharing.py and
labwc-network-sharing changed in the payload; all other members and all
archive modes/link targets, including earlier GitOps work and private
Xwayland compatibility, were preserved.

No software compilation, live mount, policy load, service restart or deployment
occurred. Native generator validation used systemd 262; the documented target
remains Forky/systemd 261.2. LPL-697 must receive the installed-client updates
described in the guide before its existing fstab and modes change. Its supplied
log shows NFS support startup, without establishing a mounted share or a server
access rejection. Server availability, actual source-IP admission and live
UID/GID/ACL/AppArmor access still require target acceptance. Earlier broad-suite
failures remain outside this focused repair.

## Previous snapshot record - 2026-10-07 GitOps and managed log review

The [GitOps and managed validation record](docs/validation/gitops-managed-20261007.md)
covers all 48 current TODO files, the reproduced symbolic-reference transaction
failure, detached-HEAD recovery, and the initramfs IOMMU redaction correction.
The existing qBittorrent style and AppArmor repairs were verified against the
current evidence; no duplicate implementation was added.

All 86 selected tests pass with no skips. ShellCheck reports no diagnostics for
the edited helper; all 711 shell parser checks and all 59 preseed/private
read-back checks pass. The 1,704-member snapshot, manifest and preseed pins are
current. Only the GitOps engine, its documentation template and the initramfs
health helper differ in the payload; all other members, including private
Xwayland compatibility, are unchanged. No software compilation or live
deployment occurred. Validation used systemd 262; target acceptance remains
Forky/systemd 261.2. Earlier broad-suite failures and documented hardware,
vendor, tray-menu and console-approval findings remain outside these verified
repository repairs.

## Previous snapshot record - 2026-10-05 desktop launcher and document repair

All 41 current desktop evidence files were read: 3,501,377 bytes, including 21
empty files. The source repair covers native missing-display recovery,
deterministic Fuzzel output/geometry selection, managed GTK accelerator groups,
Vivaldi driver safety, Tuta document/USB mounts and effective AppArmor access,
unclean user-journal reads, qBittorrent execution under no-new-privileges,
FocusWriter USB imports, and structured Zathura reading defaults.

The [desktop validation record](docs/validation/desktop-incidents-20261005.md)
reports 127 selected tests passing with no skips. These include effective native
AppArmor file masks, all 45 top-level policy parses, actual atomic media-rule
publication in dash/BusyBox, and explicitly mocked manager/socket and display
fixtures. All 711 shell parser checks and all 59 preseed/private read-back
checks pass. ShellCheck adds no diagnostics to the two edited shell scripts;
their existing diagnostics remain. The available systemd is 262, while target
acceptance remains Forky/systemd 261.2.

The rebuilt snapshot contains 1704 regular members, with 22 edited sources and
one new account-media policy template. The eight Xwayland-specific members and
all existing deterministic archive metadata are unchanged. The snapshot,
manifest, and preseed pins are current. No software compilation, live policy
load, mount, installation, service restart, or deployment was performed.

The repeated HDMI atomic EBUSY events and the forced-power-off freeze remain
unverified on the actual hardware. The supplied browser SIGTRAP and subsequent
reboot do not identify the translation freeze's exact cause. Vendor/account
warnings and actual attach/save/USB hotplug behavior retain their documented
live acceptance requirements. Earlier broad-suite failures below were not
rerun or declared fixed.

### WIN+F and qBittorrent follow-up

The four new compositor denials are the same missing `/usr/bin/env` transition.
The exact helper now inherits compositor confinement. WIN+F, Ctrl+Alt+F, and
the Labwc Files menu use the existing managed Wayland Thunar launcher, which
retains the application-local `GDK_DEBUG=nogl` setting and session-owned service
lifetime. No generic unconfined fallback was added.

All 30 focused follow-up tests pass with no skips. Native AppArmor rule reading
confirms inherited execution for env and qBittorrent; the compiled qBittorrent
file masks permit the payload, and its command fixture verifies namespace
isolation and `--cap-drop ALL`. All 45 policies parse offline. The snapshot and
pins are current, and all 59 preseed/read-back checks pass again. The three
additional payload edits are the compositor policy and two Labwc XML templates;
all eight Xwayland-specific members remain unchanged. Installed policy and user
configuration must receive these source changes before live acceptance.

### Waypaper process inspection follow-up

The additional events 1429-1469 are covered by nine exact `ptrace (read)`
grants in Waypaper's ps child and two scoped reciprocal `readby` rules in the
ChatGPT D-Bus proxy and slirp4netns helper. The other seven peers already inherit
the scoped reciprocal rule. All 22 selected tests pass without skips, including
effective expanded peer checks and offline compilation of all 45 managed
policies. The refreshed 1704-member snapshot differs from the captured previous
snapshot only in `desktop-wrappers.tmpl`; existing wallpaper inputs retain their
captured hashes. Snapshot/pin checks and all 59 preseed/private read-back checks
pass. The [validation record](docs/validation/desktop-incidents-20261005.md)
reports the commands and limits. No live policy reload or application launch
was performed; the installed host must receive the rendered updated policy.

## Previous snapshot record: 2026-10-05 explicit NFS client follow-up

The complete new `todo/nfs-client` log was read. Both client source and home
bind now require `noauto`, with no client automount/path activation or boot
links. The installer, menu, identity helper, diagnostics helper and shutdown
worker use configuration format 2; the independent diagnostics output retains
format 1. Connect/disconnect use the real mount units and preserve failure and
busy-unmount handling. The existing server TCP LAN accept rule is verified with
both base firewall profiles, the exact 41 export peers, both managed interfaces
and default/custom NFS ports. Enabled roles automatically select their overlays.

The [follow-up validation record](docs/validation/nfs-client-explicit-20261005.md)
reports 121 passing focused tests and 22 explicit skips, all 10 NFS profiles,
all 711 shell parser checks and all 59 preseed/private read-back checks passing.
The native generator confirms no client `.automount` or `.path` output and no
client boot activation links. Shutdown host commands are mocked. Available
systemd is 262; target acceptance remains Forky/systemd 261.2. No live host,
mount, firewall or service was changed.

The rebuilt snapshot retains 1703 members with exactly six scoped source-member
changes and unchanged metadata. Its three publication products and pins are
current. No Xwayland member changed and no software compilation was added.
Existing-host legacy autofs retirement requires the documented maintenance;
rebuilding alone cannot remove active units. Earlier broad-suite failures below
were not rerun.

## Previous snapshot record: 2026-10-05 supplied installed-host repair

All 88 supplied `todo/` files were read. The current repair covers the
lockdown-compatible, per-device NVMe correctable-log workaround and initramfs
wiring; absent-adapter boot validation and configured Wi-Fi fallback; NFS
identity startup hazards and root-owned Sharing parent access; the exact
`ksecretd` GPGSM exec denial; P15s speaker profile re-selection; and recovery of
the existing owned user bus for native application launch.

The [coverage and validation record](docs/validation/installed-incidents-20261005.md)
maps the remaining firmware, USB, display, external plugin and authentication
incidents to their acceptance requirements. The selected suite has 148 passing
tests and 37 explicit skips. All 711 shell parser checks and all 59 preseed
format/private read-back checks pass. Native AppArmor and WirePlumber checks
are offline; available systemd is 262, while the deployment target remains
261.2. No live host, policy load, mount, service restart or deployment occurred.

The rebuilt snapshot contains 1703 members with 16 scoped payload source/asset
changes. No Xwayland source/member changed or software compilation was added.
`python3 -B tools/build.py --check` confirms the snapshot and pins are current.
Earlier broad-suite failures remain recorded below and were not rerun.

## Previous snapshot record: 2026-10-04 AppArmor and compact Fuzzel repair

All three files under `todo/` were read. The 31 supplied AppArmor events reduce
to nine distinct requests, all represented in the existing October 4 incident
fixture. The microphone wrapper now permits read-only `/dev/shm/` and
`/etc/machine-id` access plus account-owned Pulse runtime directory maintenance.
The Mullvad local policy permits its account-owned dconf cache directory and
`user` cache file. Raw audio-device denials remain. The current source already
contains the qBittorrent stacked payload transition, the Codex child termination
rule, and both read-only monitoring endpoints; focused incident tests verify
those contracts without adding broader permissions.

All ten profiles, including both flex profiles, now select a 12-point internal
font, line height 20, width 50, 14 rows and padding 10/8/5. Unknown-output hotkeys
use the same compact DEFAULT dimensions; the existing external dimensions
(19-point font, line height 32, width 60, 18 rows and padding 16/12/8) remain.
The installer requires matching launcher/menu dimensions within each output
class and DEFAULT/INTERNAL agreement, while accepting larger external geometry.
An already-held Fuzzel lock now produces a bounded duplicate invocation: launcher
success or dmenu cancellation, with the owning picker/PID untouched. Actual
lock errors remain failures. New lock and PID files have mode 0600.

The flex-duo profile had enabled its client home bind while disabling the client,
which failed the existing NFS publication gate. Only that bind flag was disabled;
the p15s profile's deliberately enabled server and server home bind are preserved.
The offline policy fixture now replaces copied installed counterparts of source
templates, matching installer publication, and recognizes stacked profile names.

Validation passed: 66 selected tests (8 incident, 33 launcher/sizing/lifecycle,
12 policy/picker/NFS and 13 caller/rendering tests), including offline parsing of
all 45 managed top-level AppArmor policies with AppArmor parser 4.1.8. Lifecycle
tests use real processes and kernel file locks with a fixture picker; no Wayland
display is accessed. All ten NFS profiles pass the target policy checker. All
709 parser checks across 349 shell sources pass. ShellCheck still reports the
existing dynamic-variable and shell idiom diagnostics; comparison with HEAD
found no new diagnostic types in either changed shell file.
`python3 -B tools/check_preseeds.py` also passed all 59 preseed files and preserved
all four generated command values through private debconf database read-back.

The snapshot was rebuilt with 1701 payload members. Exactly 14 payload sources
changed: two AppArmor sources, the Fuzzel wrapper, the geometry validator and ten
profiles. `python3 -B tools/build.py --check` confirms the snapshot and preseed
pins are current. No Xwayland source or payload member changed, and no software
compilation was added. Python validation used 3.14.7. The available systemd is
262, so these offline checks do not claim runtime acceptance on target systemd
261.2. No live installation, kernel policy load, target restart or deployment
was performed. The older broad-suite failures below were not rerun.

The exact unittest selections were:

```text
test_apparmor_incidents_20261004
test_native_multimonitor_20260924
test_desktop_sandbox.FuzzelOutputSizingTests
test_menu_apparmor_integration_20260919.FuzzelLifecycleTests
test_compz_qbittorrent_followup
test_menu_apparmor_integration_20260919.AppArmorIntegrationTests
test_menu_apparmor_integration_20260919.PickerFailureTests
test_network_sharing.SettingsTests.test_all_ten_profiles_have_complete_safe_defaults
test_session_repairs_20260919.PickerIncidentTests
test_session_repairs_20260919.ProfileRenderingTests.test_every_profile_renders_equal_main_and_search_geometry
test_kanshi_fuzzel_followup_20260919.NativeShellProtocolTests
test_categorized_menu.MenuUnitTests.test_cancel_is_successful_and_silent
```

They were loaded with Python's unittest loader after explicitly adding
`d-i/forky/tests` to `sys.path`; subprocess boundaries were bounded. Deployment
acceptance still requires a Forky/systemd 261.2 session with enforcing AppArmor,
the affected applications, internal panels and external/docked output layouts.
When neither an output name nor class is supplied, Fuzzel keeps compact DEFAULT
geometry and lets the compositor choose placement; it does not infer focus from
an installer-time connector inventory. Publish the complete snapshot atomically.

## Previous snapshot record: 2026-10-03 finish-install home permission repair

The final `99-normalize-finish` hook still performed an unrestricted home chmod
walk after the earlier desktop pass. It reached root-owned, immutable Sharing
parents and aborted installation. The final hook now resolves a nonroot UID and
matching home from a unique entry in the target's `/etc/passwd`, verifies ownership,
and physically prunes foreign-owned entries before chmod or descent. Numeric
`-user` works with GNU find and the installer's BusyBox find. Sharing parent
flags and modes, `0000` unmounted endpoints, account-private modes, and fatal
account chmod failures are preserved. No mount, NFS policy, profile, AppArmor or
Xwayland source was changed.

The new fixture reproduced the original fatal directory normalization error.
The focused home/NFS/module/finish-order suite ran 155 tests: 129 passed and 26
were explicitly skipped. All 15 publication contract tests passed. Home tests
include the complete final hook, repeated execution, custom root-owned Sharing
parents, foreign files and descendants, GNU and BusyBox find/awk, symlink
boundaries, malformed/ambiguous identities, and fatal account chmod failures.
Ownership simulation is explicitly labelled: native foreign UID and immutable
fixtures cannot run in this environment, and private mount namespaces are denied.

The rebuilt snapshot contains 1694 payload files. Build freshness and all 59
preseeds passed, including private debconf command read-back. All 709 parser
checks across 349 shell sources passed with dash, bash and the official BusyBox
1.35.0 x86_64 musl binary. The whole-tree audit reported zero explicit failures:
612 syntax passes, 224 unit structure checks, 159 blocked Perl dependencies,
616 inventory-only records and 11 unrendered templates. These are offline checks;
the available systemd is 255, not the deployment's fixed systemd 261.2.

No software was compiled. No live Forky installation, immutable bind-mount/NFS
acceptance, enforcing AppArmor test or target service activation was performed.
The pre-existing broad-suite failures recorded below remain outside this repair;
those broad suites were not rerun. Publish the complete snapshot atomically and
perform an unattended installation on the intended deployment platform.

## Previous snapshot record: Codex, browser and Sharing integration


The desktop permission pass now prunes every foreign-owned entry before changing
modes or descending into directories. The NFS installer deliberately creates
root-owned, immutable home bind parents such as `/home/mcramer/Sharing` before
desktop configuration. The former home-wide chmod pass reached that protected
parent and failed with `Operation not permitted`; `find -xdev` did not exclude it.
All four permission walks now use physical traversal and an account-UID pruning
predicate. Root-managed parents and their `0000` unmounted endpoints remain
untouched, while account directories, data, programs and systemd units retain
their private modes. No immutable flag is cleared and no chmod failure is hidden.
The previous delivered block reproduces the protected-path failure in the
regression fixture with dash and official BusyBox ash; the corrected block passes.

The Codex publisher now accepts the private `0600` daemon-settings mode that
previously aborted installation. All ten host profiles define the SSH repository
`git@gitlab.com:core-assets/helpers/netscape.git`, branch `mcr/main`, and checkout
`Workspace/netscape`; there is no commit pin. The desktop installer reuses its
short-lived private SSH agent, stages the checkout privately, and publishes it
without replacing an existing checkout. Directories are account-owned `0700`,
regular data files are `0600`, and executable repository files are `0700`.
Symlinks, hard-linked files and special files are rejected. Target verification
checks the checkout ownership, modes, entry types and branch.

Browser policies are generated from `browser-config/policies.json` and staged
for Vivaldi, Chromium, Chrome and Edge. NoScript, Privacy Badger and uBlock Origin
Lite use `normal_installed` and default toolbar pinning. Managed extension storage
and the locked file-URL option are absent; users control extension settings and
manually import exports from the netscape checkout. Full uBlock Origin is Manifest
V2 and cannot be deployed to current Chrome through the Chrome Web Store. Edge's
existing AppArmor restriction on Workspace remains; intentional imports there
can use Downloads. Existing browser security and telemetry policy is preserved.

## Generated snapshot and permissions

The complete tree includes regenerated `d-i/forky/preseed.cfg`,
`d-i/forky/payload.manifest`, and `d-i/forky/payload.tar.gz` with 1694 payload files.
All source files use the project's nonexecutable `0644` contract; source
directories are `0755`, so ordinary HTTP/NFS service accounts can read the served
tree. Installer staging still applies its explicit executable, private-state and
credential modes. A review of 355 literal target staging paths found no conflicting
modes and no mismatch against their literal verifier checks. Every original profile
byte outside the three added browser assignments and their comment is preserved.
Xwayland source content and all Xwayland profile values are unchanged.

## Validation

Build and browser freshness checks passed. All 59 preseed files passed, including
private debconf read-back of all four generated command values. All 709 parser
checks across 349 shell sources passed using dash, bash and the official BusyBox
1.35.0 x86_64 musl binary. No executable was compiled or added to the source tree.

The focused permission/browser/NFS/provenance suite ran 77 tests: 70 passed,
and seven were skipped. Five native ownership tests could not establish foreign
UID fixtures; the native systemd condition checker could not initialize, and the
AppArmor parser was unavailable. The new home permission regressions exercised
real find/chmod behavior, symlink boundaries and fatal error propagation. Their
mixed-ownership fixture substitutes only the UID predicate and guards protected
paths with EPERM; it is not a native immutable-flag acceptance test. Real
file-descriptor copying, atomic publication, collision handling and failure
cleanup also passed using separately labelled simulated ownership. The real Git
checkout test used a local transport fixture, without GitLab authentication.
All 15 module, source-mode and publication contract tests passed on this tree.
All ten NFS profiles passed the target-policy preflight.

The whole codebase audit completed with zero explicit failures: 601 passed syntax
checks, 224 systemd structure checks, 159 blocked Perl dependency checks, 11 blocked
tool checks, 616 inventory-only records and 11 templates requiring rendering.
Structure, inventory, blocked and unrendered checks are not runtime passes.

The broad suites remain **not green**. With the same Python runtime, BusyBox and
validation environment, a fresh extraction of the uploaded ZIP previously ran
3224 installer tests with 696 failures, 331 errors and 186 skips. The prior
delivered tree ran 3238 tests with 676 failures, 330 errors and 190 skips. This
corrected tree ran 3245 tests with 675 failures, 331 errors and 191 skips. Subtests
contribute multiple failures. All three trees ran 217 tools tests with the same
three failures and 74 errors. Comparing failing test identifiers with the prior
delivery, while ignoring shifted line numbers and generated temporary directory
names, found no new failing identifiers. Unrelated source/test repairs and test
suppression were not introduced to conceal these results.

No live Forky/systemd 261.2 installation, private GitLab authentication, browser
extension installation/import, hardware boot, NFS service activation or enforcing
AppArmor acceptance was performed. This archive contains the implemented fixes
and reproducible build products; it is not a claim of full production acceptance.
Run the project gates on the deployment host and publish the complete checked
repository with an atomic directory switch.
