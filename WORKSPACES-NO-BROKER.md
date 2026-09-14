# Broker-free native workspaces and window switching

Date: 2026-09-14

## Delivery status: an important constraint

The workspace/taskbar broker has been removed. The approved native labwc
window switcher is preserved. The configured 1--12 compositor workspaces,
`ext/workspaces` selector and existing application-launcher drawer remain.

**Separate live per-workspace taskbars are not implemented by this revision.**
Stock labwc 0.20.2 / Waybar 0.15.0 does not provide the needed task-to-workspace
association to the native taskbar. Removing the broker does not add that
capability. With both the no-broker and no-custom-build constraints retained,
there is no verified configuration-only solution in this stack. This delivery
must not be represented as having achieved that outstanding requirement.

The native task strip is therefore enabled only when the managed configuration
contains a single workspace. With multiple workspaces, it is omitted rather
than silently displaying a global task list. This is a visible loss of taskbar
functionality, not an approximation that pretends to filter correctly.

| Configured workspace count | Waybar open-window strip | Window selection |
| --- | --- | --- |
| 1 | Stock ungrouped `wlr/taskbar`, real icons, output-local buttons | Native task buttons and native Alt+Tab |
| 2--12 | Not instantiated | Native current-workspace Alt+Tab |

The workspace buttons, launcher drawer, clock, status controls and existing
panel-output policy are retained. The independent Crystal Dock configuration
is unchanged and is not claimed to provide workspace-local task filtering.
No new background observer, renamed broker, socket, polling loop or per-widget
state service is introduced. Groups, counts, badges and the broker's Fuzzel
window chooser are removed. The shared Fuzzel launcher remains for its existing
unrelated uses.

## Why the native taskbar is not a replacement for the broker

The supplied workspace report already identifies this limitation in sections
1 and 4. It is independently consistent with the primary sources checked for
this revision:

1. Debian Forky packages Waybar 0.15.0-1 and labwc 0.20.2-1:
   - https://packages.debian.org/forky/amd64/x11/waybar
   - https://packages.debian.org/forky/labwc
2. The tagged Waybar taskbar manual defines `all-outputs` as monitor filtering.
   It does not define a current-workspace-only filter:
   - https://raw.githubusercontent.com/Alexays/Waybar/0.15.0/man/waybar-wlr-taskbar.5.scd
   - https://raw.githubusercontent.com/Alexays/Waybar/0.15.0/src/modules/wlr/taskbar.cpp
3. The labwc maintainer discussion identifies the missing window/workspace
   protocol relationship:
   - https://github.com/labwc/labwc/discussions/2924
4. The upstream master taskbar documentation's learned workspace CSS state is
   not an authoritative current-workspace task-button filter:
   - https://raw.githubusercontent.com/Alexays/Waybar/master/man/waybar-wlr-taskbar.5.scd

No unsupported `current-workspace-only`, `workspace-only` or `all-workspaces`
option has been added. `all-outputs: false` is not presented as isolation between
workspaces. The taskbar module definitions remain in the two native Waybar
configurations; the module lists instantiate them only for one workspace.

The generator logs a warning for a multi-workspace configuration, and the target
verifier rejects a taskbar enabled directly or through a nested group on that
configuration. Future package upgrades do not automatically enable an assumed
capability. A supported implementation would require a separately reviewed
change to the panel/compositor capability or to the stated constraints.

## What is retained in the native switcher

The previously approved configuration remains semantically unchanged:

```xml
<action name="NextWindow" workspace="current" output="all" identifier="all" />
<action name="PreviousWindow" workspace="current" output="all" identifier="all" />
```

The managed defaults remain:

```text
LABWC_WINDOW_SWITCHER_STYLE=thumbnail
LABWC_WINDOW_SWITCHER_ORDER=focus
LABWC_WINDOW_SWITCHER_PREVIEW=yes
LABWC_WINDOW_SWITCHER_OUTLINES=yes
LABWC_WINDOW_SWITCHER_UNSHADE=yes
LABWC_WINDOW_SWITCHER_OSD_OUTPUT=focused
LABWC_WINDOW_SWITCHER_CYCLE_OUTPUT=all
```

The metadata label, classic fallback fields, thumbnail/classic geometry,
Papirus application-icon theme, current-workspace scope and existing move/follow
bindings are retained. Workspace names are generated for all 1--12 workspaces;
the existing direct numbered keyboard bindings cover 1--9, with the workspace
selector providing access to higher-numbered workspaces. No unrelated keyboard
binding policy was changed.

Primary switching remains entirely inside labwc, subject to the existing window
rules. It does not invoke Perl, Python, Fuzzel, process discovery or external
screenshot capture. Native rendering, modifier handling, mouse selection and
Escape behavior remain compositor responsibilities, not newly implemented code.

Primary references:

- https://labwc.github.io/labwc-config.5.html
- https://labwc.github.io/labwc-actions.5.html

## Removal and integration

Removed from the source tree and generated installation payload:

```text
/usr/local/libexec/labwc-workspace-broker
/usr/local/libexec/labwc-workspace-wayland-adapter
/usr/local/bin/labwc-workspace-broker-client
/usr/local/lib/labwc-workspace-broker/
/etc/skel-desktop/.config/systemd/user/labwc-workspace-broker.service
```

Also removed are its staging and enablement entries, Waybar/restore service
dependencies, grouped module generator, count-badge CSS, runtime stylesheet
preparation, broker defaults, broker import checks, protocol provenance tool,
obsolete broker tests and broker-specific historical reports/logs. Relevant
switcher/rendering regression coverage was retained in the new focused suite.

Nine broker-only modified files were restored byte-for-byte to the uploaded
original: the desktop package list; three AppArmor policy files; Waybar and
session-restore unit files; the native Waybar configuration and stylesheet
templates; and `labwc-panel-run`. Existing Moo/MooX packages predated the broker
and remain in the original package list. Only the broker's package-list additions
were withdrawn. No shared packages are uninstalled from an existing system.

The session preparation/shutdown/restore program, application sandboxing,
D-Bus broker, output watcher, launcher wrappers, and pre-existing service
hardening are untouched. In particular, window shutdown enumeration remains
independent of workspace presentation.

### Reused installation targets

`desktop_retire_workspace_broker()` runs in the existing offline target-staging
path. It removes the three exact entrypoints, fifteen known private library
files, and the old service file/session-target link in both the skeleton and
the selected desktop account. All parent paths are checked before deletion;
symlinked ancestors and non-file assets fail rather than redirect cleanup.
Final symlinks are unlinked without following them.

Cleanup is idempotent. It removes only empty private directories and preserves
unrecognized files with a warning. It does not recursively erase user data,
scan or signal processes, contact a running user manager, remove live runtime
sockets, purge language packages, or modify the running kernel's AppArmor state.
The new staged configuration replaces the old unit dependencies and stylesheet
launch path through the normal installer flow.

This is not a live in-place upgrade tool. Downloading/extracting this archive
does not update an already running desktop. Use the complete snapshot for an
unattended installation; any separate deployment to an existing desktop must
coordinate stopping the old service, replacing rendered configurations and
policies, and rebooting. Do not source installer functions into a live system.
Reboot is important for previously loaded, now-retired profiles and runtime
state. Only the installer's selected desktop account is managed by cleanup;
other manually configured accounts are not enumerated or modified.

Changing `LABWC_WORKSPACE_COUNT` requires regenerating the managed labwc and
Waybar configurations together. Independently editing the live compositor XML
after a single-workspace installation is outside the generated policy. These
workspaces organize windows; they are not a process-isolation security boundary.

## Validation performed

Logs are under `validation/workspaces-no-broker/`.

| Check | Result |
| --- | --- |
| Focused broker-retirement/native-configuration suite | 25 passed; no skips |
| Real template rendering | 24 count/style combinations, plus one alternate native profile |
| Adjacent desktop, lifecycle, D-Bus, keyboard/power and process suites | 171 tests: 169 passed, 1 known baseline failure, 1 environment skip |
| Repository-integrity suite | 10 tests: 9 passed; the existing provenance test has 13 failing profile subcases |
| Original-ZIP baseline reproduction | The missing incident fixture and all 13 provenance mismatches reproduce |
| Systemd user dependency fixture | Passed for five actual session/panel units; only Exec paths relocated; no service started |
| Offline AppArmor parser | All three restored policy files passed with kernel load and cache writes disabled |
| Payload publication | 1,265 files rebuilt; payload/manifest/preseed pins current |
| Shell syntax | 268 shell files; 547 parser checks passed |
| Preseed format | 59 files passed; four command values survived private debconf read-back |

The missing incident-log fixture is the unchanged
`test_apparmor_complain_incident_is_fully_mapped` failure. The skipped adjacent
test requires `rsyslogd`, which is unavailable here. All thirteen affected host
profiles and the migration ledger remain byte-identical to the original ZIP;
no unrelated provenance data was rewritten to hide the failing baseline.

The production target verifier was tested against relocated rendered skeleton
and account trees. Its actual installed-package version queries are deliberately
excluded from those fixtures, not mocked into an installation acceptance claim.
The real installer retains those package-version checks. Negative tests reject
global Alt+Tab, a globally visible taskbar hidden in a drawer, stale executable
paths, dangling service enablement, stale dependencies, broken fallback fields,
unsafe cleanup parents and unsupported taskbar options.

No native software was compiled. Compiler-dependent NVIDIA test fixtures and a
full unattended installation were not run. There was no live labwc/Waybar
session, target GPU interaction, or kernel AppArmor-enforce acceptance in this
environment. Nothing here claims separate per-workspace taskbars were tested
or implemented: that feature remains unavailable under the retained constraints.

## Publishing

Serve the complete codebase and regenerated publication artifacts together:

```sh
python3 -B tools/build.py --check
python3 -B tools/check_shells.py
python3 -B tools/check_preseeds.py
python3 -B -m unittest discover -s d-i/forky/tests -p test_workspace_no_broker.py -v
```

The older uploaded broker tarballs are superseded for this requested design.
Do not overlay a new archive onto an old server tree without removing obsolete
files: deploy into a clean directory and switch the published snapshot as a unit.
