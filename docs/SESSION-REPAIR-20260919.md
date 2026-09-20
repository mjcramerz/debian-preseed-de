# Debian desktop session repair - 2026-09-19

## Release status and scope

This is the complete revised source tree derived from `debian-preseed-de(3).zip`,
not a patch-only package. The installer payload, manifest and pinned generated
preseed have been rebuilt together. Unrelated source files are retained.

**This is not certification that every supplied failure has been eliminated.**
The deterministic repository defects below have targeted corrections and tests.
The DRM EBUSY, input-device errors and some upstream desktop diagnostics remain
unresolved or require target-hardware verification. No real unattended install,
GPU session, suspend/resume cycle, visual pixel-alignment test, or enforced
AppArmor workload was executed in this container. The complete test suite is not
green; see the recorded exceptions and evidence below.

## Implemented changes

### Main menu, cancellation and geometry

Releasing `Super_L` alone launches `labwc-main-menu`; the existing `W-d`,
`W-space` and `C-A-space` search bindings remain search bindings. The existing
categorized menu, GIO desktop-entry resolution and fixed-argv launch boundary
are retained.

Fuzzel's native dmenu cancellation status is 2, while the managed picker API
uses 1 for cancellation and 2 for failure. The wrapper now translates native
2 to managed 1 and native 1 to managed 2. It preserves other statuses and does
not reinterpret launcher-mode statuses. Genuine configuration, execution and
Wayland failures are not converted into cancellation. Verification requires
Fuzzel >= 1.11.0, the release introducing this native cancellation convention.
Existing termination/reaping and private temporary-file cleanup remain active.

All 13 host profiles explicitly define these additional settings, copied from
the corresponding application-search values:

```text
LABWC_FUZZEL_MAIN_MENU_WIDTH
LABWC_FUZZEL_MAIN_MENU_LINES
LABWC_FUZZEL_INTERNAL_MAIN_MENU_WIDTH
LABWC_FUZZEL_INTERNAL_MAIN_MENU_LINES
```

The production renderer creates `main-menu.ini` and `main-menu-internal.ini`.
They use the same base font, padding and line geometry as application search.
The categorized menu no longer inherits the compact management-dialog clamp.
Management pickers keep their existing compact settings. Width means Fuzzel's
character-based setting, not an invented pixel dimension; lines means its
configured visible row count. No `minimal-lines` option is introduced.

### Panel window switcher and Waybar controls

The panel helper still sends one F13 press/release with `wtype`; it does not
hold modifiers, create a permanent input process, or use an IPC broker. F13 now
opens labwc's native `client-list-combined-menu` instead of starting an
unmodified `NextWindow` cycling operation. The latter mode stops updating
pointer focus and does not dismiss itself on an outside click in the inspected
labwc source, explaining stale clicks being delivered to the previous Waybar
button. The native menu has outside-click/Escape dismissal.

Opening this list does not advance focus to the next window. It is a native
window list across workspaces, not the thumbnail cycling overlay. Alt-Tab and
Alt-Shift-Tab retain the existing thumbnail cycling behavior and filtering.
**An initially highlighted current-window row is not guaranteed by this change.**
That optional request would require a supported selection API or a separate
switcher implementation; the existing configuration does not supply one.

Both internal and external Waybar configurations use centered custom-label
alignment for the affected launch buttons. Wayscriber and the Applications
drawer use the intended bold icon-font selection. The microphone's icon span
uses an explicit Font Awesome family and an en-space before the percentage.
Existing launcher hover styles remain; additional information/control modules
receive visible hover background, border and inset feedback. These are rendered
configuration checks, not a claim of live optical centering at every scale.

### IOCost native paths and safe migration

When `IOCOST_CALIBRATE_ENABLE=true`, the installed files are:

```text
/etc/udev/iocost.conf
/etc/udev/iocost.conf.d/70-unattended-installer.conf
/etc/udev/hwdb.d/70-unattended-installer-iocost.hwdb
```

The configuration files are regular root-owned 0644 files; their managed
directory is 0755. The native main file is no longer a symlink to the old
`/etc/systemd` hierarchy. Both files are rendered from one validated profile
value. Native systemd IOCost reads the main file, not a drop-in merge, so editing
only the drop-in is not an active native override.

The transaction retains native hwdb compilation/query verification, target-only
execution, locking, stock-conffile backup/restoration, administrator-file
preservation and failure rollback. Reruns remove only metadata-checked,
installer-marked legacy assets and migrate the exact legacy compatibility
symlink. Administrator files are not adopted or deleted. The original enable
matrix is unchanged: the two flex Btrfs profiles enable deployment; eleven other
profiles deliberately leave it disabled. No storage benchmark or calibration
is run during installation. Existing IOCost tuning values were not changed.

### SSH unlock lifecycle

The supplied journal shows a startup pinentry timeout, followed by a successful
loader retry at 18:12:57. Login now activates the SSH agent socket without
automatically requesting private-key decryption. Use `git-ssh unlock`; the
existing `devops` path can also request unlocking. Exact installer-created
loader wants links are removed on installer reruns, while the service remains
available on demand. Encryption, host-key checks, the loader timeout and genuine
error propagation are retained. There is no passwordless conversion, broad
success-exit override, or log suppression. A user who ignores an explicitly
requested pinentry prompt can still cause a real timeout.

### Exact vendor desktop-entry repairs

The root-owned desktop-entry reconciliation path repairs only the observed
`lynis.desktop` Exec value, replacing shell-style single quotes with valid
Desktop Entry double quotes. It removes only the dangling `Edit` action from
`sdl-freerdp-file.desktop` when that action's group is absent. Existing valid
actions, administrator overrides and all unrelated entries remain untouched.
The normal desktop-file validation and atomic publication are retained; no
arbitrary shell interpretation or validation bypass is added. These repairs
were tested as transformations; the container lacked `desktop-file-validate`
for an independent native-validator run of the new fixtures.

## AppArmor event coverage

The supplied audit contains 122 `ALLOWED` missing-permission events in seven
normalized groups, and no `DENIED` events. `ALLOWED` here is not proof that an
enforce-mode profile permits the operation. Status/profile-load messages are
not failures. These exact groups now have policy coverage:

| Events | Domain and operation | Narrow permission added |
|---:|---|---|
| 43 | crowdsec firstboot opens `/` | root directory read, not recursive filesystem access |
| 18 | firstboot `ss`/`ps` reads desktop-wrapper process state | named-peer `ptrace (read)` plus reciprocal `readby` |
| 1 | greeter font discovery | read the TeX font tree |
| 1 | compositor icon discovery | owner-only read of user-local icon directory/tree |
| 2 | autostart examines home directory | owner-only home directory read, not home contents |
| 41 | calendar examines home directory | owner-only home directory read, not home contents |
| 16 | compositor receives wtype keymap FDs | owner-only read/write of `/tmp/wtype-??????` |

The wtype helper's corresponding temporary-file rule is narrowed to the same
six-character suffix. All 35 shipped top-level policy files compiled offline
with the available AppArmor parser. Named transitions, includes, menu actions
and Fuzzel cleanup signaling are covered by the integration suite.

**Profile modes were not globally changed.** The supplied profiles still select
`DESKTOP_APPARMOR_STATE="complain"`; existing fallback transitions were not
silently replaced. No `/** rw`, unrestricted ptrace rule, global unconfined
conversion, or denial-suppression rule was introduced. Exhaustive intended-use
coverage and a production enforce-mode rollout remain unproven without the real
applications and target kernel mediation. Offline parser acceptance is not
live authorization testing.

## Complete incident-family disposition

Line references below are physical lines in the supplied files, not generated
log timestamps or external documentation. Repeated messages are grouped.

| Input and lines | Event family | Disposition |
|---|---|---|
| ERROR 1-5, 8-9; journal 1067-1074 | GPG/pinentry timeout and failed SSH loader | Startup decryption request removed; explicit unlock retained. Needs login acceptance. |
| ERROR 6, 10; journal 1096-1098 | Fuzzel status 2 reported as failure; failed transient menu service | Native cancellation mapping corrected and regression-tested. |
| ERROR 7; journal 1182 | eDP-1 atomic commit EBUSY | **Unresolved.** No causal DRM trace or target GPU available. |
| journal 42-63 | event4 EVIOCSKEYCODE EINVAL | **Unresolved.** The stable device identity, matched hwdb properties and supported scancodes are not supplied. |
| journal 327 | Bluetooth identity file absent | No identity fabricated or key store overwritten. First-start/pairing behavior requires target verification. |
| journal 552, 591, 596, 624, 629-630, 697 | Tailscale missing initial state and warm-up health errors | Later log records show health becoming OK. Not treated as evidence of a persistent failure; no fake state files. |
| journal 770-771 | malformed Lynis desktop Exec quoting | Exact vendor-entry repair implemented. |
| journal 795 | FreeRDP declares absent Edit action | Exact dangling-action repair implemented. |
| journal 928 | netavark exits after 30 seconds of inactivity | Socket-service idle lifecycle, not a proven crash. No service restart loop added. |
| journal 971-972 | host Xwayland absent; labwc continues without it | **Diagnostic remains.** Host Xwayland is intentionally excluded; nested compatibility isolation is retained. A compositor build without host-Xwayland support would be a separate packaging change. |
| journal 1164-1177 | VS Code CLI warns while forwarding Electron/Chromium flags | Forwarding is explicitly reported; no launch failure established. Existing GPU/performance policy retained. |
| journal 1179-1181 | KWallet translation/parent-window/QWizard diagnostics | **Unresolved upstream/runtime diagnostics.** No encryption bypass or fake successful wallet setup. |
| journal 1198-1199 | ELAN touch jump discarded as kernel bug | **Unresolved.** Needs a device recording and kernel/libinput validation; no speculative global quirk. |
| apparmor 391-516, excluding STATUS records | Seven missing-permission groups | Scoped policy changes above; offline compiled, not live enforce-tested. |
| User's panel observations | wrong WIN action, menu size, sticky switcher, icon/hover issues | Configuration/lifecycle corrections above; visual and interaction acceptance remains. |

The existing compositor policy already disables direct scanout and uses its
software-cursor policy where configured. A single EBUSY message does not justify
claiming that a new AppArmor allow rule, blanket legacy-DRM mode, or speculative
kernel parameter fixes the driver. No such workaround was added.

## Validation evidence and limitations

Current evidence is under `validation/session-repair-20260919/`. The immutable
input was retained separately during investigation to reproduce existing test
defects; it is not substituted for the revised tree in this release.

Targeted successful checks include the 11 new incident regression tests (with
subcases), all 13 profiles through the real Fuzzel renderer, 37 IOCost tests,
40 categorized-menu tests, 36 navigation tests, 27 workspace/no-broker tests,
27 AppArmor/menu integration tests, 16 systemd resource-policy tests, and 33
profile-provenance/release tests. The historical workload hash fixture remains
unchanged; its test removes only the exact verified new geometry block before
comparing old workload bytes. All 282 shell files passed 575 parser checks. The regenerated snapshot/pins
passed `tools/build.py --check`; 59 preseed files passed native debconf format
checking and all four generated command values survived private debconf
read-back. The independent tool test suite passed. The whole-tree non-executing
syntax/security inventory passed (validation evidence is excluded from its
self-inventory).

The broader module sweep is **not an all-green release gate**. Its raw results
and subsequent checks are included rather than overwritten with a success
claim. Known limitations include missing historical audit input already absent
from the ZIP; an obsolete one-drop-in assertion; an existing subprocess mock
mismatch; four checks blocked by unavailable Perl Moo; and a signal-cleanup
fixture failure outside the changed code. Initial PyYAML/interpreter and current
profile-hash failures were corrected/retested without changing unrelated
production code. Isolated bootstrap/debconf retries distinguish parallel test
interference from installer failures. Consult the actual result files for final
outcomes, skips and counts; do not interpret a skipped test as passed.

The container cannot boot the supplied kernel on the laptop, run the Wayland
session, exercise Bluetooth pairing, or prove AppArmor enforce-mode operation.
No generated evidence claims those tests occurred.

## Deployment and acceptance

Deploy the complete repository tree to the existing serving location, including
its rebuilt `d-i/forky/payload.tar.gz`, `payload.manifest` and `preseed.cfg` as one
release. Preserve private initrd credentials outside the served repository.
Do not copy these templates directly over a running installation: normal
installer staging renders placeholders, sets ownership/modes and performs
transactional migrations. This release does not include a general live-system
upgrade tool.

On a disposable target installation, verify WIN-only versus search bindings,
menu dimensions on internal/external outputs, and every panel control after
repeated window-list open/cancel/selection. Test Waybar hover and 9%, 99% and
100% microphone values at the actual scale. Confirm Alt-Tab retains cycling.
Test cold-cache login, explicit `git-ssh unlock`, cancellation/retry and logout.
For an IOCost-enabled profile inspect both native paths, selected solution and
real device match; verify disabled profiles leave stock configuration alone.

For the remaining GPU/input issues, collect a fresh kernel/compositor journal,
stable udev information for the actual event device, and a libinput recording
covering the touch jump. Check GPU behavior with a supported kernel in a
controlled comparison before choosing a driver-specific fix. Event numbers are
not persistent hardware identifiers. Input recordings can contain sensitive
keystrokes; capture only the affected touchpad, review before sharing, and do
not publish private runtime logs in the served tree.

Before changing managed policies to enforce mode, exercise each intended
application and privileged workflow on a test host, inspect fresh AVCs and
review necessary additions. The supplied log alone does not establish all
future permissions an application might need.

## Primary implementation references

* Fuzzel release tags (1.11.0 cancellation semantics):
  https://salsa.debian.org/swaywm-team/fuzzel/-/tags
* labwc 0.20.2 cursor event handling:
  https://github.com/labwc/labwc/blob/0.20.2/src/input/cursor.c
* labwc native menus/actions:
  https://labwc.github.io/labwc-menu.5.html
  https://labwc.github.io/labwc-actions.5.html
* systemd v261 native IOCost configuration reader:
  https://github.com/systemd/systemd/blob/v261/src/udev/iocost/iocost.c

These references explain API behavior. The uploaded logs establish the incident;
they do not prove that an upstream defect has been repaired on the target.
