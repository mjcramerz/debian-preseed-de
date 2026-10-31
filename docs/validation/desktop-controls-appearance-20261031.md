# Desktop controls and appearance source review — 2026-10-31

## Scope and revision

Base revision: `a65cd701f8712238cc9b697eb8f9da31431f7be1` (`mcr/main`).
Working-tree change fingerprint: `72c880852e6fe3f930dded96415eb2bc7852d8a4ddb1d84c44c18bc3f087dc0d`.
The fingerprint hashes each sorted changed source/fixture path, its decimal permission mode,
and its SHA-256 bytes, separated by NUL bytes; generated products and this report are excluded.
The payload manifest identifies the complete serialized payload input snapshot separately.

Target contract: Debian Forky, systemd 262; Python modules are staged under
`/usr/local/lib/python3.14/dist-packages`. Existing installer minimums remain
Labwc 0.20.2, Waybar 0.15.0 and Fuzzel 1.15.0. No installed target package set
or bootable target image was inspected or executed in this work.

All 92 files under `todo/` were read as data (4,903,263 bytes).
The ordered path/content digest is
`a2c75487552276026a1dfc93a8231c5d6a656d3afa1c95ba3a03016a41650798`
(SHA-256 over sorted path + NUL + binary SHA-256 of each file).
Pending CrowdSec/Tailscale enrollment is informational.

## Implemented contracts, in requested order

1. Internal panel height increases by 2 px, base font and icon sizes by 1 px,
   with small button width/padding increases across all ten desktop profiles.
   Workspace buttons gain the same vertical margins as application controls,
   a 30 px minimum content width, 7 px horizontal padding and an explicit
   workspace radius (14 or 18 px). Application content width is 28 px.
2. The user selected **hover reveal** for quick controls after the packaged
   Waybar click-propagation limitation was identified. Both output classes now
   use hover, and the same System controls leader retains its native right-click
   menu. The installer checks this configuration. The menu has one submenu
   level; WireGuard connections open directly from the Network submenu.
3. All eight GTK menus use regular icon names. Base dropdown icon values lose
   symbolic suffixes; GTK prefers regular icons. Existing icon-theme selection
   remains connected to the native menu stylesheet. The installer rejects a
   symbolic menu image name. Bar glyphs remain configured separately.
4. The system menu has 55 actions, with fewer duplicate reports/presets and
   direct access to applications, appearance, networking, reminders, capture,
   diagnostics and storage. The dispatcher defines the sound command before
   aliases read it, fixing the logged import-time KeyError. Existing dispatcher
   aliases remain for compatibility. Installation verification parses aliases
   as AST data and rejects references to keys not yet registered.
5. The persistent output watcher subscribes, attempts bounded initial output
   reconciliation, then sends systemd readiness. Existing After dependencies
   now wait for that boundary. Startup does not join a dock job ordered after
   the watcher itself. A rejected transaction is reported as failure and is
   submitted once; the watcher stays subscribed and waits for a later event
   with a fresh snapshot. The shared lock, topology identity recheck, dock and
   authority cleanup, raw capture wait status and existing hardware settings
   remain in their established paths.
6. Waybar actions use readable unique service names, exec startup acknowledgement,
   session shutdown conditions, cgroup lifetime and explicit stop deadlines.
   Loader/GUI injection variables are also removed from the service environment.
7. Calendar credential delivery allows a bounded ten-minute KWallet interaction
   and does not automatically repeat a cancelled or timed-out prompt. A menu
   action retries explicitly. Existing private input, identity checks, readback,
   durable receipt and unlink ordering are retained.
8. Appearance has one Components selector including Desktop Themes. Per-component
   Default/Custom/palette choices update draft fields using the native renderer
   in memory. Other component drafts survive preset changes and preview failures.
   Manual edits select Custom and update the color swatch. Component resets use
   captured installed field defaults. Desktop, cursor and icon selectors have
   Apply/Reset controls; combined desktop reset uses the existing transaction.
   Descriptive labels below fields are removed. Registry line references and
   the AppArmor allowance for `waybar/style/gtk.css` are aligned.

## Follow-up integration — Apps drawer and Crystal Dock

The Apps drawer keeps `click-to-reveal=true` and the `custom/apps` module as
its first member, so Waybar owns the left-click toggle. Waybar 0.15 latches
the group CSS node's `PRELIGHT` state while the drawer is open; the Apps leader
now uses the group-state selector `#apps:hover #custom-apps` (with the newer
`.expanded` compatibility selector). The standalone `#custom-apps:hover`
bright rule was removed, so closing the drawer clears the active appearance
even when the pointer remains over the leader. The installer verifier checks
the drawer leader, event ownership and stylesheet state selector in both
rendered output layouts.

Crystal Dock icon limits increased by four pixels at both ends in every profile:
standard profiles are now `54/84` (minimum/maximum), compact HP14 profiles are
`46/64`, and the detector, desktop renderer and both staged appearance outputs
use `54/84` fallbacks. Menu icon and font sizes remain profile-owned.

## AppArmor parser failure follow-up — 2026-10-31

The first installation attempt exposed a real policy defect that the prior
changed-file audit did not catch: `desktop-wrappers` used
`unix (send) type=dgram peer=(addr="/run/user/[0-9]*/systemd/notify")`.
AppArmor `addr=` conditions describe abstract or anonymous Unix socket
addresses. Filesystem pathname sockets are mediated by ordinary file rules.
The invalid peer rule was removed; the existing owner file rule for the
systemd notify pathname and the datagram creation rule remain.

The changed-file audit now rejects any Unix rule whose `addr=` value begins
with `/`, including a peer address, before publication. A failure-injection
case records this contract in the desktop controls fixture.

The corrected rendered policy was compiled offline with private configuration,
include, feature, cache and base paths using `apparmor_parser 4.1.8` from
Debian package `apparmor 4.1.8-3` (amd64, package SHA-256
`ca1f7e9ff3e23bd1ba8d02b76879301eecbc25d580bbfdfec5774b2557b5537a`). The
parser used `--skip-kernel-load`, `--skip-cache`, and one compile job. The
pre-edit candidate reproduced the reported line-3050 failure; after the fix,
all 143 staged policies passed, including the 48 checkout-owned profiles and
their private package support files. No host policy was loaded.

Native application launching and the existing private Zoom/Discord Xwayland
implementation/configuration were preserved in source; their live behavior was
not exercised.

## Two source review rounds

- Round 1: geometry/schema/renderer alignment, native menu IDs and dispatcher
  initialization, profile/icon contracts and appearance draft/default mappings.
  Corrected stale registry source lines and the preview's native path prefix.
- Round 2: caller/delegate/staging/policy boundaries, startup dependency ordering,
  notification environment and cgroup ownership, error propagation, credential
  recovery, preview failure behavior and unexecuted fixture interfaces.
  Corrected a possible dock/readiness self-wait and prevented watcher restart
  churn after rejected modesets. Reviewed fixture syntax after editing.

The attempted read-only agents failed during initialization; no child findings
are claimed. Both review rounds were performed by the integrating agent.

## Verification actually performed

- Required `python3 -B tools/post_change_check.py`: PASS on the generated working
  tree. It checked 562 appearance fields, 626 mappings, 604 native color tokens,
  ten geometry profiles, changed Python/shell/structured data and AppArmor
  structural hazards. The initial audit found stale registry line references;
  those were fixed before the recorded pass.
- Inline standard-library AST/JSON/XML data audit: eight menus, 109 wired leaves,
  55 system actions, ordered dispatcher aliases, two hover drawers and embedded
  installer Python syntax. No dispatcher/module was imported or executed.
  An early delegate-path check stopped on the calendar aliases; source inspection
  confirmed they are installed as links to `labwc-app` by `target-assets.sh`.
- Inline deterministic substitution and tinycss2/XML/JSON parsing: 310
  asset/profile combinations, with no unresolved theme or installer tokens.
  CSS parsing is not evidence of GTK rendering or layout.
- Reviewed pure `make build`: serialized 1,935 payload members. Every archive
  member was compared byte-for-byte with its source and manifest hash; metadata
  was checked as regular mode 0644. Payload and manifest pins occur in preseed.
- Follow-up data-only contract audit: both Apps state selectors are present,
  the standalone leader-hover rule is absent, all ten profiles resolve to
  `54/84` or `46/64`, the three renderer fallback paths resolve to `54/84`,
  and the rebuilt archive has 1,935 manifest-matching members.
- Offline AppArmor parser: PASS for all 143 private staged policies after the
  policy fix; the pre-edit candidate failed only at the reported invalid
  filesystem `addr=` condition.
- `git diff --check`: PASS.

No tests, fixture runners, installer, GUI, services, D-Bus calls, managed helpers,
network/device integration, host policy loading or disposable environments ran.
The offline AppArmor parser operated only on private staged data with kernel
loading and cache writes disabled. No source software was compiled.

## Unexecuted failure fixtures

The existing guarded Python fixtures were updated for preview failure/hidden drafts,
Custom selection, unique cgroup ownership, rejected transaction non-replay, watcher
continuity and dock/readiness dependency handling. The JSON cases also describe
credential cancellation/input replacement and retained recovery evidence. These
are source cases, not passing execution results.

- `d-i/forky/tests/fixtures/contracts/desktop-controls-failures-20261031.json`: `81964af6258cc8fee68581b5a10070e83b2a192cc9f9472e9e92650d7ffcde39`
- `d-i/forky/tests/test_appearance_picker_contract_20261027.py`: `489e59873afa9abfd74fea6f739c067b44dd5b15e97cc6a3957abc3e55b71044`
- `d-i/forky/tests/test_atomic_output_r3_20260921.py`: `d33ada702196ae8b82199718597b2c1f500c662fdf70cd6a30aa472332b501a4`
- `d-i/forky/tests/test_waybar_button_runtime_20261027.py`: `eef2db44121c5a6d9f09951cee42f835c4744dc42d026f4760605d05e9befda0`

## Generated SHA-256

- `payload.tar.gz`: `f28e02978e6ff63ec73d24483824b2f697ef22809c7569a1226800228ba48e9f`
- `payload.manifest`: `d2a708ff54cc3152e01e8e5c52ba47e2175abb2de8cd75fb4ecd3dff0009ede5`
- `preseed.cfg`: `fa299390928f2d7b16687a7e876c8c8eb73584f4c8530a5a7f7e8d1ab245e52d`

## Remaining target verification limits

The supplied journal has ten eDP-1 atomic-commit EBUSY reports without matching
output-transaction begin/end records. Those logs do not establish their historical
cause. The ordering and failure-handling defects above are repaired in source;
**elimination of all DRM failures remains unverified**. No global kernel or
compositor workaround was added. Target GUI sizing, hover/submenu behavior,
regular-icon availability in each chosen theme, KWallet completion, transient
service startup, AppArmor enforcement and reboot/session behavior remain
unverified. Serialization consistency establishes matching bytes only.

## Exact changed source and fixture paths

- `d-i/forky/hooks/target/etc/apparmor.d/desktop-wrappers.tmpl`
- `d-i/forky/hooks/target/etc/apparmor.d/labwc-appearance`
- `d-i/forky/hooks/target/etc/skel-desktop/.config/systemd/user/labwc-calendar-credentials.service`
- `d-i/forky/hooks/target/etc/skel-desktop/.config/systemd/user/labwc-output-watch.service`
- `d-i/forky/hooks/target/etc/skel-desktop/.config/waybar/gtk/system-menu.xml.tmpl`
- `d-i/forky/hooks/target/etc/skel-desktop/.config/waybar/modules/external-quick-controls.tmpl`
- `d-i/forky/hooks/target/etc/skel-desktop/.config/waybar/modules/internal-quick-controls.tmpl`
- `d-i/forky/hooks/target/etc/skel-desktop/.config/waybar/modules/system.tmpl`
- `d-i/forky/hooks/target/etc/skel-desktop/.config/waybar/style/apps.css.tmpl`
- `d-i/forky/hooks/target/etc/skel-desktop/.config/waybar/style-common.css.tmpl`
- `d-i/forky/hooks/target/etc/skel-desktop/.config/waybar/style/gtk.css.tmpl`
- `d-i/forky/hooks/target/usr/local/bin/labwc-autostart`
- `d-i/forky/hooks/target/usr/local/bin/labwc-system-menu-action`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_appearance/cli.py`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_appearance/editor.py`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_appearance/engine.py`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_appearance/fields.py`
- `d-i/forky/hooks/target/usr/local/libexec/labwc-output-watch`
- `d-i/forky/hooks/target/usr/local/libexec/labwc-waybar-run`
- `d-i/forky/hooks/target/usr/local/share/labwc-appearance/fields.json`
- `tools/post_change_check.py`
- `d-i/forky/hosts/profiles/btrfs-de-duo.env`
- `d-i/forky/hosts/profiles/btrfs-de-flex-duo.env`
- `d-i/forky/hosts/profiles/btrfs-de-flex.env`
- `d-i/forky/hosts/profiles/btrfs-de-p15s-duo.env`
- `d-i/forky/hosts/profiles/btrfs-de-p15s.env`
- `d-i/forky/hosts/profiles/btrfs-de.env`
- `d-i/forky/hosts/profiles/f2fs-de-hp14-duo.env`
- `d-i/forky/hosts/profiles/f2fs-de-hp14.env`
- `d-i/forky/hosts/profiles/f2fs-de-x360-duo.env`
- `d-i/forky/hosts/profiles/f2fs-de-x360.env`
- `d-i/forky/hosts/themes/base.env`
- `d-i/forky/scripts/desktop/components/core-renderers.sh.tmpl`
- `d-i/forky/scripts/desktop/components/desktop-helpers.sh`
- `d-i/forky/scripts/desktop/detect.sh.tmpl`
- `d-i/forky/scripts/desktop/verify.sh.tmpl`
- `d-i/forky/scripts/desktop/waybar-geometry.tsv`
- `d-i/forky/tests/fixtures/contracts/desktop-controls-failures-20261031.json`
- `d-i/forky/tests/test_appearance_picker_contract_20261027.py`
- `d-i/forky/tests/test_atomic_output_r3_20260921.py`
- `d-i/forky/tests/test_waybar_button_runtime_20261027.py`
