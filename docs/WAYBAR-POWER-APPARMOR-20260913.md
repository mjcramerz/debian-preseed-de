# Waybar keyboard, power lifecycle, and AppArmor fixes

Date: 2026-09-13

## Delivery and scope

This is the complete `debian-preseed-de` repository, not a patch-only delivery.
All 1,562 files in the uploaded ZIP remain present. Thirteen existing installed
source/configuration files were edited, together with the three mechanically
regenerated publication files: `payload.tar.gz`, `payload.manifest`, and
`preseed.cfg`. New material consists of scoped regression tests, an audit
fixture, this report, a change manifest, and validation evidence. Unrelated
source files, package selections, boot/kernel configuration, and existing
AppArmor mode defaults were not changed.

The change manifest is `docs/CHANGE-MANIFEST-20260913-POWER-KEYBOARD.json`.
Existing executable/file permission bits are preserved. The published payload
contains 1,261 files and its hash pins match the regenerated preseed.

Input ZIP SHA-256: `1925597b0e29db2a65af1342b611f784e984677fc13c0c72b827743b1e332b0e`

Input AppArmor log SHA-256: `1ffcbaef9f857a927a7a6c2deacc9ba86330f323f9415c9d79204f53d8c7fb16`

## 1. Keyboard layout and Waybar refresh

The keyboard toggle now queues concurrent callers with a bounded, five-second
`flock` wait rather than silently dropping a click. The old 150 ms sleep is
30 ms. CLI `set`, CLI `toggle`, and Waybar toggles use the same lock and
completion path. US and Swedish (`se`, with `sv` accepted as an alias) remain
the supported layouts; their existing persistent state and labwc environment
fragment are retained.

After committing the state/environment update and successfully issuing
`labwc --reconfigure`, the helper releases the lock and invokes the existing
`labwc-system-action refresh-waybar-custom-module` action. Reconfiguration
failure restores the previous stored layout and returns an error instead of
reporting success. Offline configuration does not require a running compositor.
The refresh action has a direct, noninteractive path: it no longer opens a
maintenance terminal for this callback. Both Waybar keyboard definitions have
`exec-on-event` disabled, so the asynchronous click launch does not trigger a
premature read. Their RTMIN+7 update signal and 30-second fallback polling remain.

A second source defect was found in the actual signal path. `waybar.service`
runs `labwc-panel-run` as its main process; the generic helper signals that
supervisor, not the Waybar child. The supervisor now forwards RTMIN+7, RTMIN+8,
and RTMIN+9 to Waybar. Crystal Dock does not receive these additional signals.
Matching AppArmor send/receive rules cover both ends. For the Debian glibc
signal numbers 41, 42, and 43, AppArmor uses kernel-relative names `rtmin+9`,
`rtmin+10`, and `rtmin+11`, respectively.

The keyboard profile explicitly transitions into the existing system-action
profile. `systemctl` inherits that profile with explicit user/system bus access,
rather than an unconfined fallback. Read-only journal and cgroup/status metadata
permissions preserve the helper's existing status/timer display actions.

Completion here means the layout helper has committed state and the labwc
reconfiguration command has succeeded. Labwc's command sends a reconfiguration
request; it is not a protocol acknowledgment that a physical keyboard has
already produced a character using the new layout. The live acceptance check
below verifies actual input separately.

## 2. Power-action lifecycle

The existing menu/authentication architecture remains intact. Waybar dispatches
the power menu through a user service; `labwc-power-settings` and the logout
wrapper route requests through the authenticated admin helper. The fixed
self-logout Polkit path still delegates to the same root worker. No broader
Polkit authorization was added.

The system worker template is now `Type=notify` with `NotifyAccess=main`.
The root frontend waits for the worker's startup acknowledgment, rather than
merely enqueueing a job and reporting acceptance. Only the main worker emits
readiness, after acquiring its root-owned action lock and checking the target
session. The worker belongs to the system manager, outside the user slice it
will stop. Startup is bounded to 60 seconds and execution to 360 seconds.

Preparation remains an unprivileged user-manager service. It records approved
restart descriptors, then sends one normal Wayland close request to existing
windows. It does not simulate Discard buttons or repeatedly close newly created
save dialogs. An empty desktop, including background/tray services without
windows, advances immediately without the old application-service-liveness
wait. Remaining windows receive up to 120 seconds to resolve a save/close
prompt; unresolved windows cancel before destructive teardown. A failed window
probe is an error, not evidence of an empty desktop. Clipboard cleanup failure
is logged but no longer blocks an otherwise prepared session.

After preparation, reboot/poweroff recheck for other interactive accounts and
commit to teardown. The worker queues stops of the managed desktop target and
compositor, asks logind to terminate the invoking UID, and queues stops of the
UID's manager and user slice. If necessary, PID 1 sends TERM and then KILL to
the user's cgroups, with bounded waits. This avoids cross-profile `/proc`
scanning and direct `pkill` from the controller. Its previous broad ptrace,
signal-send, and CAP_KILL permissions are removed; only same-profile KILL is
needed to reap its own timed-out transport subprocesses.

Once teardown is committed, a failed individual stop, stale stop job, or
unexpected cleanup exception must not prevent the final reboot/poweroff request.
The worker performs bounded best-effort sync and submits exactly one `--force`
flag per `systemctl reboot` or `systemctl poweroff` request, with one bounded
retry on failure. It never uses double-force, `--no-sync`, SysRq, or a raw
reboot syscall. Failure after commitment stays in the system journal and does
not restart the user manager just to display a misleading save-dialog message.
Transport timeouts kill and reap their own process groups so an inherited pipe
cannot keep the controller waiting indefinitely.

Logout uses the same preparation/cleanup but never performs machine shutdown.
Suspend retains screen-lock readiness and the normal systemd sleep/GPU hook
path; it does not close applications or terminate the user manager.

**Forced-shutdown tradeoff:** one `--force` skips the normal all-units stop
transaction. PID 1 still performs final process termination and filesystem
unmount/read-only handling, but unrelated system services are not promised
normal `ExecStop` execution. User-session cleanup is attempted first, as
requested. Force cannot guarantee recovery from an unresponsive kernel or
uninterruptible hardware task. Applications that hide unsaved state, suppress
save dialogs, or run inside nested compositors cannot be generically inspected
for dirty documents through the outer compositor's window list. Such data can
still be lost during forced termination; no universal dirty-document detector
is claimed.

## 3. AppArmor incident coverage

The supplied log has 329 permission events, represented by 170 distinct tuples
of profile, operation, path, denied mask, and peer. Normal profile-load/status
messages are not permission defects and were not silenced.

| Observed source | Events | Scoped resolution |
| --- | ---: | --- |
| `managed-firstboot` execution failures | 2 | Permit `/usr/bin/printf` and the existing read-only `managed-nvidia-char-links --check` invocation. Add its Python runtime and read-only NVIDIA character-device validation paths. |
| Firstboot complain-mode `//null-` descendants | 313 | Resolve the missing parent execution rules and verify the recorded accesses against the real inherited firstboot domain. Do not create permissive null profiles. |
| `managed-session-controls` | 4 | Reciprocal compositor metadata-inspection permission for labwc-tweaks; owner-only capture PNG creation/truncation for grim. |
| `managed-desktop-launcher` | 7 | Read `/srv/` itself, not recursive service data. |
| `managed-waybar` | 1 | Read the package-owned Satty asset directory. |
| Bluetooth and capture callback wrappers | 2 | Read-only inherited battery telemetry fields in the shared desktop-wrapper abstraction. |

The normalized fixture is
`d-i/forky/tests/fixtures/installed-apparmor-20260913-power-keyboard.json`.
The new tests walk every recorded event and assert a corresponding source-level
fix. This matcher deliberately is not an AppArmor engine: it does not claim to
model every deny-rule interaction, mount namespace, kernel ABI, or future
application code path. The supplied log cannot establish coverage for operations
that were never exercised. Existing explicit security denials and mode defaults
are retained; no blanket file/network allowance or profile disabling was added.

## Validation performed

Detailed evidence is in `docs/validation/20260913-power-keyboard/`.

| Check | Result |
| --- | --- |
| New scoped tests | 34/34 pass. Repeated and overlapping real shell toggles, completion ordering, rollback, real supervisor signal forwarding, preparation/save-dialog branches, mocked power cleanup/force ordering, real disposable transport-timeout handling, readiness, menu routing, and all logged AppArmor events. |
| Selected existing regressions plus new tests | 263 tests run. The untouched upload runs the same 229 existing tests. Failure/error/skip identifiers match exactly; no new failing identifiers. |
| Inherited test failures | 13 stale host-profile provenance subtest failures, one missing historical audit-file assertion, and one error reading that same missing historical file. These are three affected test methods, not 15 independent regressions. The missing file is `todo/managed/apparmor/apparmor.log`, associated with earlier incident tests, not the new 329-event upload. |
| Inherited skip | One rsyslog parser test: `rsyslogd` is unavailable in the container. |
| AppArmor syntax/includes | All 34 policy files parse; 228 profile names. `apparmor_parser --names --skip-cache` exits before policy compilation/load. A preprocess check also exercised the session policy includes. |
| Systemd service definition | `systemd-analyze verify --man=no --generators=no` passes using a temporary copy with only the executable/condition paths relocated to the repository. No unit was started. |
| Shell syntax | 267 shell files, 545 parser checks, all pass. |
| Preseed | 59 files pass; all four generated command values survive private debconf read-back unchanged. |
| Publication | `tools/build.py` regenerates 1,261 payload files; `tools/build.py --check` confirms snapshot, hash pins, and preseed are current. Browser artifacts remain unchanged. |
| Source retention | Uploaded ZIP contents verified against the baseline; all original files retained. Edited originals are confined to the 13 source/configuration files and three publication products. |

A separate attempt at the entire pre-existing suite reached a 200-second tool
limit during `test_bootstrap_portability.TimeoutPortabilityTests.test_downloader_error_record_keeps_status_and_mode`.
It is not counted as a completed full-suite run. Native-compiler test cases were
excluded from that attempt, and no native compilation is part of the completed
selected suite.

No native binaries, DKMS modules, compositor/panel binaries, or AppArmor DFA
policies were compiled. The repository's `build.py` step packages files and
updates hashes; it is not a native software build. The container does not run
the target desktop or expose a usable AppArmor kernel interface. Actual reboot,
poweroff, suspend/resume, compositor input, and enforcing-kernel behavior remain
live acceptance tests, not reported successes.

## Reproducing the non-destructive checks

From the repository root:

```sh
python3 -B -m unittest discover -s d-i/forky/tests -p test_power_keyboard_20260913.py -v
python3 -B tools/build.py --check
python3 -B tools/check_shells.py
python3 -B tools/check_preseeds.py
python3 -B docs/validation/20260913-power-keyboard/run_selected_regressions.py . /tmp/labwc-regressions.json
```

The final command intentionally retains the original suite's failures; it is
not expected to produce an all-green result until those unrelated fixtures and
provenance records are repaired in a separately scoped task. Do not substitute
an unrestricted full-suite command when preserving the no-native-compilation
constraint.

## Publication and live acceptance

Publish the complete extracted repository atomically. Do not serve a new
`preseed.cfg` with an old payload/manifest, or copy only edited scripts while
leaving the pinned payload stale. Normal installer staging already installs
all affected helpers, the service template, the rendered Waybar configuration,
and these policy files; no parallel unstaged implementation was introduced.
Publishing this tree does not by itself upgrade already-installed machines or
rewrite their existing per-user Waybar configuration. Existing-host rollout
must update the same managed assets/configuration and reload the corresponding
policies/managers, followed by a fresh desktop session.

Use a disposable installed VM/session and saved test data first. Exercise the
keyboard button repeatedly and with closely spaced clicks on both Waybar
configurations; confirm the indicator and actual typed input both alternate,
and that Waybar's supervisor stays alive. Test an empty-desktop reboot/poweroff,
then background/tray-only applications, then an editor with an unsaved document.
A presented save dialog should remain usable and an unresolved dialog should
cancel before target teardown. Check logout separately and confirm suspend
keeps applications alive with the screen locked. Repeat these workflows with
the managed policies enforced using the repository's existing mode-management
workflow. Inspect the power-worker journal and new AppArmor permission events;
do not treat profile-load status messages as failures.

Useful read-only diagnostics on the installed test machine:

```sh
journalctl -b --user -u waybar.service
journalctl -b -u 'labwc-admin-action@*'
journalctl -b -k | grep 'apparmor='
```

## Primary technical references

The implementation was checked against the upstream Waybar custom-module
manual (`exec-on-event` and signal behavior), labwc's reconfiguration/environment
manual, systemd's force/shutdown and readiness contracts, and AppArmor's parser
and kernel signal mapping. The input code and incident log remain the basis for
the actual changes.

- https://raw.githubusercontent.com/Alexays/Waybar/master/man/waybar-custom.5.scd
- https://labwc.github.io/labwc.1.html
- https://labwc.github.io/labwc-config.5.html
- https://raw.githubusercontent.com/systemd/systemd/main/man/systemctl.xml
- https://www.freedesktop.org/software/systemd/man/latest/sd_pid_notifyf.html
- https://gitlab.com/apparmor/apparmor/-/raw/master/parser/parser_main.c
- https://raw.githubusercontent.com/torvalds/linux/master/security/apparmor/ipc.c
- https://raw.githubusercontent.com/torvalds/linux/master/include/uapi/asm-generic/signal.h
