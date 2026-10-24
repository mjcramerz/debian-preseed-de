# Waycal right-click toggle with five-second lifetime

## Current interaction

This implements the user's later October 24 right-click/five-second request.
The earlier [hover/outside-click investigation](waycal-hover-20261024.md)
remains historical; this change makes no claim that those events are supported.

Both Waybar layouts bind the native clock's `on-click-right` to the fixed
command `/usr/local/libexec/labwc-waycal-control toggle`. No right-release
command is set, so a single click dispatches one toggle. The left-click native
GTK calendar menu and single clock format are retained; tooltips remain off.

| State at the serialized request | Result |
| --- | --- |
| No popup service loaded | Request one five-second popup |
| Popup active, activating or reloading | Request stop; do not extend or restart its timer |
| Popup deactivating | Acknowledge its pending stop |
| Popup inactive/failed but not collected | Treat as closed; do not replace/reset it |
| Popup collected | A later click can open a fresh five-second popup |
| Persistent/unrelated unit at the popup name, external Waycal owner or invalid session | Return unavailable without taking over that process/unit |

Right-click can close early. It does not pin the calendar open indefinitely.
Escape remains Waycal's own early-close action.

### Status against the original hover goal

The timed interaction above implements the later right-click request. It does
not complete the original hover/outside-click goal. A source review of this
working tree confirms the following boundaries:

| Original requirement | Current evidence | Status |
| --- | --- | --- |
| Open actual Waycal after 1,500 ms of continuous clock hover, cancel on early leave | Both clock entries have the right-click callback and no hover event provider or cancellable hover timer | Unimplemented |
| Right-click no longer opens Waycal | Both clock entries explicitly invoke `labwc-waycal-control toggle` on right-click, as requested in the later instruction | Original requirement not met by the later interaction |
| Dismiss on every click outside the clock/calendar, preserving clicks within either area | No input bridge, protected-region geometry or outside-click handler is installed; termination comes from the timer, toggle or Waycal's Escape handling | Unimplemented |
| Correct pointer timing, mixed-output geometry, restart and session cleanup | The controller requests session/cgroup ownership; no disposable native desktop result exists | Unverified |
| Preserve native left-click menu and private two-app Xwayland policy | Source retains the left-click menu and changes no Xwayland paths | Source inspection only; runtime regression gate remains open |

The [earlier investigation](waycal-hover-20261024.md#evidence-guiding-the-remaining-implementation)
records the reviewed upstream event limitations and unsuccessful no-compilation
bridge routes. A transient service supplies process ownership and termination;
the missing clock events and protected outside-click information still require
a supported native interface. No compatible prebuilt provider was established.
These capability gaps remain open independently of the timed toggle's native
acceptance gates below. Neither interaction has been demonstrated in a target
desktop, and the original goal must not be marked complete from this receipt.

## Service lifetime and cleanup

The controller requests the fixed transient user service
`labwc-waycal-popup.service` using `systemd-run --user --collect --no-block`.
The service command is an explicit argument array, with no shell:

```text
/usr/bin/timeout --signal=TERM --kill-after=1s 5s /opt/waycal/waycal --week-start monday
```

The countdown and Waycal process belong to the service's cgroup. No detached
sleep job later targets the shared unit name or a recycled numeric PID. GNU
timeout forwards termination to its owned process group, waits for its child,
and exits when the child exits. Waycal closing early therefore ends that
supervisor and its timer. The controller only invokes fixed manager clients;
it does not own the popup process tree.

The [GNU implementation](https://github.com/coreutils/coreutils/blob/master/src/timeout.c)
defines 124 for ordinary expiry and separate failures for invocation/internal
errors and forced termination. `SuccessExitStatus=124` makes ordinary expiry
clean completion; other failures retain their error status. GNU timeout is a
prebuilt coreutils program, not software compiled for this task.

The service additionally requests:

- `Type=exec`, `ExitType=main`, `KillMode=control-group` and `Restart=no`.
- `RuntimeMaxSec=6s`, `RuntimeRandomizedExtraSec=0` as an independent supervisor
  backstop; `TimeoutStartSec=10s`, `TimeoutStopSec=1s`, `SendSIGKILL=yes`.
- `Requisite`, `After` and `PartOf` for `labwc-session.target`, the desktop-owner
  condition and rejection of the closing-session marker.
- Private user, temporary, IPC and network namespaces; `ProtectSystem=full`;
  native Wayland environment and the existing Waycal AppArmor attachment.
- Existing CSS/state paths and graphics-device access. The binary's own
  layer-shell placement remains in use; no unsupported `--popup` is supplied.

Systemd [documents the runtime backstop](https://www.freedesktop.org/software/systemd/man/262/systemd.service.html#RuntimeMaxSec=)
as failure termination, and [control-group cleanup](https://www.freedesktop.org/software/systemd/man/262/systemd.kill.html#KillMode=)
as covering the unit's processes. Normal five-second expiry is handled by the
supervisor first. The extra second is an allowance for forced cleanup of an
unresponsive process, not an additional normal display interval. The six-second
backstop is measured from service activation, and the five-second countdown
from payload launch. Neither is a Waycal window-ready notification. Exact
visible duration, startup latency and shutdown latency remain unmeasured.

The helper retains its private mode-0600 no-follow lock, inode checks, bounded
manager output, twelve-second shared client-operation deadline and separate
one-second client cleanup budget. Toggle resolves inside that lock. If expiry
collects the unit between the initial read and a failed stop request, a read-only
state reconciliation can confirm it closed. It never retries the mutation or
starts a replacement in that request. Unreadable or still-active state remains
outcome-unknown.

An existing application bus owner outside the popup unit is rejected before
launch, to avoid GApplication activating a window outside the cgroup. An
independent same-UID launcher can still race this preflight; the controller is
not an adversarial same-UID security boundary.

## Installer and fixture integration

`components/target-assets.sh` stages the helper at mode 0755. The matching
AppArmor profile permits its fixed systemd/bus clients, runtime socket metadata
and lock. Waybar's existing profiled-helper transition reaches this profile;
the user manager launches the timeout supervisor, whose child enters Waycal's
existing profile. These policy transitions are source review, not loaded-policy
acceptance evidence.

The existing offline audit in `scripts/desktop/verify.sh.tmpl` now requires the
exact clock toggle command, rejects a release-binding conflict, and includes
the packaged timeout/systemd clients in executable/ownership checks. The audit
is not reactivated during installer late-command. Existing firstboot/helper
path checks retain the new controller name. No login-start unit is added.

Focused fixtures were updated for:

- Both clock layouts and the exact toggle command, with native left menu.
- Absent/active/stopping/collecting toggle states and a fresh opening after
  collection.
- Expiry racing a stop request, failed/readback-unknown outcomes and no retry.
- The CLI's shared lock and descriptor release.
- Service namespace, timer, success-status and cleanup arguments.
- Rejection of missing/wrong/double-dispatch clock callbacks by the actual
  native-menu verifier fixture in both skeleton/account copies and layouts.
- An older Tomat/menu fixture that still expected the clock menu on right-click;
  it now agrees with the existing left-click menu contract.

All authored fixtures remain **unexecuted**. No approved disposable Forky
environment has been established. No host fallback is permitted by
`AGENTS.override.md` or `docs/test-isolation.md`.

## Acceptance and artifacts

Only source/data inspection is permitted here. No controller, fixture, manager,
D-Bus operation, GUI client, native policy parser or syntax runner was executed.
No compilation or build command ran for this revision. The independent review
agent failed to initialize and supplied no review evidence.

Native acceptance still needs a disposable Forky/systemd 262 desktop with its
own packages, compositor, user manager, sockets and loaded policy. Exercise:
first right-click, second click before expiry, click exactly at expiry, rapid
clicks, reopen after collection, Escape, binary/startup failure, hanging process
cleanup, bar/session shutdown and the preserved left-click menu. Measure actual
window appearance/disappearance and verify the cgroup is empty after closure.
Record the image/package identities and current rendered inputs with results.

The user's no-build instruction remains in force. The three generated payload
products and both root inventories are **stale** relative to current sources.
The existing archive lacks the new controller and still contains the retired
static launcher files. This source revision has not been deployed.

### Static source receipt

Base revision: `74ed52c4e8aa8121a335733166cc6170b2e1b80b` on `mcr/main`.
The worktree was clean at the beginning of this task; these are uncommitted
changes. Payload-source fingerprint:
`da7fd21467c140286f585270c4d86218181517ab469ddbd6f5ad64c31e8d5d59`.
Focused-fixture fingerprint:
`33988f7fe46ac33828122780c9c144f13681f0c9ac725b30e9059159ec231667`.
Each group hashes its sorted paths listed below: path plus NUL, `present` plus
NUL plus current file bytes (or `absent` plus NUL for a removed path), then
NUL. Documentation, generated products and source filesystem modes are excluded.

An inline `/usr/bin/python3 -I -B` standard-library data-inspection script:

- Parsed the controller and all three changed fixture files with `ast.parse`.
- Parsed the native-menu and rendered-runtime verifier Python blocks as ASTs.
- Parsed both Waybar JSON templates with numeric stand-ins for unrelated
  installer/theme tokens. It confirmed the exact right-click toggle, native
  left menu, disabled tooltip, single format and absence of release/unsupported
  hover callbacks.
- Inspected the controller's AST string data for the exact five-second command,
  six-second manager backstop, success status and cgroup cleanup properties.
- Read staging sources as data to confirm mode 0755 and absence of the retired
  helper/static units from source.
- Recalculated the unchanged generated-product hashes below.

None of those source/fixture/verifier modules was imported or executed.
`git diff --check` returned exit status 0 after the code changes. The inspected
clock diff against the base revision changes only its two right-click commands.
This establishes static source consistency, not a passing fixture or native
runtime result.

| Existing generated product | Bytes | SHA-256 |
| --- | ---: | --- |
| `d-i/forky/payload.tar.gz` | 26621010 | `29dcbd3a335bff287621d9aca493bc8b273a4f1898f6b75b3d09a2edfbe1dabc` |
| `d-i/forky/payload.manifest` | 226692 | `50b7841b7a3c44a5f495e60e8e0a8e19619407e8e02f5c1ea447ddb85abf3185` |
| `d-i/forky/preseed.cfg` | 96407 | `e8aadfab0093357619961d4848eba33b35dc834b4e50581c6d3a4bfbdf2f3582` |

### Changed paths

Current payload-source changes, including the retained transient foundation:

- `d-i/forky/hooks/target/usr/local/libexec/labwc-waycal-control` (new)
- `d-i/forky/hooks/target/usr/local/libexec/labwc-waycal-toggle` (removed)
- `d-i/forky/hooks/target/etc/skel-desktop/.config/systemd/user/labwc-waycal.service` (removed)
- `d-i/forky/hooks/target/etc/skel-desktop/.config/systemd/user/labwc-waycal-toggle.service` (removed)
- `d-i/forky/hooks/target/etc/skel-desktop/.config/waybar/config.tmpl`
- `d-i/forky/hooks/target/etc/apparmor.d/calendars`
- `d-i/forky/scripts/desktop/components/target-assets.sh`
- `d-i/forky/scripts/desktop/verify.sh.tmpl`
- `d-i/forky/scripts/firstboot/04-validation.sh.tmpl`

Fixture changes:

- `d-i/forky/tests/test_native_menu_contract_20260920.py`
- `d-i/forky/tests/test_native_menu_verifier_20260922.py`
- `d-i/forky/tests/test_native_tomat_20260920.py`

Documentation: this report, `docs/calendar-and-wifi.md` and the superseded
`docs/validation/waycal-hover-20261024.md` report. The previously generated
`d-i/forky/payload.tar.gz`, `payload.manifest` and `preseed.cfg` remain changed
from the earlier serialization; they were not regenerated for this revision.
