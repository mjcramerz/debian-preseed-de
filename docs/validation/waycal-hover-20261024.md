# Waycal 1.5-second clock hover — earlier investigation

The user's later October 24 instruction selects a right-click toggle with a
five-second automatic lifetime. See the
[current timed-toggle implementation](waycal-timed-toggle-20261024.md).
The implementation and source fingerprints below describe the earlier hover
attempt before that revision. Hover and outside-click behavior were not
implemented or accepted by that investigation.

## Requested contract

This request supersedes the earlier click mapping. Completion requires all of
the following in both Waybar layouts:

1. A continuous 1,500 ms pointer hover over the clock opens the actual Waycal
   calendar. Leaving before the deadline cancels the pending opening.
2. Right-click does not open Waycal.
3. A click outside the union of the clock button and calendar dismisses the
   calendar, including clicks on the desktop, other applications, other bar
   buttons and other outputs. A click within either protected area does not
   itself dismiss it. Moving from the clock to the calendar must remain possible.
4. Repeated entries, cancellation, display changes, bar restarts and session
   shutdown do not leave duplicate calendars, timers or input interception.
5. Native app launch and the existing private Zoom/Discord Xwayland boundary
   remain intact. The existing left-click GTK calendar menu remains available.

## Changes made

The fixed `labwc-waycal-toggle.service` right-click command is removed from
both clock entries in `config.tmpl`. The existing optional native-menu verifier
and focused contract fixture now require that key to be absent. Alternate
formatting and clock tooltips remain disabled.

The source now includes `labwc-waycal-control open|close`, installed at mode
0755, with a matching AppArmor profile and updated installer/firstboot file
checks. It requests one transient `labwc-waycal-popup.service`. The old
`labwc-waycal-toggle` helper, `labwc-waycal-toggle.service` and
`labwc-waycal.service` are removed from installer sources. No host files or
services have been changed. This is not an upgrade migration for an already
installed desktop.

The transient service executes the pinned binary directly:

```text
/opt/waycal/waycal --week-start monday
```

There is no `--popup` option in that release. Waycal retains its own top-layer,
top-anchored placement; the controller adds no positioning override.

The controller's source contract is:

- Require the desktop-owned Labwc session target, reject a closing session, and
  use `PartOf=labwc-session.target` for shutdown ownership.
- Use one fixed transient unit name, `Type=exec`, `ExitType=main`,
  `KillMode=control-group`, a ten-second start timeout, a five-second stop
  timeout, no restart and collection after exit/failure.
- Request `PrivateUsers`, `PrivateTmp`, `PrivateIPC`, `PrivateNetwork` and
  `ProtectSystem=full`. Keep native Wayland and GPU device access; retain the
  executable's existing AppArmor profile, CSS and state paths. Systemd 262
  documents unprivileged user namespaces as a prerequisite for these user-unit
  namespaces; actual target support is unverified. No weaker fallback is added.
- Serialize through one no-follow, mode-0600 runtime lock, with bounded lock
  waiting and inode revalidation. Validate unit metadata before targeting it;
  refuse persistent/unrelated collisions and opening a stopping/collecting unit.
- Before a new launch, query the fixed Waycal application bus name without
  service autoactivation. An existing owner is unavailable: GApplication could
  otherwise activate a process outside this cgroup. Same-UID independent
  launchers can still race the preflight; this is not an adversarial same-UID
  security boundary or proof of window ownership.
- Bound client output during reading and share a twelve-second operation
  deadline across manager operations, with a separate one-second child cleanup
  budget. Never retry an uncertain mutation. Exit 0 acknowledges the request
  or existing state, exit 2 rejects invocation, exit 3 reports unavailable and
  exit 4 reports an uncertain outcome. Acknowledgment does not prove visibility
  or completed termination.

The new helper is not yet called by any clock binding. **Hover opening and
outside-click dismissal are not implemented.** Bar/output-specific ownership
and event-bridge cleanup remain part of that missing integration.

## Evidence guiding the remaining implementation

The current entrypoint is
`hooks/target/etc/skel-desktop/.config/waybar/config.tmpl`. Both layouts use the
native clock and its left-click GTK menu. `scripts/desktop/components/target-assets.sh`
stages the credentials unit and helpers; `components/user-config.sh` copies the
Waybar, Waycal and user-unit trees to the account. The new controller requests
the popup as a transient unit. `scripts/desktop/calendar-install.py`
installs its pinned prebuilt 0.2.1 archive. The `waycal` profile in
`hooks/target/etc/apparmor.d/calendars` confines that installed binary.

The [Waybar 0.15.0 module implementation](https://github.com/Alexays/Waybar/blob/0.15.0/src/AModule.cpp)
handles native pointer entry and exit internally, but does not dispatch a
configurable enter/leave command. Its click/menu dispatcher cannot provide the
requested hover timer. The
[clock implementation](https://github.com/Alexays/Waybar/blob/0.15.0/src/modules/clock.cpp)
uses a GTK tooltip for its hover calendar text.

GTK3 explicitly documents
[`gtk-tooltip-timeout` as ignored](https://docs.gtk.org/gtk3/property.Settings.gtk-tooltip-timeout.html).
The [GTK3 tooltip source](https://github.com/GNOME/gtk/blob/gtk-3-24/gtk/gtktooltip.c)
uses different delays in ordinary and browse modes. Observing a tooltip and
adding another delay therefore does not establish 1,500 ms of continuous clock
hover. The earlier tooltip/accessibility adapter was not native acceptance
evidence for this request.

The pinned [Waycal implementation](https://github.com/ForrestKnight/waycal/blob/b9b5abd73fbaebf0756157ad141e509410ff181c/src/main.rs)
creates a separate top-layer window with on-demand keyboard input. It handles
Escape and navigation keys, but contains no outside-click or focus-loss
dismissal handler. Its layer surface does not automatically provide the
dismissal semantics of a parented popup. The
[layer-shell protocol](https://gitlab.freedesktop.org/wlroots/wlr-protocols/-/blob/master/unstable/wlr-layer-shell-unstable-v1.xml)
treats input regions, keyboard interactivity and parented popups as separate
contracts. Merely stopping the service on keyboard focus loss would also miss
clicks that never give keyboard focus to another surface.

These observations rule out treating a JSON hover key, tooltip-timeout setting,
or focus-loss wrapper as a complete implementation with the current binaries.
They do not prove that every possible integration has been exhausted. A native
event integration and explicit popup dismissal design still need implementation
and target acceptance.

The upstream [Waybar hover command proposal, PR #5312](https://github.com/Alexays/Waybar/pull/5312),
is still open in the reviewed public state. Its enter/leave command hooks must
not be assumed available in Waybar 0.15.0. The reviewed
[Waycal 0.2.1 release page](https://github.com/ForrestKnight/waycal/releases/tag/v0.2.1)
labels that release latest; its matching source has no `--popup` option.
No compatible prebuilt replacement was established by this bounded review.
The Debian web source listing could not be retrieved. A subsequent bounded
in-memory read of the official
[`waybar_0.15.0-1.debian.tar.xz` packaging archive](https://deb.debian.org/debian/pool/main/w/waybar/waybar_0.15.0-1.debian.tar.xz)
found exactly one listed patch,
`0001-fix-patch-paths-for-Debian-shipped-custom-modules.patch`; it contains no
hover/AModule changes. The archive was read as data without extraction,
installation, source execution or compilation. This was HTTPS source review,
not a signature-verification or installed-package acceptance result. It rules
out relying on an enter/leave backport in that reviewed Debian revision.

The repository's existing public APT metadata includes Waybar
`0.15.0-1+b1` and Labwc `0.20.2-1` candidates for amd64. These records are
stale inventory data, not installed-package evidence. The latest Waybar release
URL still resolved to 0.15.0 during review.

### Accessibility bridge review

The [GTK3 widget accessibility implementation](https://github.com/GNOME/gtk/blob/gtk-3-24/gtk/a11y/gtkwidgetaccessible.c)
exports focus, mapped-state and allocation changes; its state set does not
export the prelight changes used by Waybar's crossing handlers. An ordinary
AT-SPI object listener therefore does not establish actual clock entry/exit.

Newer [AT-SPI device code](https://github.com/GNOME/at-spi2-core/blob/main/atspi/atspi-device.c)
does have a pointer-moved API. Its
[Wayland accessibility-manager backend](https://github.com/GNOME/at-spi2-core/blob/main/atspi/atspi-device-a11y-manager.c)
requires compositor-side KeyboardMonitor/PointerLocator services and refuses
initialization without the required bus owner. No such provider was established
in the reviewed Labwc 0.20.2
[server](https://github.com/labwc/labwc/blob/0.20.2/src/server.c) and
[source list](https://github.com/labwc/labwc/blob/0.20.2/src/meson.build).
This review is not a live D-Bus capability probe. The legacy
[AT-SPI mouse event producer](https://github.com/GNOME/at-spi2-core/blob/main/registryd/deviceeventcontroller-x11.c)
uses X11 pointer queries; it is not evidence for native Labwc surface coverage.

GTK3's [Wayland coordinate implementation](https://github.com/GNOME/gtk/blob/gtk-3-24/gdk/wayland/gdkwindow-wayland.c)
uses a synthetic origin for a toplevel. Treating accessible screen coordinates
as global multi-output coordinates would not justify click-capture masks.
No accessibility bridge is installed on the strength of these incomplete
capabilities.

### Further no-compilation alternatives reviewed

The upstream hover proposal's reviewed head is abbreviated `9f3179d`.
Its [Linux run](https://github.com/Alexays/Waybar/actions/runs/39937563146)
was awaiting maintainer approval, with status `Action required` and no listed
artifacts. This is an external dependency, not a locally running process to
wait on or a binary acceptance result. The matching
[Linux workflow](https://github.com/Alexays/Waybar/blob/9f3179d/.github/workflows/linux.yml)
builds/tests but has no artifact-publication step. The reviewed
[smoke workflow](https://github.com/Alexays/Waybar/blob/master/.github/workflows/smoke.yml)
uploads screenshots and image directories, not its executable. This bounded
review established no downloadable hover-enabled binary from those routes.
No workflow was triggered, approved, built or downloaded for execution.

Labwc 0.20.2 does expose an `All` mouse context:
[`node_type_contains`](https://github.com/labwc/labwc/blob/0.20.2/src/common/node-type.c)
matches every node type, including layer surfaces. The
[cursor dispatcher](https://github.com/labwc/labwc/blob/0.20.2/src/input/cursor.c)
marks matching `All` press/click bindings as consuming the press event. A
release binding avoids that particular consumption, but does not by itself
provide the protected clock/calendar regions. Matching also requires the exact
button and modifier set; compositor menu/cycle modes have separate paths.

The [action implementation](https://github.com/labwc/labwc/blob/0.20.2/src/action.c)
passes only the configured command to `Execute`, after tilde expansion. It does
not pass cursor coordinates, the hit surface or its layer namespace. `If`
evaluates a normal view, and its default target for a null activator can be the
active view rather than the layer surface under the pointer. Therefore an
unconditional global close binding would also close on protected clicks, while
ordinary view-only bindings would miss other layer surfaces. Neither is the
requested outside-region contract. No compositor mouse binding was changed.

These additional reviews leave the same event-provider dependency unresolved.
A new maintained prebuilt interface or another verified supported runtime
interface is required before hover and dismissal can be integrated correctly.

## Proposed implementation requirements

The next implementation must receive the actual clock's pointer enter/leave
events and use one cancellable monotonic 1,500 ms timer. Keep Waycal's existing
placement. If a dismissal bridge needs geometry, it must obtain verified output
and logical clock/calendar bounds through a supported native interface.
An accessibility bridge remains an option only if the target compositor and
toolkits actually expose the required events and coordinates. Raw input access,
privileged input authority, guessed screen masks and Xwayland expansion are not
implemented substitutes.

The calendar needs an explicit dismissal mechanism that works before it has
keyboard focus and across all outputs. Any transparent click-capture surfaces
must exist only while the calendar is visible, exclude the clock and calendar
from dismissal, and be destroyed on dismissal, owner disconnect, output change
and shutdown. Such a design must specify whether the dismissing click is
consumed; forwarding input to unrelated applications is not implicit authority
to synthesize a second click.

Clock geometry and output changes must invalidate stale placement or input
regions. Opening once must not start a timer loop; dismissal while the pointer
remains over the clock must not immediately reopen it. IPC, if needed, must be
private to the session, bounded, versioned and tied to the actual owner lifetime.
Unknown launch/stop outcomes must not trigger automatic retries.

`AGENTS.override.md` expressly prohibits building software from source. The
user reaffirmed that restriction: nothing is to be compiled for this task,
and no further build command is to run. An earlier pure payload serialization
completed before that clarification; it compiled no software. The remaining
research is restricted to existing binaries and supported runtime interfaces.
The user's suggested transient service is a valid process-lifetime boundary,
but a service alone does not supply hover events or outside-click semantics.
The pinned Waycal source registers `--week-start`; it has no `--popup` option.
No unsupported option is added to the launch command. An approved disposable
Forky environment is also required for native acceptance; none has been
supplied or established during this work.

## Acceptance still required

The focused fixture now covers coalesced opens, stopping-unit refusal,
idempotent close requests, metadata collisions, external application ownership,
uncertain request outcomes, invalid display names, constructed namespace
properties, output limits, final-wait child cleanup and installer staging.
All of these authored fixtures remain unexecuted. Runtime-directory/lock
failure injection and target-native manager/policy/GUI acceptance also remain
open. No tests, native
syntax checks, policy parsers, display clients, host management helpers or
service managers were run. Static parsing and payload serialization cannot
prove pointer timing or dismissal.

Native acceptance must exercise: a short hover; a full hover; rapid leave and
re-entry; pointer movement within the clock; movement into the calendar;
clicks inside both protected areas; every mouse button and touchpad click
outside them; the background, other apps and bar buttons; multiple outputs,
mixed scale, rotation and hotplug; calendar/bar restarts; Escape; keyboard
navigation; session shutdown; failed startup; and removal of all interception
after each closure/failure. Record measured timing, image/package versions,
loaded policy, rendered configuration and exact source/artifact identities.

The full objective remains incomplete. The earlier source/artifact receipts
describe their earlier inputs and do not establish acceptance of this request.

### Current completion audit

| Requirement | Current authoritative evidence | Result |
| --- | --- | --- |
| Continuous 1,500 ms hover, canceled on early leave | Both clock templates have no hover entrypoint; reviewed Waybar 0.15.0 has no configurable crossing commands | Unimplemented |
| Remove right-click launch in both layouts | Both clock JSON objects omit the right-click command; static template inspection completed | Source change complete; live behavior unverified |
| Outside clicks dismiss; protected clock/calendar clicks do not | No native Waycal outside-click handler and no installed event bridge | Unimplemented |
| No duplicate calendars, stale timers or interception across restarts/output changes | Serialized fixed transient service exists in source; bridge/output/bar ownership is absent | Incomplete and unexecuted |
| Preserve left-click GTK menu and private Zoom/Discord boundary | Clock still uses its native left-click menu; no private Xwayland source changed | Source invariant retained; native regression acceptance unexecuted |
| Verify actual target behavior and current artifacts | No approved disposable Forky desktop established; generated products/inventories are stale | Missing acceptance evidence |

## Source and artifact receipt

Base revision: `74ed52c4e8aa8121a335733166cc6170b2e1b80b` on `mcr/main`.
The worktree was clean before this task's edits.

The earlier two-file source/fixture fingerprints recorded before controller
implementation are superseded. The current source receipt is recorded below;
it identifies uncommitted data, not an executed fixture or native acceptance.

Current payload-source fingerprint:
`43dcf15fd3a8f3a6145f8f1f0602b010d54ac72967f0a680c8426d39925d4310`.
Current focused-fixture fingerprint:
`00af25c8c1722ea7e9adaea549b78615b2309dc1e133dd0ba42ec28dbdf5274e`.
For each group, SHA-256 consumes sorted repository-relative path, NUL,
`present` plus NUL plus file bytes (or `absent` plus NUL for a removed path),
then NUL. The source group is the nine payload-source paths listed below;
the fixture group is its one listed test file. Generated products and docs
are excluded; source filesystem modes are not part of this byte fingerprint.

Current checks ran only source/data operations:

- `/usr/bin/python3 -I -B` with an inline standard-library data-inspection
  script parsed the new controller, focused fixture and optional embedded
  native-menu verifier using `ast.parse`. It imported/executed none of them.
- The same script parsed both Waybar JSON templates with unrelated unresolved
  installer/theme tokens replaced by numeric stand-ins. It confirmed the
  native left-click menu, disabled tooltip, absent alternate format and absent
  right-click/unsupported hover command keys in each clock. This is not a
  rendered target-config result.
- It read staging text as data: the new controller is explicitly installed at
  mode 0755; the retired toggle is not staged. Source review traced the existing
  firstboot path-presence loop, executable verifier and AppArmor transitions.
  None of these installer functions or policy parsers ran.
- It streamed the existing archive with member/expanded-byte limits and found
  1,839 members, 34,896,863 expanded bytes, both retired user units and the
  retired toggle helper. The current controller is absent. It recalculated the
  three artifact hashes shown below without extraction or execution.
- `git diff --check` returned exit status 0 after the code edits.

No controller command, fixture, host helper, manager, D-Bus operation or GUI
client was executed. The attempted independent agent review failed to start
because of a runtime context error; it provided no review evidence.

Before the user's later no-build clarification, the reviewed pure serialization
command `make build PYTHON=/usr/bin/python3` returned exit status 0 and reported
1,839 payload files. This command compiled no software and ran no validators or
tests. No build command has run after the clarification.

Static inspection immediately after that earlier serialization, using only
Python standard-library parsing and reading files as data, established for
that earlier snapshot:

- Both clock templates omit right-click and right-release launch commands,
  retain `menu: on-click`, and have no competing left-click command or alternate
  formatting. Unrelated unresolved tokens used numeric stand-ins for this JSON
  inspection; this does not prove rendered configuration acceptance.
- The changed fixture and embedded native-menu verifier Python parse as ASTs.
  Neither module nor the verifier was imported or executed.
- All 1,839 regular archive members, totaling 34,896,863 expanded bytes, match
  that snapshot's source bytes and manifest hashes. Member sets and normalized
  owner/mode/time metadata match. Inspection streamed the archive with explicit
  member and expansion bounds, without extraction or repository-code execution.
- The payload, manifest and bootstrap-source hashes embedded in `preseed.cfg`
  matched that snapshot's bytes. `git diff --check` returned exit status 0.

| Generated path | Bytes | SHA-256 |
| --- | ---: | --- |
| `d-i/forky/payload.tar.gz` | 26621010 | `29dcbd3a335bff287621d9aca493bc8b273a4f1898f6b75b3d09a2edfbe1dabc` |
| `d-i/forky/payload.manifest` | 226692 | `50b7841b7a3c44a5f495e60e8e0a8e19619407e8e02f5c1ea447ddb85abf3185` |
| `d-i/forky/preseed.cfg` | 96407 | `e8aadfab0093357619961d4848eba33b35dc834b4e50581c6d3a4bfbdf2f3582` |

**The three generated products above are now stale relative to the latest
controller/policy/staging sources.** The archive still contains the retired
static popup/toggle files and lacks the new controller. No serialization has
run since the user's no-build instruction.

Both root inventories still record payload hash
`6a370d066a9c7d7af4e97418b6a492a8487a160a078ec32eece0c4afabbbb128`
and size 26,621,075. They are **stale** relative to the current payload and were
not regenerated after the user's no-build instruction. No target image or
installed package identity was inspected. The target remains Forky/systemd 262
by repository contract; that is not evidence of any running deployment.

### Exact changed paths

- `d-i/forky/hooks/target/etc/skel-desktop/.config/waybar/config.tmpl`
- `d-i/forky/hooks/target/usr/local/libexec/labwc-waycal-control` (new)
- `d-i/forky/hooks/target/usr/local/libexec/labwc-waycal-toggle` (removed)
- `d-i/forky/hooks/target/etc/skel-desktop/.config/systemd/user/labwc-waycal.service` (removed)
- `d-i/forky/hooks/target/etc/skel-desktop/.config/systemd/user/labwc-waycal-toggle.service` (removed)
- `d-i/forky/hooks/target/etc/apparmor.d/calendars`
- `d-i/forky/scripts/desktop/components/target-assets.sh`
- `d-i/forky/scripts/desktop/verify.sh.tmpl`
- `d-i/forky/scripts/firstboot/04-validation.sh.tmpl`
- `d-i/forky/tests/test_native_menu_contract_20260920.py`
- `d-i/forky/payload.tar.gz`
- `d-i/forky/payload.manifest`
- `d-i/forky/preseed.cfg`
- `docs/calendar-and-wifi.md`
- `docs/validation/waycal-hover-20261024.md`
