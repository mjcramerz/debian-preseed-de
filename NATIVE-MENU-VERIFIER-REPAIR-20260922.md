# Native Waybar menu verification repair

Date: 2026-09-22  
Input: `debian-preseed-de(5).zip`  
Requested deployment target: Debian Forky with systemd 261.2.  
Scope: fix the failing native Waybar menu / Tomat installation verification,
without redesigning the desktop or changing private Xwayland.

## Confirmed defect and reproduction

The existing `desktop_verify_native_menus()` asserted this adjacency:

```text
custom/wayscriber -> custom/tomat -> group/apps
```

The actual `desktop_waybar_modules_left_json()` generator instead emits:

```text
custom/launcher -> ext/workspaces -> custom/tomat -> custom/wayscriber
-> custom/window-switcher -> group/apps
```

It additionally appends `wlr/taskbar` for a single workspace. The native workspace
verifier already agrees with this generator; the native-menu verifier did not.
Consequently, valid generated desktop configurations cannot satisfy the old
native-menu assertion. This is a configuration/verification contract mismatch,
not evidence that the GTK menu XML should be replaced or that Tomat needs a
different daemon model.

Before modifying production code, the new regression fixture executed the
original embedded Python verifier against configurations from all ten actual
profile renderers, with Whisper enabled and disabled. All 20 cases stopped at
`SystemExit: wrong Tomat button order`. The baseline log is retained at
`validation/native-menu-verifier-20260922/baseline-regression.log`; its failures
are intentional historical reproduction evidence, not the final test result.
Only the generic fatal-stage message was supplied, not a complete installation
log. This reproduction establishes an unconditional defect at that stage; it
does not establish which earlier target-specific prerequisite succeeded on the
original machine.

## Targeted correction

Only `d-i/forky/scripts/desktop/verify.sh` is changed in the active installer sources.
`desktop_verify_native_menus()` now obtains the canonical left-module list from
the existing renderer function, checks generator failure explicitly, and passes
the list as one quoted JSON argument to the target Python verifier. The verifier
compares the full installed list to that expected list, rather than using the
obsolete pair of `list.index()` adjacency checks.

The expected list is not read from the installed file being checked. The test
suite also independently asserts the intended order for all twelve supported
workspace counts. Missing, duplicated, reordered and unexpected modules remain
errors. A mismatch reports the configuration path, internal/external bar name,
expected list and actual list. A missing Tomat item now fails this explicit
contract check instead of producing an incidental `ValueError` from `index()`.

No verification phase was bypassed. The existing drawer verifier still runs
first. All 31 native-menu `require()` call sites remain, including file ownership
and permissions, TOML validation, menu event conflicts, XML IDs, action mappings,
transient-unit lifecycle properties, optional audio availability, Mako version,
Tomat CLI probes and stock service masks. The verifier remains display-independent
and does not start a daemon.

## Wiring reviewed and preserved

| Menu | Waybar module | Popup event | Leaf actions |
|---|---|---|---:|
| Tomat | `custom/tomat` | Right click | 10 |
| Audio | `pulseaudio` | Right click | 8 |
| Notifications | `custom/notifications` | Left click | 7 |
| Power | `custom/power` | Left click | 5 |
| Calendar | `clock` | Right click | 12 |

All five menu XML assets, IDs, native GTK3 widgets and action backends remain
unchanged. Both internal/external layouts and both the skeleton and primary-user
copies are exercised. Optional Whisper actions continue to follow the installed
service state. The native menu/action contract is the upstream Waybar
`menu`, `menu-file`, `menu-actions` contract, with a `GtkMenu` root named `menu`.[1]
Real GTK3 builder tests are distinct from XML-only parsing.[2]

The existing Tomat foreground daemon invocation is retained. Tomat v2.13.0's
upstream CLI explicitly includes the hidden `daemon run` subcommand; its absence
from general help is not a reason to switch to a background-daemon command.[3]
The existing `systemd-run` user-service handoff, argument-expansion setting,
collection policy and session/cgroup properties are not modified.[4]

No changes were made to Xwayland, Zoom/Discord integration, labwc, wlroots,
Crystal Dock, AppArmor policy files, user/system service units, package selections,
release pins, menu configuration/templates or the module-order generator.
No new upstream source build or upstream source patch was introduced. The
repository's existing `tools/build.py` only republished installer artifacts.

## Regression coverage

New file: `d-i/forky/tests/test_native_menu_verifier_20260922.py`.

Nine test methods cover the actual shell-to-target argument handoff and execute
the complete embedded production verifier. They cover all ten profiles, both
Whisper states, both layouts and config copies, workspace counts 1 through 12,
invalid module lists, conflicting popup events, mismatched menu/action IDs,
missing lifecycle flags, unsafe ownership/modes, symlinked menu files, missing
stock service masks, an insufficient Mako version, optional-audio mismatches,
the existing non-amd64 branch, and generator failure under dash and BusyBox ash.

The new verifier regressions pass under `/usr/bin/python3` (nine tests, no skips).
The focused `test_native*.py` run passes: 107 tests, one dependency-related skip.
That skip is the pre-existing Perl release-metadata test requiring Moo modules.

The fixture deliberately simulates only target boundaries: filesystem root and
UID/account lookup, GTK import, installed package version/architecture probes and
Tomat `--help` responses. Real file bytes, renderer substitutions, XML parsing,
TOML validation, shell quoting, Python assertions and `dpkg --compare-versions`
execute. No fixture pretends to qualify a real daemon or user manager.

## Repository-wide results

Results directory: `validation/native-menu-verifier-20260922/`.
The machine-readable final result is `summary.json`; every stage below returned
zero, and no stage timed out.

| Stage | Result | Log |
|---|---|---|
| Browser publication check | PASS | `browser-check.log` |
| Installer snapshot / pin / preseed consistency | PASS | `build-check.log` |
| Preseed checks | PASS | `preseed-check.log` |
| Shell and embedded preseed parsing | PASS | `shell-check.log` |
| Installer / desktop test suite | PASS; 2304 run, 50 skipped | `tests.log` |
| Repository tools test suite | PASS; 179 run, 0 skipped | `tools-tests.log` |
| Repository audit | PASS | `audit.log` |

The final repository-wide run uses Debian's `/usr/bin/python3`. The first full
attempt used the sandbox virtual-environment interpreter and hit the unchanged
Spotify cancellation fixture's 250 ms shutdown limit (`137 != 1`). The isolated
virtual-environment repetition reproduced that timing sensitivity; five
consecutive repetitions under Debian's interpreter passed. Neither Spotify code
nor the fixture deadline was modified. The initial full-run evidence remains in
`virtualenv-attempt/`, and the interpreter comparison logs are retained alongside
this report's validation files. A preliminary Debian-Python run exposed a missing PyYAML import in the unchanged
`test_config_safety` module. That run was stopped rather than continued with a
known loader error; its partial logs and termination reason are preserved in
`debian-python-missing-yaml-attempt/`. The sandbox's existing, unchanged PyYAML
6.0.3 package was then supplied through a test-only `PYTHONPATH`, outside the
repository. No package was fetched or compiled, and no repository dependency
file was modified. A discovery-only preflight loaded all 2,304 test cases with
zero import errors before the final full run. The final full run is a complete
rerun, not a filtered suite or a replacement of any failed assertion with a skip.

A stage marked PASS means that validation command returned zero; it does not turn
unavailable runtime checks into successes. The final audit records
471 passing checks and
180 structure-only checks, alongside
158 dependency-blocked checks,
11 tool-blocked checks,
509 inventory-only entries and
2 templates needing rendering.
See `audit.json` for individual classifications.

The separate native GTK3/Xvfb harness reports:

- 400 menu roots constructed across ten profiles, two bar layouts,
  two GTK themes and the optional-audio states.
- 3200 simulated menu action activations, including
  80 notification-center activations.
- 11400 highlight-state checks, 3920
  disabled-state checks, and zero callback errors.

These results are saved in `gtk-menu-report.json`. Callbacks are intercepted;
the harness does not execute power actions or change the host. Xvfb is used only
by this existing test harness and is not a deployment/Xwayland change.
The focused AppArmor profile parser test also passes; parsing is not kernel
mediation testing. All skipped test methods and reasons from the full validation
are enumerated in `skipped-tests.json`. Debian package retrieval could not fill
missing test dependencies because `deb.debian.org` did not resolve in this
execution environment.

## Publication integrity and complete-tree scope

The installer snapshot was regenerated using the existing publisher. The three
updated generated files are:

```text
d-i/forky/payload.tar.gz
d-i/forky/payload.manifest
d-i/forky/preseed.cfg
```

A member-by-member comparison of the old/new inner installer archives confirms
1403 members before and after, exactly one changed member
(`scripts/desktop/verify.sh`), and no member metadata changes. All other payload
files are byte-identical, including all Xwayland and AppArmor assets.

The full delivery retains every original source-tree file. Besides the one
production source and three required generated files, additions are the new
regression test, this report, the current validation evidence and the scoped
SHA-256 change manifest. Historical reports remain unmodified and may describe
older revisions; use this report and the date-matched validation directory for
this repair. `CHANGE-MANIFEST-NATIVE-MENUS-20260922.json` identifies each changed
or added file and records input/output hashes.

## Deployment and validation boundaries

Publish the complete replacement repository atomically. Do not mix the old
`preseed.cfg`, manifest or payload with the new versions, and do not replace only
the served loose `verify.sh`: an installer consuming the pinned payload would
still execute its embedded copy. External copies/caches of the generated preseed
must likewise be refreshed. No deployment was performed from this environment.

This repair has repository/fixture and native GTK3 validation. It has **not**
been qualified by booting an unattended Forky installation with systemd 261.2,
starting Waybar inside labwc, running the real Tomat vendor daemon, exercising a
live systemd user-manager lifecycle, or testing AppArmor kernel enforcement.
Those are the remaining deployment acceptance boundaries, not disabled checks.

Reproduce the relevant checks from the extracted repository root, using a
Python interpreter with the repository's validation dependencies, including
PyYAML, available:

```sh
python3 -B tools/build.py --check
PYTHONPATH=d-i/forky/tests python3 -B -m unittest -v test_native_menu_verifier_20260922
python3 -B tools/validate.py --output-dir validation/local-native-menu-check
```

## Production diff

```diff
--- original/d-i/forky/scripts/desktop/verify.sh
+++ corrected/d-i/forky/scripts/desktop/verify.sh
@@ -2057,6 +2057,9 @@
 
 desktop_verify_native_menus() {
   desktop_verify_native_drawer_icons
+  # Share the renderer's layout, including the single-workspace taskbar.
+  desktop_native_menu_modules_left=$(desktop_waybar_modules_left_json) ||
+    desktop_fatal "failed to resolve native Waybar menu button order"
   # Parse installed files, without launching a daemon or requiring a display.
   # shellcheck disable=SC2016
   run_in_target "verify native Waybar menus and Tomat integration" /usr/bin/python3 -I -B -c '
@@ -2094,6 +2097,7 @@
                        timeout=10, check=False).returncode == 0,
         "native notification history requires mako-notifier >= 1.11")
 controller = runpy.run_path("/usr/local/libexec/labwc-tomat")
+expected_left = json.loads(sys.argv[3])
 account = pwd.getpwnam(sys.argv[2])
 require(account.pw_uid != 0 and account.pw_dir == sys.argv[1], "menu account/home mismatch")
 for base, uid in ((Path("/etc/skel-desktop"), 0), (Path(sys.argv[1]), account.pw_uid)):
@@ -2106,8 +2110,9 @@
     bars = json.loads((config / "waybar/config").read_text())
     for bar in bars:
         left = bar["modules-left"]
-        require(left.index("custom/tomat") == left.index("custom/wayscriber") + 1
-                and left.index("group/apps") == left.index("custom/tomat") + 1, "wrong Tomat button order")
+        require(left == expected_left,
+                "wrong native menu button order in " + str(config / "waybar/config")
+                + " (" + str(bar.get("name")) + "): expected " + repr(expected_left) + ", got " + repr(left))
         right = bar["modules-right"]
         controls = "group/quick-controls-internal" if bar.get("name") == "internal" else "group/quick-controls"
         require(right[-4:] == [controls, "custom/notifications", "custom/lock", "custom/power"]
@@ -2212,7 +2217,7 @@
         path = Path("/") / relative
         require(path.is_symlink() and os.readlink(path) == "/dev/null", "stock Tomat service is not masked: " + relative)
 print("desktop_native_menu_verification menus=5 tomat=isolated power=native calendar=native")
-' "$ACCOUNT_HOME" "$ACCOUNT_USERNAME"
+' "$ACCOUNT_HOME" "$ACCOUNT_USERNAME" "[${desktop_native_menu_modules_left}]"
 }
 
 desktop_verify_target_staging() {
```

## Upstream references consulted

[1] Waybar native-menu documentation:
https://raw.githubusercontent.com/Alexays/Waybar/master/man/waybar-menu.5.scd

[2] GTK3 GtkBuilder documentation:
https://docs.gtk.org/gtk3/class.Builder.html

[3] Tomat v2.13.0 CLI definition (foreground `DaemonAction::Run`):
https://raw.githubusercontent.com/jolars/tomat/v2.13.0/src/cli.rs

[4] systemd-run documentation:
https://www.freedesktop.org/software/systemd/man/systemd-run.html
