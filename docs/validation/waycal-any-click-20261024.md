# Waycal: right-click opening and mouse-only dismissal

## Scope and current acceptance

October 24, 2026. Base revision: `c248d1679a6b7740dad78ba1c649ca13647382a5`.
The source implementation and serialized installer products are updated.
Native runtime acceptance remains open. No software was compiled, no tests or
native policy parsers were executed, and no host desktop or manager was used.
There is no prepared disposable Forky environment available for this receipt.

The latest interaction contract supersedes the preceding timed-toggle and hover
designs:

- Right-click the clock to open the existing native Waycal binary on release.
- The next mouse button click anywhere, including the calendar or clock,
  dismisses the popup. The complete ordinary dismissing click is consumed.
- Keyboard input has no dismissal action. No F14/Escape injection, global key
  binding, keyboard grab or keyboard event observer is introduced.
- The existing five-second automatic expiry remains independent of input.
- Left-click opens the GTK calendar dropdown while the popup is closed.

## Observed failure evidence

The checked-in archive at the base revision had 1,839 members. Its two clock
entries had no right-click controller callback, and it contained the retired
`labwc-waycal-toggle` rather than `labwc-waycal-control`. This is a concrete
source/archive mismatch that prevents the current controller from reaching an
installation consuming those bytes. No saved target logs or installed-file
snapshot were supplied, so it does not prove which bytes the reported desktop
was actually running.

The source touchpad policy used `clickfinger`. A one-finger physical press in
the right-hand region can therefore remain a left click. The updated policy
uses `buttonAreas`, preserving `tapButtonMap=lrm` for two-finger right taps.
This is a configuration correction with hardware acceptance still required.

Waybar 0.15.0 dispatches the native menu only when the configured event name
matches. Both layouts keep `menu=on-click` and now use the separate
`on-click-right-release` callback with the fixed `open` action. The opening
release is completed before the helper's input surfaces appear. Queued opening
requests coalesce and cannot toggle a newly started popup off or reset its timer.

## Runtime ownership and cleanup design

1. The existing bounded controller validates its account, runtime directory,
   bus and Wayland socket, serializes requests with its existing private lock,
   and queries only the fixed transient unit. It refuses an unrelated unit or
   an existing Waycal GApplication owner outside that unit.
   The existing `labwc-autostart` activation environment includes
   `WAYLAND_DISPLAY`; it also sets `LABWC_SESSION_OWNER=desktop` in the user
   manager before the session target starts. Those paths were inspected as
   source, without contacting a manager.
2. The user manager starts `labwc-waycal-popup.service`. GNU `timeout` runs the
   new `labwc-waycal-popup` supervisor for five seconds. The supervisor requires
   the expected cgroup-v2 unit component and invocation identifier before
   importing GTK or starting the application.
3. The supervisor creates one transparent GTK3 layer-shell surface per GDK
   monitor, bounded to 32. Each uses the Overlay layer, four anchors and
   exclusive zone -1 to cover the output including Waybar's reserved area.
   The native Waycal Top-layer surface remains underneath; no xdg-toplevel
   identifier, window geometry guess or WindowRule is used.
4. Every surface must map and finish its first frame. A synchronization round
   trip on the supervisor's Wayland connection precedes the fixed child launch
   `/opt/waycal/waycal --week-start monday`. Missing outputs, RGBA visual,
   layer-shell support or frame clock fail closed. Unfinished startup has a
   two-second GLib deadline inside the independent service lifetime bound.
5. Only mouse press/release events trigger input dismissal. Unmatched opening
   releases are ignored. Multiple held buttons retain capture until the last
   matching release. The helper neither replays input nor signals numeric PIDs.
6. Each surface requests layer-shell keyboard mode `NONE`, disables GTK focus
   and focus-on-map, and has no keyboard event handlers. Waycal's unchanged
   native keyboard handling is not replaced: the design leaves its OnDemand
   surface unfocused and intercepts clicks that would focus it. Target acceptance
   must confirm that typing and Escape remain with the existing focused client.
7. A dismissal, child exit, output addition/removal, geometry/scale change,
   surface closure or setup failure removes all capture surfaces and exits the
   supervisor. Pending first-frame callbacks are disconnected during cleanup.
   `ExitType=main` and `KillMode=control-group` retain cleanup ownership of the
   remaining Waycal process through the timeout parent and service cgroup.
8. The existing five-second TERM deadline, one-second forced cleanup allowance,
   six-second systemd runtime backstop and one-second stop timeout remain.
   Stopping the Labwc session or Waybar also requests popup termination.
   `StopPropagatedFrom=waybar.service` does not create a new bar start dependency.

The countdown starts with the timeout command, before toolkit setup. This is
not a measured five seconds of visible calendar time. Output changes close the
popup so stale input geometry is never retained. Normal clicks are consumed
until release; held buttons across forced expiry require native acceptance.
Ordinary same-UID application ownership checks are coordination, not protection
against that UID deliberately racing an independent GApplication launch.

Both helpers are staged at mode 0755. The new supervisor has an explicit
AppArmor profile in `calendars`, a fixed transition to the existing Waycal
profile, paired child-exit signal rules, and an explicit raw-input-device deny.
The compositor's ordinary Wayland event delivery supplies input; there is no
accessibility bridge, evdev reader, virtual keyboard or virtual pointer.
Existing GTK3/GI/layer-shell packages already appear in the desktop role.
The optional offline verifier checks the new typelib and executable paths;
it remains outside the installer's late-command execution path.

## Checks actually performed

| Activity | Observed result | Limit |
| --- | --- | --- |
| Read controller, caller, staging, profile and primary upstream interfaces | Completed static review | No service or GUI execution |
| Python `ast.parse` on both helpers and both changed fixture files | Parsed successfully | No repository imports or fixture execution |
| Python AST on embedded native-menu verifier | Parsed successfully | No target package probes executed |
| JSON parse with inert placeholders in both Waybar layouts | Both clocks use right-release/open and left native menu | Does not execute the renderer |
| XML parse of Labwc source template | `buttonAreas` and `lrm` recorded | No libinput/device operation |
| `git diff --check` | Exit 0 | Whitespace inspection only |
| Reviewed pure `make build` recipe | Exit 0; 1,838 members serialized | No compilation or tests |
| Bounded gzip/tar/hash comparison | All 1,838 members equal current source bytes and manifest; preseed pins match | No extraction or archived-code execution |
| Reviewed `make inventory` recipe | Paired generation from the final archive | Public metadata acquisition only |

Exact generation invocations used a minimal environment:

```sh
/usr/bin/env -i PATH=/usr/bin:/bin LC_ALL=C /usr/bin/timeout 60s /usr/bin/make build 'PYTHON=/usr/bin/python3 -I'
/usr/bin/env -i PATH=/usr/bin:/bin LC_ALL=C /usr/bin/timeout --signal=INT --kill-after=5s 600s /usr/bin/make inventory PYTHON=/usr/bin/python3
```

No `make check`, `make test`, `make validate`, installed helper, systemctl,
systemd-run, busctl, GTK/GI import or AppArmor parser was run for acceptance.
The 14 new popup mock fixture definitions cover opening releases, all button
clicks, simultaneous buttons, first-frame launch ordering, missing frame clocks,
pending callback cleanup, early click, child failure/exit, output changes,
startup expiry, an early show failure, monitor bounds and service context.
They are **unexecuted**.
Existing menu/controller fixtures were aligned with the release callback and
new child command, and verifier fixtures now supply their required styles and
typelib mocks. Those fixtures are also **unexecuted**.

## Working-tree and artifact identity

The payload manifest is the fingerprint of all serialized source inputs,
including the new helper. The two changed fixture definitions are fingerprinted
as the concatenation of each basename, a NUL byte and its raw bytes, in the
order `test_native_menu_contract_20260920.py`, then
`test_native_menu_verifier_20260922.py`:
`f5f0da8ea9e2c8f04b3fab7ce2cd0f4532528ed66fd6cedf00dea1735e25a9ce`.

| Product | SHA-256 |
| --- | --- |
| `d-i/forky/payload.tar.gz` | `be656869d2cb3ac213379dd8c377a5db7a0450133620fb7bd034bde71682c31b` |
| `d-i/forky/payload.manifest` | `1ceccfd7710c81496641cd5bcb5b185c137324fb11d13f666060ac530f835a31` |
| `d-i/forky/preseed.cfg` | `999b053b8f18f3fae8f59f13a524aaad0817c4f4218cedfc3f42b8f9fe144b1e` |
| `inventory.json` | `d1f5977b31239728d9dd46837ce3ec630411d65276e6e911c6879cfb6401fae5` |
| `inventory-apt.json` | `ee17eeba0583b474e5ae4cc3c65d800c698297552ad8c4c4476718bc13d22ca0` |

The final archive contains 34,919,256 source bytes. Its tar stream is
36,372,480 bytes; compressed size is 26,626,138 bytes. Archive comparison was
bounded to 40 MB compressed, 100 MB expanded, 4,096 members and 20 MB per member.

Final inventory generation completed with 29 Release records, 97 index records,
21,359 retained package candidates, zero acquisition errors and zero missing
package requests. Both inventories reference the final archive's size and
SHA-256, and `inventory.json` references the exact APT metadata digest above.
The collector checks public HTTPS transport and Release/index byte consistency;
it does not perform OpenPGP signature verification. These data are not evidence
of an installed target package set or an APT solver result.

## Remaining acceptance gates

An approved disposable Forky environment must supply its own compositor,
systemd 262 user manager, AppArmor policy, target packages and sockets, without
host mounts or forwarded desktop/manager sockets. Image identity and installed
package versions remain unmeasured. Public APT candidates are acquisition data,
not evidence of installed target versions or native compatibility.

Required native observations are mouse and touchpad right-click opening in both
layouts; first-click dismissal on calendar, clock, desktop and another output;
typing/Escape without focus theft or dismissal; complete click consumption;
first-frame behavior with mixed scales; rapid requests and stop/collection;
hotplug and output reconfiguration; child failure and stalled compositor;
five-second expiry, held buttons across expiry, Waybar restart and logout;
AppArmor transitions/signals in enforce mode; and no stranded surfaces or
remaining service-cgroup descendants. Existing native application launch and
private Zoom/Discord launch/shutdown remain regression gates. Their eligibility
and Xwayland policy were not changed. No deployment, commit or push was made.

## Changed paths

```text
d-i/forky/hooks/target/etc/apparmor.d/calendars
d-i/forky/hooks/target/etc/skel-desktop/.config/labwc/rc.xml.tmpl
d-i/forky/hooks/target/etc/skel-desktop/.config/waybar/config.tmpl
d-i/forky/hooks/target/usr/local/libexec/labwc-waycal-control
d-i/forky/hooks/target/usr/local/libexec/labwc-waycal-popup
d-i/forky/scripts/desktop/components/target-assets.sh
d-i/forky/scripts/desktop/verify.sh.tmpl
d-i/forky/scripts/firstboot/04-validation.sh.tmpl
d-i/forky/tests/test_native_menu_contract_20260920.py
d-i/forky/tests/test_native_menu_verifier_20260922.py
d-i/forky/payload.tar.gz
d-i/forky/payload.manifest
d-i/forky/preseed.cfg
inventory.json
inventory-apt.json
docs/calendar-and-wifi.md
docs/validation/waycal-any-click-20261024.md
```

Primary interface references:
[Waybar 0.15.0 event dispatch](https://github.com/Alexays/Waybar/blob/0.15.0/src/AModule.cpp),
[pinned Waycal source](https://github.com/ForrestKnight/waycal/blob/b9b5abd73fbaebf0756157ad141e509410ff181c/src/main.rs),
[GTK layer-shell API](https://wmww.github.io/gtk-layer-shell/),
[GTK3 frame clock](https://docs.gtk.org/gtk3/method.Widget.get_frame_clock.html),
[Labwc 0.20.2 layer focus](https://github.com/labwc/labwc/blob/0.20.2/src/layers.c),
[Labwc touchpad parser](https://github.com/labwc/labwc/blob/0.20.2/src/config/rcxml.c),
[systemd 262 transient dependency support](https://github.com/systemd/systemd/blob/v262/src/core/dbus-unit.c).
