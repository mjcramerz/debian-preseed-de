# Workspace broker and native window switcher

## Scope and status

This change implements the three requested desktop features: workspace-local
application grouping with real icons and raised counts, a Perl-authoritative
user-session broker with a narrow Python Wayland driver, and labwc-native
current-workspace Alt+Tab. It does not change application launch isolation,
shutdown/restore descriptors, the workspace selector, or the existing launcher
drawer. No compositor, panel, language extension or other native component is
built by this implementation.

The five supplied research reports are design inputs. The mixed Perl/Moo report
and modern window-switcher report take precedence. Three findings refine the
reports rather than silently accepting their assumptions:

* GTK3 CSS can render an actual icon-theme image on a stock Waybar custom
  label. A glyph substitution is not necessary for this implementation.
* This repository's session target has `DefaultDependencies=no`. Its established
  client-after-target lifecycle must be preserved, not replaced with the normal
  target ordering assumed by parts of the research.
* A focus-preserving `SendToDesktop` can move a window without a fresh foreign
  toplevel activation event. Following a move does not guarantee that an external
  client can relearn its workspace. Ambiguous observations remain unknown.

Implementation and headless validation are complete in the delivered sources.
A fresh Debian desktop installation, actual PyWayland/Moo imports, and live
AppArmor-enforced Wayland acceptance remain deployment gates; see
`WORKSPACE-BROKER-VALIDATION.md` for exactly what was and was not run.

## Authority and process layout

```text
systemd --user
  labwc-session.target (existing lifecycle boundary)
    labwc-workspace-broker.service
      MainPID: labwc-workspace-broker (Perl/Moo)
        semantic State -> Policy reducer
        grouping, UNKNOWN membership, counts, slots, snapshots, authorization
        readiness, watchdog, child supervision, bounded Unix IPC
      child: labwc-workspace-wayland-adapter (Python/PyWayland)
        registry and live proxies
        raw workspace/output/toplevel observations
        protocol done boundaries and sync fences
        four fixed outbound requests; no grouping or UI policy

Waybar -> labwc-workspace-broker-client (Perl)
          -> broker control socket
          -> labwc-fuzzel only for a multi-window/overflow selection

Alt+Tab -> labwc native switcher (never broker, Fuzzel or external capture)
```

There is one service and one logical failure domain, not independently restarting
Perl and Python services. The Perl `State` is a strict Moo/MooX constructor with
Type::Tiny-checked attributes and explicit methods. Its pure Perl `Policy`
reducer is intentionally separable for compositor-free testing. Python retains
all PyWayland proxies and reports observations; it cannot assign workspace
membership, canonicalize applications, allocate slots or render badges.

Installed files are application-private and Python-minor-version neutral:

```text
/usr/local/libexec/labwc-workspace-broker
/usr/local/libexec/labwc-workspace-wayland-adapter
/usr/local/bin/labwc-workspace-broker-client
/usr/local/lib/labwc-workspace-broker/perl5/Labwc/WorkspaceBroker/*.pm
/usr/local/lib/labwc-workspace-broker/python/labwc_workspace_wayland/*.py
/usr/local/lib/labwc-workspace-broker/PROTOCOL-LICENSES.txt
/etc/skel-desktop/.config/systemd/user/labwc-workspace-broker.service
```

The desktop role supplies `perl`, `libmoo-perl`,
`libmoox-strictconstructor-perl`, `libtype-tiny-perl`, `libjson-pp-perl` and
`python3-pywayland`. Dependencies already in the role remain there; only missing
packages were added. No CPAN, pip, venv, runtime scanner or generated native
extension is used. Python entrypoints run with `-I -B`; Perl entrypoints use
`-T` and fixed library roots. The target verifier imports the actual Debian
modules and checks minimum labwc 0.20.2 and Waybar 0.15.0 versions.

## Workspace and grouping semantics

The ordering is deliberate:

```text
committed observations
  -> live tasks with known workspace
  -> current workspace
  -> exact canonical application identity
  -> stable application slots and exact workspace-wide counts
  -> output-local button visibility
  -> real icon and optional numeric badge
```

Workspace count remains the existing dynamic 1--12 setting. The broker follows
compositor objects, not names parsed from keys, shell commands or Waybar text.
`ext/workspaces` remains the selector. `group/apps` remains the launcher drawer.
Only native `wlr/taskbar` is replaced by `group/workspace-taskbar`.

Tasks group by exact application ID, with the existing deliberate aliases
`footclient -> foot` and `org.xfce.Thunar -> thunar`. No arbitrary lowercasing,
prefix matching or title matching occurs. Anonymous tasks receive separate
identities. A title change cannot change the application's group.

Slots are stable while the corresponding group exists; focus does not move
buttons under the pointer. Membership and slot generations change when needed,
not for every title update. Removing a group does not compact all following
slots. Slot zero is an overflow selector for remaining known current-workspace
windows, with application/output labels and bounded pagination. It is not a
second global taskbar and does not discard windows beyond the visible slots.

On multiple monitors, a button is visible only where at least one group member
is reported on that output. Its badge and picker count all members of that
application on the current workspace, including members on other outputs.
The same slot always identifies the same workspace-local group across bars.
The chooser is deliberately workspace-wide, not guessed from pointer focus.

### Clicks and counts

| Live group size | Display | Left/right click | Middle click |
| --- | --- | --- | --- |
| 0 | Hidden | No action | No action |
| 1 | Real icon, no count | Minimize active window; otherwise unminimize/activate | Request close of that window |
| 2--99 | One real icon plus exact raised number | Choose one window, then activate | Choose one window, then request close |
| 100+ | One real icon plus `99+` | Same chooser, exact count retained | Same close-one chooser |

The selected item from a multi-window picker is always activated, not toggled
into minimization. Closing never means closing the entire group. Sending a
request does not decrement counts or optimistically rewrite focus; later
compositor observations are the truth.

The picker uses the existing hardened `labwc-fuzzel` wrapper, dmenu index mode,
fixed argv, and sanitized stdin rows. Window titles never become shell commands,
file paths or authorization IDs. Duplicate titles are harmless. Immutable
snapshots hold opaque task tokens; a numeric result is mapped back to that
snapshot and revalidated against the live epoch, workspace, group and task.
Escape, nonzero exit, malformed output, stale selection or timeout means no
window action. A picker has a 60-second broker lifetime, a shorter client
execution budget, and 128-row pages with navigation. The task bound is 1024.
Picker child process groups are terminated and reaped without scanning or
signaling application processes.

### Protocol limitation: important, not a hidden fallback

These Wayland protocols expose workspace state and toplevel state separately;
they do not publish an authoritative arbitrary-window-to-workspace relation.
A fresh positive activation can teach the broker membership when a unique
committed workspace is known. Creation alone cannot. Unknown tasks are retained
for diagnostics but hidden from groups, counts and pickers.

Python honors manager/toplevel `done` boundaries and two quiet asynchronous
sync fences before Perl commits a cross-protocol batch. Fences prevent applying
partially delivered observations; they do not invent missing workspace data.
Fresh activation evidence and the final unique active task are checked when a
batch also changes workspace. A cached active bit is not enough to move a task
into the new workspace.

Consequences to expect:

* Newly focused ordinary windows are learned and grouped as observations arrive.
  An unfocused background-created window can remain hidden until activation.
* After broker restart, inactive preexisting windows are unknown until activated.
  No persistent Wayland IDs or guessed restoration map is loaded.
* A focus-preserving move with no new activation can become ambiguous and hide
  the moved window until it is activated again. Existing follow behavior is
  preserved, but immediate external membership discovery is not promised.
* Unobservable moves of inactive windows, no-follow moves, sticky windows and
  unusual application/compositor focus behavior can leave a learned association
  stale. This is not an authoritative security partition between workspaces.
  Activate the affected window to refresh evidence; use native Alt+Tab to find
  windows that the broker cannot currently place.
* A nested compositor's externally exposed toplevel is what can be represented;
  this feature does not enumerate windows hidden inside another compositor.

The implementation does not claim exact membership for these missing-protocol
cases. It never enables a global unfiltered fallback to conceal the problem.
The native switcher has compositor-internal workspace knowledge and does not
share this limitation. "Isolated workspace taskbars" describes presentation;
it does not stop, freeze, sandbox or otherwise isolate application processes.

## Real icons without modifying Waybar

Waybar custom modules remain labels. Their trusted CSS background is an actual
GTK icon-theme image, normally resolved from the system desktop entry under
Papirus-Dark. The label contains a zero-width marker for the one-window case and
a trusted Pango raised span for counts. Icon and badge are one click target.
This is a raised numeric badge, not a separate circular overlay widget.

`Icons.pm` reads bounded root-owned, non-group/world-writable desktop metadata
from `/usr/share/applications` and `/usr/local/share/applications`. It reads
Name, Icon and StartupWMClass, never executes desktop `Exec`. Safe icon names
use `-gtk-icontheme`; accepted absolute images are limited to system icon/pixmap
roots. Application IDs and titles cannot inject CSS: selectors use opaque
SHA-256-derived names and values are validated. Unknown/unsafe metadata gets a
real generic application image, not a font glyph. Per-user or arbitrary `/opt`
icon files are deliberately not read. New system application metadata can be
found on first use; restart the broker after changing an already cached entry.

The panel launcher asks the rootless client to prepare a runtime stylesheet
which imports the existing user style followed by bounded generated icon CSS.
The icon file exists before Waybar installs its recursive style monitors and
is rewritten under a lock without replacing its inode, matching Waybar 0.15's
change-complete notification behavior. Configuration enables style reload.
No new process is spawned per property update. The existing palette and icon
sizes are reused. The new taskbar's active/hover styles retain icon geometry
and a readable amber background rather than allowing background shorthand to
reset the real image dimensions.

Counts 2--99 are internally computed decimals in a fixed small, bold, raised
Pango span. Every application-controlled tooltip/name/title is normalized,
bounded and markup-escaped. Only these broker-rendered modules use
`escape=false`; arbitrary application text is never treated as markup.

## IPC, races and resource bounds

All IPC is local AF_UNIX beneath the validated, user-owned 0700 directory:

```text
/run/user/$UID/labwc-workspace-broker/
```

Public `control.sock` and private `adapter.sock` are 0600. Both sides validate
UIDs; the private adapter connection must match the exact supervised child PID,
not just the same user. Adapter instance tokens, protocol version and strictly
increasing sequences bind observations and commands to one driver lifetime.
Public clients cannot issue commands directly to Python.

Frames are strict UTF-8 JSON objects with a 32-bit network-order length, maximum
256 KiB and depth 20. Duplicate keys (including escaped equivalents), floats,
non-finite numbers, malformed types, excess properties and out-of-range values
are rejected. Event batches, queues, clients, watchers, pending commands and
picker snapshots all have explicit bounds. Slow or malformed public clients
are disconnected, not allowed to block compositor processing. A corrupt or
lost private adapter channel fails the entire service.

Files use ownership/mode checks, no-follow opens, regular-file and link-count
checks, close-on-exec and nonblocking opens before validation. Nonblocking opens
matter: a substituted FIFO must not hang the broker before its type is checked.
Same-UID peer checks are a layer, not protection against a fully compromised
same-user unconfined process or compositor. AppArmor provides the additional
local-domain restriction on managed processes.

Watchers retain the last emitted slot's epoch/workspace/membership generation
in a private lease. Clicks must present it; the broker also checks live state
and a short settling interval. A hidden bar must not erase another output's
visible lease. Picker decisions receive stronger immutable snapshot checks.
There is nevertheless no stock Waybar acknowledgment binding an action to the
exact last painted frame. A stalled GTK UI and an already advanced watcher can
still create a residual render/click timing gap. The implementation reduces this
with stable slots, leases, generations and rejection during transitions; it
does not claim a mathematical proof about unacknowledged screen contents.

## User-service lifecycle and confinement

`labwc-workspace-broker.service` is `Type=notify`; only Perl sends readiness,
status and watchdog notifications. It becomes ready after runtime validation,
authenticated child initialization, required protocol bindings, a committed
workspace snapshot and creation of the control socket. Child connection,
initial synchronization, heartbeat and command acknowledgment have deadlines.
A dead child, lost Wayland connection or failed initialization exits the parent;
systemd restarts the whole pair with rate limits. Shutdown terminates/reaps the
owned child; `KillMode=control-group` is the final service boundary.

This repository's existing session target deliberately disables normal target
default dependencies. The broker therefore follows the same `After`/`Requisite`
relationship to that target as established desktop clients. It is bound to the
compositor, `PartOf` the target, and ordered before Waybar and session restore.
Both dependents use `Wants` plus `After`, not `Requires`, so failed taskbar startup
must not make the other panel modules or application restoration fail. The
broker is included in the existing target-wants staging path. No target ordering
cycle is introduced.

The service has `NoNewPrivileges=yes`, no capabilities, AF_UNIX-only sockets,
restricted namespace/SUID/SGID behavior and bounded task/file/memory resources.
The Python child inherits the same narrow AppArmor broker domain via `ix`; it
does not require an NNP-incompatible profile transition. The ordinary Waybar
client has a separate profile and an explicit transition to the existing
Fuzzel domain. Reciprocal signals and Unix permissions are included in the
existing managed profiles. The broker cannot execute the picker or arbitrary
applications. There is no root daemon, Polkit action, inet access, ptrace or
application `/proc` discovery.

A user-namespace filesystem sandbox was not added to this user unit: remapped
root ownership would conflict with validation of trusted root-owned defaults,
code and desktop metadata. `PrivateUsers=no` and AppArmor filesystem rules keep
those checks meaningful. No executable-memory prohibition is imposed blindly
on libwayland/CFFI callback machinery. Live enforce-mode testing is still
mandatory; parsing policy is not proof that a real session has no denials.

`labwc-session-state` remains unchanged. Shutdown still considers real windows
on every workspace, including multiple windows behind one icon. Resume
metadata contains no task/group/badge/Wayland handles. Broker readiness before
restore is lifecycle ordering, not fabricated workspace restoration.

## Managed configuration

Change settings through the existing managed-default/rendering workflow, not
by editing generated slot commands. Defaults are in
`d-i/forky/hooks/target/etc/default/labwc-desktop.tmpl`.

| Setting suffix (prefix `LABWC_WORKSPACE_BROKER_`) | Default | Allowed |
| --- | --- | --- |
| `GROUP_SLOTS` | 24 | 4--64 |
| `PICKER_LINES` | 12 | 2--32 |
| `PICKER_WIDTH` | 64 | 24--120 |
| `TOOLTIP_WINDOWS` | 8 | 1--32 |

The visible badge cap is fixed at 99. Slot count is not workspace count. All
numeric inputs are validated by the installer and again when broker defaults
are read.

| Setting suffix (prefix `LABWC_WINDOW_SWITCHER_`) | Default | Allowed |
| --- | --- | --- |
| `STYLE` | `thumbnail` | `thumbnail`, `classic` |
| `ORDER` | `focus` | `focus`, `age` |
| `PREVIEW` | `yes` | `yes`, `no` |
| `OUTLINES` | `yes` | `yes`, `no` |
| `UNSHADE` | `yes` | `yes`, `no` |
| `OSD_OUTPUT` | `focused` | `all`, `focused`, `cursor` |
| `CYCLE_OUTPUT` | `all` | `all`, `focused`, `cursor` |

The workspace scope is fixed to `current`, identifier to `all`. Label format is
source controlled: application name, window title, state and conditional
multi-output name. It is not arbitrary XML supplied by an environment variable.
The existing theme override contains compact thumbnail geometry and a complete
classic column fallback without introducing a separate color palette.

## Native Alt+Tab

The primary path is entirely inside labwc. `A-Tab` and `A-S-Tab` invoke
`NextWindow` and `PreviousWindow` with `workspace="current"`; the default
candidate output scope is all monitors while the single OSD follows keyboard
focus. Thumbnail layout, icons, title/name/state/output metadata, focus order,
preview, outlines and unshade are configured explicitly. Classic mode retains
icon, desktop-entry name, state, output and title columns.

Modifier handling, reverse cycling, Escape cancellation, mouse selection,
live previews and scrolling large candidate sets remain the compositor's
implementation. No competing global keyboard grab, Fuzzel invocation,
screenshot cache or broker round-trip is inserted. Native Alt+Tab should remain
usable if the broker is stopped. Use classic mode as the supported fallback
for accessibility, software rendering or thumbnail/driver problems; do not
revert workspace scope to all.

## Publication and installation

After any payload change, use the existing publisher from the repository root:

```sh
python3 -B tools/build.py
python3 -B tools/build.py --check
python3 -B tools/check_preseeds.py
```

This publishes source/configuration payloads, not native software. Keep
`d-i/forky/payload.tar.gz`, `payload.manifest` and the generated `preseed.cfg`
pins together on the installation server. The delivered repository includes
the regenerated set. Do not publish a mixture of old and new hashes.

The explicit asset inventory stages all modules, entrypoints, protocol notices
and service files with root ownership and the intended modes. Target validation
checks module imports, versions, generated XML/JSON, managed module options,
entrypoints, private library directory modes and the existing account/unit
staging contracts before installation is considered successful.

Serving this new preseed affects new installations; it does not upgrade an
already installed user's home. For existing hosts, deploy the same complete
matching set of Debian dependencies, root-owned library/entrypoint assets,
defaults, rendered per-user configuration, target-wants links and managed
AppArmor policies through the site's normal configuration-management workflow.
Preserve unrelated user customization and existing permissions. Load the
updated policies and use a fresh desktop session after the complete deployment,
not an intermediate half-updated live panel. This change intentionally does not
add an ad hoc privileged in-place migration program.

Useful checks from the installed desktop user's own session:

```sh
systemctl --user status labwc-workspace-broker.service
journalctl --user -u labwc-workspace-broker.service -b
/usr/local/bin/labwc-workspace-broker-client diagnose
```

Diagnostics provide bounded structural counts and readiness, not a dump of
sensitive window titles. Root execution of feature entrypoints is refused.
Changing the root-owned defaults requires the normal administrator workflow;
the service itself never gains privilege.

## Primary-source references and protocol provenance

The supplied reports remain the specification context. Implementation-specific
verification used these upstream/Debian sources:

* GTK3 CSS overview, including icon-theme images and stylesheet imports:
  https://docs.gtk.org/gtk3/css-overview.html
* Waybar 0.15.0 custom module, command execution and style monitoring:
  https://github.com/Alexays/Waybar/tree/0.15.0
* labwc configuration, action and theme manuals:
  https://labwc.github.io/labwc-config.5.html
  https://labwc.github.io/labwc-actions.5.html
  https://labwc.github.io/labwc-theme.5.html
* Debian Forky labwc package:
  https://packages.debian.org/forky/labwc
* PyWayland 0.4.18 client/protocol-core definitions:
  https://github.com/flacjacket/pywayland/tree/v0.4.18
* ext-workspace-v1 XML, wayland-protocols 1.47, and foreign-toplevel-management
  XML as identified in `PROTOCOL-LICENSES.txt`.

`tools/workspace_broker_protocols.py` deterministically emits the small static
Python protocol surface from a reviewed wire table. `--check` verifies that the
checked-in source matches that table. It is development tooling, not an
installer or service action. Protocol versions, opcodes, signatures, nullability
and copyright/permission notices are recorded. The SHA-256 recorded in the
notice is the wire-table hash, explicitly not a fabricated downloaded XML hash.
PyWayland's `_gen_c()` constructs CFFI interface metadata using the packaged
library; it does not invoke a compiler. No upstream package binary or font file
has been added to this repository.
