# Workspace broker validation record

## What this record means

This is the execution record for the delivered workspace-broker changes, not a
claim of completed testing on an installed graphical Debian host. No native
software was compiled. The package publisher assembles source/configuration
archives only. AppArmor was parsed without loading policy into the kernel.
The feature design, configuration and known protocol limits are documented in
`WORKSPACE-BROKER.md`.

## Completed feature checks

| Check | Observed result |
| --- | --- |
| Focused Python/Perl/protocol/integration runner | 29 test methods: 28 passed, 1 explicitly skipped |
| Production Perl policy, framing, renderer and private-file suite | 6 subtests passed; real Moo constructor subtest explicitly skipped |
| Static protocol generation consistency | Passed `tools/workspace_broker_protocols.py --check` |
| Actual installer template functions | Parsed rendered XML, JSON and CSS for 1, 3, 4, 5 and 12 workspaces, thumbnail/classic, and 4/24/64 slots |
| Installed configuration-verifier code | Executed successfully against relocated rendered fixture; real package-version calls remain target checks |
| Broker staging inventory | All 15 library/notice assets and 3 executables are staged and verified |
| GTK3 real-image and raised-badge smoke | Actual GTK3 under Xvfb rendered 1/2/10/99/99+ examples; image-enabled versus image-disabled pixels differed |
| systemd dependency verification | Relocated five-unit fixture passed; real dependency edges retained, executable paths replaced only with `/bin/true`; no units started |
| AppArmor profiles | All three modified profile files parsed with `apparmor_parser --names`; no enforce-mode session run |
| Publisher | Rebuilt 1284 payload files; `tools/build.py --check` passed |
| Shell parser checks | 268 shell files, 547 parser checks, passed |
| Preseed checks | 59 files passed; all four generated command strings survived private debconf read-back |

The focused command is:

```sh
PYTHONPATH=d-i/forky/tests python3 -B -m unittest \
    test_workspace_broker test_workspace_broker_integration -v
```

The standalone Perl suite is:

```sh
perl -I "$PWD/d-i/forky/hooks/target/usr/local/lib/labwc-workspace-broker/perl5" \
    d-i/forky/tests/workspace_broker.t
```

The production reducer is tested directly, not replaced with a simulated
policy. Coverage includes every exact badge value 2--99, single/no-badge and
100+/capped display, true exact counts, alias and anonymous identities,
workspace-before-grouping, output-local visibility, stable slots, overflow
pagination, UNKNOWN membership, cross-protocol transitions, stale picker
rejection, title/app-ID changes, duplicate JSON keys, UTF-8 and frame bounds,
Pango/CSS injection, private path modes, symlinks, hard links and nonblocking
FIFO rejection.

Python callback tests use fake proxies to exercise the actual driver code:
manager/toplevel done buffering, workspace integer state versus toplevel array
state, fence interleaving, retired-output lifetime, required-global loss,
initialization, command restrictions, acknowledgment behavior, flush EAGAIN,
queue limits, selector progress, EOF and guarded callback failures.

Process fixtures execute the actual Perl broker, private/public framed IPC,
policy and child supervision. They verify exact-child authentication,
initial readiness, public-client failure isolation, direct action dispatch,
child failure taking down the broker, cleanup and normal shutdown. Because
Moo is unavailable in this builder, the process fixture substitutes only the
State constructor/accessor facade, configuration/runtime locations and driver
executable path; all semantic methods still invoke the production reducer.
This is **not** a successful real-Moo/PyWayland session test.

The picker fixture executes the actual picker implementation against a fake
Fuzzel wrapper. It checks index mapping, cancellation, malformed or out-of-range
results, timeout, and a crashed wrapper leaving a descendant holding its output
pipe. A valid-looking number followed by an execution timeout is discarded;
owned process-group cleanup is exercised.

The GTK smoke uses the container's installed HighContrast icon theme and
DejaVu Sans as test-only overrides. It demonstrates actual image pixels and
raised numeric text in GTK, including active/minimized styles. It does not
validate target Papirus assets, Waybar on Wayland, fractional scaling or the
native thumbnail switcher. No fonts were copied into the deliverable.
A harmless accessibility-bus warning is retained in its log.

Reproduce that optional test on a machine with GTK3/Xvfb:

```sh
fixture=$(mktemp -d)
/bin/sh d-i/forky/tests/fixtures/workspace-broker/render.sh \
    "$PWD" "$fixture" 12 thumbnail 24
xvfb-run -a python3 -B \
    d-i/forky/tests/fixtures/workspace-broker/gtk_smoke.py \
    "$fixture/etc/skel-desktop/.config/waybar/style.css" \
    "$fixture/taskbar.png"
```

## Explicit dependency skips

`python3-pywayland`, Moo, MooX::StrictConstructor and Type::Tiny are not installed
in this execution container. The actual generated-binding import test and
actual Moo strict-constructor subtest therefore skip with explicit messages.
No dependency was fetched using pip/CPAN or built to hide those skips.
The installer now performs real target-side imports with the Debian packages,
plus version/configuration/ownership checks, before accepting target staging.
Those target-side imports have not been executed here.

## Adjacent regression checks and pre-existing failures

These completed existing suites passed unchanged, except for the narrowly
adapted rendering fixture in the keyboard regression test:

| Existing suite | Result |
| --- | --- |
| `test_config_safety` | 19 passed |
| `test_dbus_broker` | 16 passed |
| `test_lifecycle` | 22 passed |
| `test_process_capture` | 10 passed |
| `test_power_keyboard_20260913` | 34 passed |

The existing keyboard test had treated every template placeholder as a scalar.
A generated taskbar module block is not a scalar. That single test now uses the
real renderer; its original keyboard behavior assertions are unchanged.

Two existing checks are **not green**, and were not repaired outside this task:

1. `test_desktop_sandbox`: 70 methods, 68 passed, 1 skipped (`rsyslogd`
   unavailable), 1 failed because
   `InstalledFailureRegressionTests.test_apparmor_complain_incident_is_fully_mapped`
   requires an external `todo/apparmor.log` above the repository that is absent
   from the supplied material. No invented audit log was created.
2. `test_repository_integrity`: 9 methods passed; the profile-provenance method
   failed for all 13 existing host-profile hash records. A separate SHA-256
   comparison confirms that **all 13 profiles and `docs/migration-map.json` are
   byte-identical to the uploaded ZIP**. The mismatch predates these changes;
   neither profiles nor historical migration metadata were edited. The other
   integrity checks, including composition, paths and generated-product
   currency, passed.

A broader no-native-build regression attempt and the repository-transport
suite exceeded the execution environment's time budget. They have no claimed
passing result. The unfiltered aggregate test target was not used, because
some existing unrelated NVIDIA tests invoke a native compiler. Consequently
this record does not claim an entirely passing repository-wide test suite.

Completed logs are preserved under `validation/workspace-broker/`. Older
validation reports elsewhere in the supplied repository are historical and
have not been rewritten to imply they apply to this feature.

## Required live acceptance on a disposable installed target

Run these with the actual packaged dependencies and AppArmor in enforce mode,
not by disabling confinement or bypassing the Fuzzel wrapper.

**Installation and lifecycle.** Complete unattended installation from the new
matched payload/manifest/preseed set. Verify the target import/configuration
checks and root-owned modes. Verify one Perl MainPID plus one Python driver in
the service cgroup; actual READY and watchdog behavior; failure and restart of
the driver; no duplicate child after restart; socket cleanup at logout; and
continued Waybar workspace/clock/network use and native Alt+Tab with the broker
stopped. Check the journal and audit log for denied dependencies or transitions.

**Taskbar.** Open one foot window, then a second; confirm the same real foot
icon, no badge then raised 2, and immediate grouping after activation. Return
to one window and confirm direct minimize/raise returns. Repeat with Firefox
and Thunar, duplicate and hostile titles, minimized windows, failed-close or
unsaved documents, and a canceling picker. Test empty workspaces and the same
application on two workspaces without mixed counts. Verify UNKNOWN/relearning
after restart and background creation. Explicitly exercise focus-preserving
moves and document the missing-protocol behavior, rather than treating a
cached active bit as proof of membership.

**Outputs and scale.** Test group members split across outputs, workspace-wide
badge counts with output-local visibility, hotplug and output removal while a
picker is open, 100/125/150/200 percent scale, active/hover/minimized contrast,
and real Papirus resolution on the target. Check rapidly changing titles and
slot overflow without panel restarts. Unknown application metadata should
produce a real generic icon without filesystem escape or CSS injection.

**Native switcher.** Test quick Alt+Tab, held modifier and repeated cycling,
Shift reverse, mouse selection, Escape restoring prior focus, minimized and
fullscreen windows, and 25 or more windows with scrolling. Confirm candidates
are current-workspace only, one OSD follows keyboard focus, and all current-
workspace monitors remain candidates by default. Test classic fallback,
software rendering and available GPU drivers, native/XWayland clients, Wine
modal dialogs and input-method popups without adding global workaround rules.
No broker/picker/helper process should be spawned by ordinary Alt+Tab.

**Shutdown safety.** Test unsaved windows on multiple workspaces behind a
single grouped application icon. Existing session preparation must still
consider every real toplevel; grouping must not silently lose save prompts.
Restore must not depend on persistent broker handles or on successful taskbar
startup. No resume descriptor schema was changed by this feature.

## Source and archive integrity

The original ZIP contained 1621 regular files. None was removed. Changes to
original files are confined to 15 desktop implementation/configuration files,
one existing regression-test adaptation, and the three regenerated publication
artifacts. New files are the broker, its protocol tooling/tests, documentation
and this validation evidence. Original host profiles, session-state code,
other desktop utilities and historical reports remain unchanged. The normal
publisher sets the three generated publication files to mode 0644; other
original modes were preserved.

The full-codebase tarball is not a patch or an overlay. It contains the complete
`debian-preseed-de/` tree, including unrelated original files and the matched
published payload set. Its sibling SHA-256 file covers the final archive.
