# Waycal click mapping, styling and current log review — 2026-10-24

> Historical snapshot: the later [alternate clock format removal](clock-format-removal-20261024.md)
> supersedes this report's middle-click mapping and generated artifact hashes.
> Its earlier implementation and acceptance evidence remain recorded below.

## Accepted behavior

The user's final instruction replaces the hover experiment with this mapping
for **Waybar 0.15.0**, on both the internal and external bars:

| Input | Required action |
| --- | --- |
| Left click / normal touchpad click | Native GTK clock dropdown; no clock-format change |
| Middle click | Toggle the existing alternate clock format only |
| Right click | Open Waycal when closed; close the managed popup when open |
| Hover | No tooltip text and no popup launch |

The dark purple theme and interactive task-label corrections remain requested.
The earlier [hover/MOK report](todo-waycal-mok-20261024.md) records an earlier
working tree. Its hover description and hashes are superseded by this report.
The prior MOK 900-second and single automatic route changes remain incorporated.

Base revision: `e1f929c73033bfed247e51b90a2574880503c786`, branch `mcr/main`.
Target contract: Debian Forky, Python 3.14, systemd 262. These are requirements,
not development-host package observations. No application was compiled.

## Current saved logs

The supplied `todo/` snapshot changed since the earlier review: it now contains
43 regular files, 27 empty. Inspection was bounded and read saved files as data.

| Current evidence | Disposition |
| --- | --- |
| `todo/apparmor.log`: Agenda denies execution of `/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2`; same event in managed AppArmor log line 444 | Added inherited execution for that exact package loader in the Agenda profile. The process remains confined as Agenda. The earlier owner-qualified `/proc/.../cmdline` read permission remains. Native launch is unverified. |
| `todo/apparmor.log`: three hover-adapter ptrace reads denied against `unconfined` | Retired the hover helper, its autostart unit, AT-SPI bridge override and ptrace rules. The replacement toggle reads one fixed user-unit state and never inspects another process's executable. No broader ptrace permission was added. |
| Current apps log: Calix duplicate `gdk_frame_timings_presented()` warning | Added the app-local GTK Wayland frame-callback fallback, `GDK_WAYLAND_DISABLE=wp_presentation`. Native Wayland rendering and diagnostic output remain. This is a compatibility workaround; the warning's absence and visual behavior are not yet demonstrated. |
| CrowdSec Console enrollment, duplicated vendor grok definitions and absent optional qBittorrent log | Console approval remains manual; no remote enrollment action or enforcement reduction. The latter warnings do not establish a local API/bouncer failure. |
| USB/UCSI error 88 and `UCSI_GET_PDOS failed (-5)` | Hardware/controller investigation remains open. No speculative driver or power workaround. |
| Saved journal: GVFS user cgroup could not kill `gvfsd-fuse`/`fusermount3` at logout | Changed the existing user-service drop-in from `KillMode=mixed` to `control-group`, preserving its 15-second budget. Cleanup children receive the grace period instead of immediate escalation when the main daemon exits. No new capability or signal permission was granted. Native logout acceptance remains open. |
| Saved journal: XFS healer unit changed-on-disk warning, followed by successful starts for `/data` and `/pool` | Added a bounded manager-cache refresh before the native healer starter's initial scan. Staging remains offline. The log does not establish which writer caused the stale metadata; native boot must demonstrate both warning absence and successful healer starts. |
| Journal: initial Tailscale warming-up/stopped state, authentication failure, thermal interlock, unavailable public Xwayland | Startup transition and failed credentials do not justify configuration changes. Preserve the thermal safeguard and the requested private Zoom/Discord-only Xwayland implementation. |

`debian-preseed-de-audit.md` is absent in this checkout, so no additional
acceptance evidence is attributed to that referenced file.

## Implementation

Both clock definitions now use integer `format-alt-click: 2`, retain
`menu: on-click` without a competing left-click command, and disable tooltips
with `tooltip: false`. The `Calendar` tooltip-format marker is removed.
The [0.15.0 ALabel handler](https://github.com/Alexays/Waybar/blob/0.15.0/src/ALabel.cpp)
toggles format only for the configured GDK button. The provided logs do not
include the target's loaded JSON, so the reported prior left-click behavior
cannot be attributed to an observed rendered configuration.

The fixed right-click command starts `labwc-waycal-toggle.service` without
blocking Waybar. Its on-demand oneshot prevents concurrent toggle commands;
overlapping starts during a running toggle coalesce. The root-owned Python
helper queries only `labwc-waycal.service` and submits one bounded start or
stop request. A failed state read prevents mutation. An uncertain mutation is
reported and is not retried. The popup service retains native Wayland,
Monday-first week, its own cgroup and session ownership. Escape also closes it.
Both manually invoked units disable start-rate limiting; neither has an
automatic restart loop.

The former hover helper/unit and their staging, firstboot checks, login wants
links and profile rules are removed or replaced. The new toggle unit is
on-demand and has no login wants link. The optional broad `verify.sh` remains
outside the installation entrypoint; it was updated to the new contract.
The direct hover-only package requests for `gir1.2-atspi-2.0` and `at-spi2-core`
are removed. This does not remove GTK's own accessibility dependencies or
change unrelated applications' accessibility policy.

### User styling drop-in

The pinned [Waycal source](https://github.com/ForrestKnight/waycal/blob/b9b5abd73fbaebf0756157ad141e509410ff181c/src/main.rs)
loads embedded CSS at application priority and has no native config-file/CSS
option. Its [upstream integration](https://github.com/ForrestKnight/waycal/blob/b9b5abd73fbaebf0756157ad141e509410ff181c/README.md)
launches a separate application from a Waybar click.

The installer supplies `~/.config/waycal/style.css`, imported by
`~/.config/gtk-4.0/gtk.css`. GTK4 documents this as a
[user-priority stylesheet](https://docs.gtk.org/gtk4/const.STYLE_PROVIDER_PRIORITY_USER.html),
above the embedded application style. All selectors are scoped to
`window.waycal`. Both built-in variants use a dark purple background at 94%
opacity, a purple border and today highlight, light opaque text and a readable
muted footer. The native sharp/rounded style switch retains its distinct corner
radii. Reopening the popup loads user edits. AppArmor permits those
exact user CSS paths. Staging and primary-account copying include both files.

The GTK Tasks submenu now uses `Create task...`, `Edit task...`,
`Delete task...` and `Mark task completed...` for interactive operations.

### GVFS logout lifecycle

The saved journal shows `gvfsd-fuse` and two `fusermount3` children being sent
SIGKILL as the GVFS main daemon exits, followed by `Operation not permitted`
and remaining-process warnings. There is no preceding 15-second timeout in
that sequence. The repository's `KillMode=mixed` selected the escalation
behavior documented by [systemd 262](https://www.freedesktop.org/software/systemd/man/latest/systemd.kill.html):
the main process exiting is enough to trigger SIGKILL for remaining children.
The new `control-group` setting sends the initial stop signal to the whole
cgroup and permits its existing stop timeout before escalation.

The [GVFS FUSE implementation](https://github.com/GNOME/gvfs/blob/master/client/gvfsfusedaemon.c)
owns the unmount/loop cleanup. The source correction preserves that native
path and session ownership. It does not establish why a later SIGKILL was
denied on the recorded target; that requires native process/mount evidence.
No host manager, FUSE mount or capability was changed during this work.

### XFS healer metadata refresh

The fresh public APT snapshot provides xfsprogs `7.2.0-1` as a Forky candidate.
Its [native starter](https://sources.debian.org/data/main/x/xfsprogs/7.2.0-1/healer/xfs_healer_start.c)
discovers mounts with the package's own mount-identity logic and restarts the
per-mount healer units through `systemctl`. It does not write unit drop-ins.
The recorded `/data` and `/pool` starts succeeded despite the cache warning.

After existing offline XFS unit sanitation, the installer conditionally stages
`/etc/systemd/system/xfs_healer_start.service.d/20-refresh-unit-cache.conf`
only when the native starter unit exists. Its `ExecStartPre` runs the target's
`systemctl daemon-reload` through a 15-second timeout and 2-second kill budget
before the native executable starts its initial scan. No native `ExecStart`
is replaced and no mount scanner or healer is reimplemented. This enforces
fresh staged metadata at that boundary; a runtime writer racing afterward is
not excluded by the saved logs. Boot acceptance remains required.

### Calix presentation timing

The public APT metadata candidate is GTK `4.24.1+ds-1`; that is not proof of
the affected target's installed version. GTK 4.24.1's
[Wayland presentation feedback](https://github.com/GNOME/gtk/blob/4.24.1/gdk/wayland/gdkwaylandpresentationtime.c)
and [frame callback fallback](https://github.com/GNOME/gtk/blob/4.24.1/gdk/wayland/gdksurface-wayland.c)
provide separate timing paths. The [GTK runtime documentation](https://docs.gtk.org/gtk4/running.html)
allows protocol names in `GDK_WAYLAND_DISABLE`.

The Calix entry in the shared managed-launch profile sets that variable to
`wp_presentation`. Existing environment construction applies it only to Calix;
Waycal, Agenda and other applications retain their previous environment. This
uses native Wayland frame callbacks while keeping rendering, the compositor
and warning output enabled. The tradeoff is fallback timing estimates instead
of the optional presentation protocol's precise timestamps. This is a scoped
compatibility mitigation, not evidence of a reproduced upstream root cause or
a proven native fix. It needs a Calix launch and visual/diagnostic acceptance
on the target before being considered resolved at runtime.

## Verification boundary

No test suite, fixture, native syntax runner, AppArmor parser, display client,
service manager or UEFI operation was executed on the development host.
No approved disposable target has been supplied. Authored focused fixtures
cover toggle states, failed state reads, uncertain mutation without retry,
invalid invocation and the new menu/style wiring; they remain **unexecuted**.
Existing regression fixtures also record the GVFS stop policy, conditional XFS
drop-in staging and Calix-only environment. The GVFS historical workload hash
is retained by reversing only the exact reviewed lifecycle hunk in its existing
fixture normalizer, without rebasing old expected hashes.
The attempted independent agent review failed to start with a content hydration
error, and supplies no review evidence.

Completed static checks use the standard library without importing repository
code: changed Python ASTs, both changed embedded verifier blocks, the shell
single-quote boundary around the menu verifier, both JSON clock definitions
with unrelated-token numeric stand-ins, XML task labels and source/diff review.
A quoting defect introduced in the optional verifier was caught by review and
corrected before final publication. Intermediate generation passes preceded
the later GVFS/XFS/Calix and styling changes; the final receipt below supersedes
those intermediate products.

Native acceptance still requires the target's loaded Waybar 0.15.0 JSON,
repeated mouse/touchpad clicks, right-click open/close and Escape, actual GTK4
style loading, session logout cleanup, Agenda startup under loaded AppArmor,
XFS boot cache/start ordering, Calix presentation behavior and unchanged
native/private Zoom/Discord launches. Earlier MOK/UEFI acceptance
also remains unexecuted. Static consistency does not prove those outcomes.

## Final generation receipt

Both reviewed generation commands returned exit status 0:

```text
make build PYTHON=/usr/bin/python3
make inventory PYTHON=/usr/bin/python3
```

The build serialized **1839** regular payload members, **34,897,451** expanded bytes.
A bounded streaming archive read, without extraction, compared every member with
its current source bytes and manifest digest, checked the complete member set
and normalized archive metadata, and confirmed all three preseed hash pins.
The retired hover helper and unit are absent from the payload.

The inventory refresh acquired 29 Release files and processed 97 indexes,
retaining **21,359** candidates with zero unavailable metadata requests. It scanned
1,809 text members, including 353 relevant sources. All 691 package requests
have indexed candidates. Both inventories reference the exact payload hash and
size below; the inventory's APT metadata digest matches its paired JSON file,
and all package/dependency candidate indices are in range and canonical.
This is metadata coverage, not a solved installation. The collector records
Release OpenPGP verification as not performed; consumers still authenticate
metadata with their configured archive keys.

| Generated path | Bytes | SHA-256 |
| --- | ---: | --- |
| `d-i/forky/payload.manifest` | 226692 | `cfadcaa56713a296d1929913a168bafe1b82816797b9fdc9adbf220ce276df72` |
| `d-i/forky/payload.tar.gz` | 26621104 | `70e83859ed8b07f98d70fc546d67b0e52d541688f4a0f60361381f4d8b5781bb` |
| `d-i/forky/preseed.cfg` | 96407 | `5f91b67bf4ad3ed52f8ff2f00993b6eb2f3f09bf18f60834de104ec743f379c3` |
| `inventory-apt.json` | 19190436 | `cdf364e7c9884fd0201a78f46a939d247f8d59536b9bca14fbe57ff338e5b686` |
| `inventory.json` | 2489201 | `81118814d87bf27af27cbaba5c70332756d9a306f4d0322af71070ed930605ac` |

The 24 changed payload source paths below have working-tree fingerprint
`4ac56d08c9e5a0f1f1fdebbccf6494f0f2d7a797211c7a1ed8ce70b7da48c7ad`.
The seven changed fixture paths have fingerprint
`249a8aa7d11b7365ae54caa64045a45ce666c65337938702ade669f2a651b428`.
Each digest hashes sorted repository-relative UTF-8 path, NUL, current file
bytes, NUL; deleted paths use the literal bytes `<deleted>`. Generated products
and fixture paths are excluded from the source-input digest. The base revision
is recorded above. These identify the reviewed uncommitted inputs; they are
not a native acceptance receipt or a commit ID.

Current public metadata includes Waybar `0.15.0-1+b1`, systemd `262-1` /
`262.1-1`, GVFS `1.62.0-3`, GTK `4.24.1+ds-1` and xfsprogs `7.2.0-1`
alongside other configured Debian suites. No installed target package versions
or disposable image identity were observed. No runtime deployment, service
restart, host repair, application compilation or native test was performed.

## Exact changed paths

### Payload sources

- `d-i/forky/classes/class-select/role/desktop.cfg`
- `d-i/forky/hooks/target/etc/apparmor.d/calendars`
- `d-i/forky/hooks/target/etc/apparmor.d/labwc-session`
- `d-i/forky/hooks/target/etc/skel-desktop/.config/gtk-4.0/gtk.css`
- `d-i/forky/hooks/target/etc/skel-desktop/.config/systemd/user/labwc-waycal-hover.service` (removed)
- `d-i/forky/hooks/target/etc/skel-desktop/.config/systemd/user/labwc-waycal-toggle.service`
- `d-i/forky/hooks/target/etc/skel-desktop/.config/systemd/user/labwc-waycal.service`
- `d-i/forky/hooks/target/etc/skel-desktop/.config/systemd/user/waybar.service`
- `d-i/forky/hooks/target/etc/skel-desktop/.config/waybar/calendar-menu.xml.tmpl`
- `d-i/forky/hooks/target/etc/skel-desktop/.config/waybar/config.tmpl`
- `d-i/forky/hooks/target/etc/skel-desktop/.config/waycal/style.css`
- `d-i/forky/hooks/target/etc/systemd/system/xfs_healer_start.service.d/20-refresh-unit-cache.conf`
- `d-i/forky/hooks/target/etc/systemd/user/gvfs-daemon.service.d/10-labwc-session.conf`
- `d-i/forky/hooks/target/usr/libexec/install-tools/secure-boot-tool.tmpl`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/profiles.py.tmpl`
- `d-i/forky/hooks/target/usr/local/libexec/labwc-waycal-hover` (removed)
- `d-i/forky/hooks/target/usr/local/libexec/labwc-waycal-toggle`
- `d-i/forky/scripts/desktop/components/services.sh`
- `d-i/forky/scripts/desktop/components/target-assets.sh`
- `d-i/forky/scripts/desktop/components/user-config.sh`
- `d-i/forky/scripts/desktop/verify.sh.tmpl`
- `d-i/forky/scripts/firstboot/04-validation.sh.tmpl`
- `d-i/forky/scripts/late/grub.sh`
- `d-i/forky/scripts/late/storage-maintenance.sh`

### Authored or updated fixtures — unexecuted

- `d-i/forky/tests/refactor_fixture.py`
- `d-i/forky/tests/test_comprehensive_contracts_20261017.py`
- `d-i/forky/tests/test_desktop_integration_20260914.py`
- `d-i/forky/tests/test_desktop_sandbox.py`
- `d-i/forky/tests/test_installer_hardening.py`
- `d-i/forky/tests/test_native_menu_contract_20260920.py`
- `d-i/forky/tests/test_systemd_resource_policy.py`

### Generated products

- `d-i/forky/payload.manifest`
- `d-i/forky/payload.tar.gz`
- `d-i/forky/preseed.cfg`
- `inventory-apt.json`
- `inventory.json`

### Documentation

- `docs/calendar-and-wifi.md`
- `docs/validation/todo-waycal-mok-20261024.md` (historical snapshot; superseded click contract marked explicitly)
- `docs/validation/waycal-click-20261024.md`

## Deployment boundary

These changes describe new installer output. Rebuilding does not change an
already installed desktop, unload its old AppArmor profiles or stop its old
hover service. Any update of that existing installation must also retire the
previous hover unit/helper and its wants link before verifying the new clock
controls. No such live update was performed here. Native acceptance and the
reported hardware/controller or remote-account issues listed above remain
separate open gates.

## Completion audit — continuation on 2026-10-24

The preceding goal turn made source and generated-artifact progress. This
continuation reread the attachment, current worktree, staging paths, user units
and AppArmor rules, and checked the complete upstream button dispatch path.
It does not reinstate hover: the user's later right-click request is the
accepted interaction contract.

In Waybar 0.15.0, [ALabel::handleToggle](https://github.com/Alexays/Waybar/blob/0.15.0/src/ALabel.cpp)
compares the event button to `format-alt-click` before switching formats, then
delegates to the module handler. The [event map](https://github.com/Alexays/Waybar/blob/0.15.0/include/AModule.hpp)
maps buttons 1/2/3 to left/middle/right actions. The
[module dispatcher](https://github.com/Alexays/Waybar/blob/0.15.0/src/AModule.cpp)
opens a configured GTK menu for its matching event, then executes a configured
click command. The [clock class](https://github.com/Alexays/Waybar/blob/0.15.0/include/modules/clock.hpp)
does not override that button handler. This supports the current source
configuration; it is not a native click test.

| Requirement | Current authoritative evidence | Completion status / missing proof |
| --- | --- | --- |
| Left click opens GTK menu without changing clock format; middle click alone changes format | Both source clock entries use button 2, `menu: on-click`, and no competing left/middle command; upstream 0.15.0 dispatch reviewed | Source/artifact consistent. Need the target's rendered and loaded JSON plus mouse/touchpad observations. |
| Right click opens and closes Waycal | Fixed helper/unit staging, one state query and one start/stop request, managed popup cgroup and session lifetime | Source/artifact consistent. Need native open/close, Escape, repeated-click and session-stop observations. Closely overlapping oneshot starts coalesce as documented above. |
| No Calendar tooltip or a11y hover bridge | Tooltips disabled; former marker/helper/unit, login activation and clock-specific bridge/ptrace wiring removed | Source/artifact consistent. Need a fresh target session showing no tooltip and no old installed hover unit. |
| Dark purple Waycal with slight background transparency and editable user drop-in | Scoped GTK4 user CSS at 94% background opacity; import, account copying, installed modes and exact AppArmor read rules traced | Source/artifact consistent. Need actual GTK CSS load and visual acceptance for both native style variants. |
| Interactive task labels end in three dots | Four XML labels parsed from current template; packaged bytes match source | Source/artifact consistent. Need the rendered GTK submenu and interactive actions observed on target. |
| Resolve recorded Agenda and hover AppArmor denials | Exact Agenda loader inherited-exec rule; retired hover implementation and permission set | Source/artifact consistent. Need policy parsing/loading and Agenda launch in an isolated native target, with no corresponding denial. |
| Resolve GVFS logout, XFS healer warning and Calix presentation warning | Current lifecycle drop-in, conditional healer prestart staging, and Calix-only environment correction reviewed | Corrections incorporated; native outcomes remain unproven. The Calix setting remains a compatibility workaround. |
| Preserve native apps and the private Zoom/Discord boundary; avoid source compilation | No private Xwayland implementation/configuration changes; native launch paths retained; generation receipts above | Source invariant preserved. Native regression acceptance is still unexecuted. |

The audit found no further source correction justified by the evidence reviewed.
The remaining blocker is native acceptance in an explicitly prepared disposable
Forky environment. No approved image/runtime or exported acceptance results
were supplied in this continuation. The repository instructions prohibit host
fallback, so no tests, display clients, service managers or policy parsers were
executed. The goal remains incomplete; this audit does not promote source
consistency to runtime acceptance. Only this report changed in the continuation,
so the payload, source/fixture fingerprints and five product receipts above
remain applicable.
