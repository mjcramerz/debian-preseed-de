# Native Waybar menus and calendar integration - 2026-09-20

## Scope and delivery

This revision starts from the supplied `debian-preseed-de(2).zip`. It changes the
managed Waybar menus, their calendar/notification helpers, the corresponding
installer staging and verification, and the calendar helper's AppArmor policy.
The complete repository is delivered, not an overlay or a replacement desktop.

No new upstream compilation, upstream source patch, notification daemon, global
Xwayland instance, or Xwayland application exemption is introduced. The existing
Zoom/Discord private-Xwayland implementation, compositor configuration, wlroots,
Crystal Dock, package selections, hardware profiles, and unrelated launchers are
preserved. Existing historical reports and generated assets are retained; this
report supersedes only their descriptions of the menus changed here.

The three served installer products (`d-i/forky/payload.tar.gz`,
`d-i/forky/payload.manifest`, and `d-i/forky/preseed.cfg`) are regenerated together.
Publish the complete repository atomically using the existing deployment method;
do not serve a new manifest with an old payload. This is an unattended-install
source update, not an in-place migration of already customized user homes.

## Native menu contract

Both the internal and external Waybar layouts use the same five GtkBuilder menu
files. Every clickable leaf has one unique ID and exactly one configured action.
Submenu containers and separators are not accidentally wired as leaf actions.
The menu root is `GtkMenu` with ID `menu`, as required by Waybar.

| Button | Native menu gesture | Leaf actions per layout | Other gestures retained |
| --- | --- | ---: | --- |
| Tomat | Right click | 10 | Left toggles; middle skips |
| Audio | Right click | 8 | Existing audio application on left; output mute on middle |
| Notifications | Left click | 7 | Middle toggles DND; right opens the center |
| Power | Left click | 5 | Existing policy/authorization wrappers retained |
| Calendar / clock | Right click | 12 | Existing calendar application on left; tasks on middle |

The clock's old right-click Fuzzel command is removed, not layered underneath a
GTK menu. The non-Waybar `labwc-calendar menu` interface remains compatible and
now exposes the same task operations for existing callers.

Waybar's GTK activation callback executes its configured command synchronously.
All 84 menu action definitions therefore use `systemd-run --user --no-block`:
Waybar submits the transient service without waiting for its activation or the
application to exit. Submission still involves the normal user-manager D-Bus
round trip; this is not a hard real-time guarantee about an overloaded manager.

Each menu action retains `--service-type=exec`, `--collect`,
`--expand-environment=no`, `app.slice`, `Requisite`/`After`/`PartOf` relationships
to `labwc-session.target`, `ExitType=cgroup`, and `KillMode=control-group`.
Startup is bounded at 10 seconds and stop handling at 20 seconds. There is no
shell backgrounding, `nohup`, PID-name killing, or detached application scope.
Long-lived children remain owned by the user manager and session lifecycle.
Non-menu mouse launchers are intentionally unchanged.

### Tomat

Existing default, 25/5, 50/10, and 90/15 presets, pause/resume, skip, stop,
configuration, notification and sound actions retain their reviewed controller.
The independent Tomat daemon lifecycle, private runtime/configuration validation,
atomic settings updates, and bounded hooks are not rewritten.

### Audio

Open Pavucontrol, output mute, microphone mute, and volume 40% retain their
existing fixed commands. The nested Whisper actions retain their existing
record/start/stop/transcribe services. During staging, the Whisper submenu is
labeled `Whisper (not installed)` and made insensitive when `addon/whisper` is
not selected. Selected installations get the normal active submenu. IDs remain
stable in both cases. The sensitivity property is inserted before submenu children:
real GTK3 ignores that construction property when it is appended after them.
A native GTK regression exercises absent/present/absent staging. Target verification compares that state with the presence
of the staged transcription service in both the skeleton and account home.
No Whisper package or source build is added by this change.

### Power

Lock, suspend, reboot, logout and poweroff continue through
`labwc-power-settings`, not direct unvalidated power commands. Existing
confirmation/authorization, package-operation guards, save/quiesce handling and
session shutdown ownership are preserved. This revision changes only how
Waybar submits these already managed operations.

## Calendar and task actions

| Menu section / entry | Public helper action | Backend behavior |
| --- | --- | --- |
| Open calendar | `browse` | Existing terminal-based interactive calendar |
| Upcoming agenda (14 days) | `agenda` | `khal list today 14d` |
| Events / Create event | `new-event` | Interactive `khal new -i` |
| Events / Edit or delete event | `edit-event` | Interactive `khal edit --show-past -- QUERY` |
| Tasks / Pending tasks | `tasks` | `todoman list` |
| Tasks / All tasks | `all-tasks` | `todoman list --status ANY` |
| Tasks / Create task | `new-task` | Interactive `todoman new -i` |
| Tasks / Task details | `show-task` | Select numeric ID; `todoman show -- ID` |
| Tasks / Edit task | `edit-task` | Select numeric ID; `todoman edit -i -- ID` |
| Tasks / Mark task completed | `done-task` | Preview, default-no confirmation, then `todoman done -- ID` |
| Tasks / Delete task | `delete-task` | `todoman delete -- ID`, keeping Todoman's own confirmation |
| Sync calendar and tasks | `sync-ui` | Open the existing `sync-terminal` flow |

All native calendar actions use the absolute public wrapper path and fixed
subcommands. Interactive operations run in the existing managed terminal. The
shared result-holding helper preserves the backend exit status and keeps output
visible until Enter, rather than flashing a terminal closed on an error.

Task IDs must be positive ASCII decimal integers of at most 18 digits; empty
input cancels. Option-like input, leading zeroes, shell fragments, whitespace,
and oversized IDs are rejected before a mutating command. Event queries are
quoted single operands after `--`, so a query beginning with a dash cannot
become a Khal option. Non-sync dispatch rejects extra command arguments.

A failed task listing or preview prevents the later mutation. Completion is
explicitly default-no; deletion never supplies `--yes`. Editing can select
completed/cancelled tasks from the all-status list. Khal supplies event search,
edit/delete prompts and recurrence handling; this helper does not manipulate
ICS files directly or invent alternate calendar semantics.

The existing vdirsyncer configuration, protected directories, lock ownership,
unique private logs, discovery/sync deadlines, and process-group cancellation
flow are retained. `sync-ui` makes that existing visible/error-reporting path
available directly from the native menu. No new polling sync daemon is added.

The AppArmor change is confined to `managed-labwc-calendar`: permit the existing
cancel path's `kill`/`sleep` executables and TERM/KILL delivery to children that
use the existing `pux` fallback. The script still targets only its own saved
sync process group. No Xwayland-related AppArmor rule or shared abstraction is
changed. Offline parser success does not demonstrate live kernel enforcement.

## Notifications and Mako center

The native menu exposes seven fixed choices:

| Choice | Mako control |
| --- | --- |
| Open notification center | Managed GTK3 application |
| Restore most recent notification | `makoctl restore` |
| Do not disturb / Enable | `makoctl mode -a do-not-disturb` |
| Do not disturb / Disable | `makoctl mode -r do-not-disturb` |
| Do not disturb / Toggle | `makoctl mode -t do-not-disturb` |
| Dismiss active (save to history) | `makoctl dismiss --all` |
| Clear active (do not save) | `makoctl dismiss --all --no-history` |

DND operations preserve other Mako modes. History retention remains subject to
Mako's policy: this configuration does not retain low-urgency notifications.
"Clear active" does not erase saved history. Restore uses Mako's most recent
history item and does not turn DND off; while DND is enabled, a restored popup
may remain invisible. There is no fabricated "clear saved history" command.
Mako's history is a bounded session buffer, not a durable archive.

The center remains one GTK3 `Gtk.Application` per user session, with Current
and History pages, Refresh, DND, Dismiss active and Restore latest controls.
Activating it again requests presentation of the existing application. Escape
or closing the window shuts down the view. Notification content is read-only:
no notification-supplied command, callback, markup, image or URI is executed.
It is a best-effort viewer/control surface for Mako, not a replacement daemon
or a promise of features Mako's public control API does not provide.

The implementation uses Mako's JSON list/history interfaces. Actual Mako 1.11
`app_name` and nullable text fields are handled without printing Python `None`.
Strings are type-checked and length-bounded; NUL, control characters and lone
surrogates are neutralized before plain GTK labels are constructed. Invalid
JSON, incorrect list/field types, excessive nesting, or invalid UTF-8 produce
controlled errors. Data from stderr is never mixed into notification JSON or
printed into a UI/journal error as notification content.

The existing unprivileged-user/runtime validation and isolated Python entrypoint
are preserved. Subprocesses receive a fixed PATH, the same user's runtime/bus,
Wayland-only toolkit settings, and no inherited DISPLAY, XAUTHORITY, Python
module overrides or dynamic-loader injection variables. Only a closed set of
absolute-path `makoctl` argv requests is accepted; there is no shell execution.

Each Mako request has a four-second deadline and a combined one-MiB stdout/stderr
capture limit enforced while reading, not after collecting unlimited output.
Both pipes are drained independently. Timeout, cancellation and over-limit
responses kill and reap the exact child; even a child that closes its pipes
without exiting remains subject to the same deadline.

One worker handles refreshes. A five-second GTK timer never queues another job
while one is active. Current, History and DND failures are independent, allowing
a working page to remain available when another request fails. Each page renders
at most 100 entries, with an explicit truncation notice when needed. Unchanged
pages are not rebuilt on every refresh. Closing sets a cancellation event,
removes the refresh timer and shuts down the worker; normal cancellation is
checked at intervals no greater than 100 ms while reading/waiting. This is not
a guarantee about an unkillable kernel task or a broken desktop bus.

## Installer integration and validation

`desktop_stage_waybar_native_menus` explicitly stages all five XML assets, then
applies the optional Whisper state. The existing account-copy path distributes
them alongside the generated Waybar configuration. Calendar helper staging
continues through its existing public/private wrapper pair.

`desktop_verify_native_menus` checks both the installed skeleton and primary
account: helper ownership/modes, GtkBuilder IDs and complete leaf/action
bijections, click conflicts, exact calendar/notification backends, lifecycle
options, optional Whisper availability, GTK3 availability, and the existing
Mako >= 1.11 and Tomat requirements. GTK import does not require an active display
inside the installer chroot. The existing desktop package selection already
contains `python3-gi`, `gir1.2-gtk-3.0`, Mako, Khal and `todoman/trixie`.

A new regression module exercises actual shell-helper dispatch with controlled
backend fixtures, task/event input handling, failure propagation, completion
confirmation, optional-menu staging, Mako parsing, real subprocess timeout/
cancellation/output-limit behavior, and the 84-action lifecycle contract.
Existing GTK Builder tests now load all five actual XML files; existing
notification placement/style tests retain both layouts and all desktop profiles.

Validation evidence, scope hashes and baseline comparisons are recorded in
`validation/native-menus-calendar-20260920/`. The final validation results and
known limitations are summarized in the companion `review-summary.json` there.
Historical validation directories elsewhere in this tree describe older runs,
not this revision.

### Recorded final validation

| Check | Result |
| --- | --- |
| Final menu-focused suite | 68 tests: 67 passed, 1 Perl-dependency skip, no failures |
| New contract module within that suite | 35 passed, no skips |
| Full repository test suite | 1964 tests, 3 failures, 0 errors, 48 skips |
| Untouched uploaded baseline | 1930 tests, 4 failures, 0 errors, 48 skips |
| Repository tool tests | 179 tests, 0 failures, 0 errors, 0 skips |
| Shell syntax/metadata checks | 285 files, 581 parser checks, passed |
| Preseed checks | 59 files, passed; four generated command values survived private debconf read-back |
| Native GTK3 | All five menus loaded; optional Whisper insensitive/sensitive/insensitive verified |
| AppArmor source parsing | Three relevant profile sources passed offline parsing; not loaded into the kernel |
| Served payload | All 1,401 entries match source bytes and manifest hashes; modes match unchanged builder policy |
| Generated products/browser exports | Freshness checks passed against the final source |

The repository-wide audit reports `{"blocked-dependency": 157, "blocked-tool": 11, "inventory-only": 508, "pass": 473, "structure-pass": 178, "template-needs-render": 2}`.
Blocked dependencies, templates awaiting rendering and inventory-only entries
are explicitly not runtime passes. Unit checks are lexical structure checks.

**The full repository suite is not green.** Its three failure names also occur
in the untouched baseline; no new failure name was introduced. These failures
are an existing IOCost profile/test expectation mismatch: the supplied
`btrfs-de-flex-duo.env` sets `IOCOST_CALIBRATE_ENABLE="false"`, while those tests
expect it to be enabled and staged. Changing that hardware policy or silently
rewriting unrelated tests would go beyond this menu revision, so both are kept.

The baseline also failed `test_opposite_role_fails_before_preflight_marker`,
and an isolated run against the final tree reproduced the failure. Its unchanged
eight-second wait elapsed before the fatal record appeared. A separate extended
diagnostic reached the correct terminal FATAL hold after 8.394 seconds, with
no `preflight.ok` marker and no return to unattended installation. This same test
passes in the final full suite. These observations demonstrate timing sensitivity
in this environment, not an installer fix in this revision. All outcomes and
tracebacks are retained separately; the failed runs are not relabeled as passes.

The full suite discovered tests before the final additional native-GTK Whisper
property-order regression was added. The final 68-test focused run includes that
case and the final staging fix. Build, preseed, shell, AppArmor and payload checks
were repeated against the final source. The initial tools run also exposed a
stale assertion expecting 60 ordinary click callbacks: moving the two clock
right-clicks to GTK menus correctly leaves 58. That regression was updated to
require both native calendar menu paths and reject the old Fuzzel right-click
fallback. The entire 179-test tools suite was then rerun successfully. Both
initial and final logs are retained; the original validator summary is not
rewritten to hide its initial tools-stage failure. These overlapping suite
counts must not be added as distinct tests.

All 3,319 original regular files are retained; 3,306 are byte-identical. The
13 changed originals consist of seven scoped production files, three regression
files and three regenerated served products. New files contain the calendar
menu, contract tests, the native GTK fixture, this report and validation evidence.
46 protected-path files, including the existing private-Xwayland implementations,
are byte-identical. Shared installer/AppArmor files are also checked unchanged
outside their explicitly reviewed functions/profile. The outer delivery archive
retains the repository's file permissions. The unchanged payload builder uses
0755 for executable entries and 0644 otherwise.

### Target-session acceptance checks still required

These files have not been booted through Debian d-i or exercised in a live
Forky/systemd 261.2 labwc session in this environment. Before fleet rollout,
perform a disposable target installation and check all five menus on both bar
layouts, with the optional Whisper add-on both selected and absent. Test Mako
Current/History, DND and restore against real notifications; check an unavailable
Mako daemon and close the center during refresh. Confirm that repeated opening
presents one center rather than leaving worker processes behind.

Use disposable calendar/task data to test create/edit/complete/delete and sync
failure/cancellation. Confirm backend errors remain visible. Inspect the user
journal and AppArmor denials during these operations and verify no transient
menu application survives session shutdown. Check `DISPLAY` remains absent in
the ordinary Wayland session and that only the existing Zoom/Discord private
Xwayland paths are used. These are acceptance steps, not claims of tests already
performed here.

## Primary interface references

The implementation was checked against these primary sources; they are design
references, not dependencies fetched or built by this revision.

- Waybar native menu format:
  https://raw.githubusercontent.com/Alexays/Waybar/master/man/waybar-menu.5.scd
- Waybar 0.14.0 GTK activation implementation:
  https://raw.githubusercontent.com/Alexays/Waybar/0.14.0/src/ALabel.cpp
- systemd 261 transient-run options:
  https://raw.githubusercontent.com/systemd/systemd/v261/man/systemd-run.xml
- Mako 1.11 control interface:
  https://raw.githubusercontent.com/emersion/mako/v1.11.0/doc/makoctl.1.scd
- Mako control JSON implementation:
  https://raw.githubusercontent.com/emersion/mako/master/makoctl.c
- Todoman 4.5.0 CLI (the existing Trixie package uses 4.5.0):
  https://raw.githubusercontent.com/pimutils/todoman/v4.5.0/todoman/cli.py
- Trixie Todoman package interface:
  https://manpages.debian.org/trixie/todoman/todoman.1.en.html
- Khal calendar, interactive creation, and edit/delete interfaces:
  https://khal.readthedocs.io/en/latest/usage.html
