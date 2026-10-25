# Desktop appearance, navigation and downloads — 2026-10-25

## Scope and evidence boundary

This records source changes against HEAD
`aebdbc41aa3d2e7e2447f6aae1ca444c4b874c65` in the working tree.
The payload source fingerprint is the SHA-256 of `payload.manifest` below.
Fixture sources are fingerprinted separately because tests are excluded from
the payload. This document is outside the payload source tree.

Work followed `AGENTS.override.md` and `docs/test-isolation.md`. No tests,
validation runners, native syntax checks, managed application helpers, browser,
Gio resource loader, compositor, package manager, service manager or policy
loader were executed. No disposable execution environment was used. The only
repository programs executed were the explicitly permitted generation paths
for `make build` and `make inventory`.

Independent review agents failed during initialization with encrypted-context
hydration errors. They supplied no review findings. The source review and
integration recorded here were performed by the root agent.

The optimization review covered all 274 uncommitted paths listed below or
enumerated by the pinned asset inventory. The repository guidance names
`debian-preseed-de-audit.md`, but that file is absent from this checkout; no
acceptance result is inferred from it.

## Implemented source contracts

### Navigation and focus loss

- Picker status 0 publishes a selected row; 1 means Back; 2 means a picker
  failure; 3 dismisses the complete workflow. Custom Back output is buffered
  and discarded so a highlighted row cannot become an accidental action.
- Escape and Ctrl+C dismiss the workflow. Win+Backspace uses Fuzzel's
  `custom-1` binding and returns to the previous menu. Parent menu processes
  propagate status 3 instead of reopening.
- The shared Fuzzel base sets `keyboard-focus=on-demand` and
  `exit-on-keyboard-focus-loss=yes`. Management menus inherit the base through
  `menu.ini`; launcher mode does not inherit the custom Back binding.
- Fuzzel 1.15 source inspection showed that keyboard focus loss leaves native
  dmenu status 1, while Escape returns 2 and custom-1 returns 10. The wrapper
  maps clean native 1/2/130 to workflow dismissal and native 10 to Back.
  Bounded, uncolored diagnostics distinguish native startup/configuration
  errors from silent focus loss. Diagnostic errors, unknown nonempty output,
  failed reads and oversized output remain failure status 2. The private
  diagnostic channel is limited to 65,537 bytes and explicitly cleaned up.
- Hardware Tuning returns from its profile or ownership-confirmation menu to
  the appropriate parent. Component appearance confirmations return to the
  component's profile list before returning to Desktop Appearance.
- The unused `labwc-fzf-menu` adapter, staging, policy and backend routing were
  removed. AI & Copilots retains its dedicated fzf entrypoint. Fuzzel's
  `match-mode=fzf` is its native matching algorithm and remains configured.

Primary source inspected as data:
[Debian Fuzzel 1.15 source archive](https://deb.debian.org/debian/pool/main/f/fuzzel/fuzzel_1.15.0+ds.orig.tar.xz).
Native Wayland behavior was not exercised.

### Application themes and complete component profiles

There are 20 application theme brands and 50 variants. A flavor, accent,
light variant or dark variant does not create another brand.

| Brand | Variants |
| --- | ---: |
| Adwaita | 2 |
| Ant | 1 |
| Arc | 2 |
| Breeze | 2 |
| Canta | 2 |
| Catppuccin | 16 |
| ChromeOS | 2 |
| Dracula | 1 |
| Fluent | 2 |
| Layan | 2 |
| Matcha | 2 |
| Materia | 2 |
| Nordic | 1 |
| Orchis | 2 |
| Qogir | 2 |
| Rosé Pine | 3 |
| Sweet | 1 |
| Vimix | 2 |
| WhiteSur | 2 |
| Yaru | 1 |

Each brand has GTK3/GTK4 data or the built-in Adwaita provider and a real Qt6
style provider: Adwaita, Breeze or a paired Kvantum configuration and SVG.
The installer prepares the entire candidate before publishing its asset
directories and publishes the inventory last. Installation and selection
checks reject missing or changed providers. Interrupted publication retains
private candidate/journal evidence; unknown publication and committed cleanup
failure have distinct outcomes. These checks were inspected, not executed.

There are 193 pinned input files totaling 49,444,952 bytes. Their exact paths,
upstream URLs, commits/versions, lengths and hashes are in
`d-i/forky/assets/desktop-themes/sources.json`. The staging list is
`d-i/forky/scripts/desktop/desktop-theme-assets.list`. Upstream archives are
read as data; no upstream installer, maintainer script, Sass compiler or
software build is used. Only GTK3/GTK4 assets are published; GTK2 themes and
engines are not requested. Explicit missing-image repairs for ChromeOS,
Matcha, Qogir and Vimix are recorded in the installed inventory.

The 32 existing component profile identities are retained and ten are added:
Electric Iris, Arctic Cyan, Citrus Graphite, Coral Basalt, Jade Obsidian,
Royal Ink, Fuchsia Smoke, Honey Carbon, Azure Steel and Silver Pine.
All 42 declare background, foreground, accent, 15 additional named color
roles and 16 ANSI colors. Background, surface, raised surface, hover and
pressed colors are distinct within each profile; all 42 base backgrounds
are unique. Bright accents can fill selections and controls. These profiles
remain dark even when the selected application theme is light.

Data-only color arithmetic observed maximum surface/hover/pressed luminance
0.08488678577728671, minimum foreground/hover contrast 8.476356113869056,
and minimum selection-text/accent contrast 7.072954325258633. These numbers
describe declared colors, not rendered application acceptance. Supported
native keys cover Fuzzel, Waybar, Crystal Dock, GTK greeter CSS, Foot and
Kitty. CSS state rendering includes hover/focus/pressed/selected states,
gradients, outlines and glow; layout and fonts are preserved. Components
receive only effects supported by their native formats.

The Desktop Themes menu replaces the Dark/Light Mode menu. Selection writes
GTK3/GTK4 settings, an owned GTK4 CSS import, Qt6ct settings/palettes, Kvantum
selection where applicable, GSettings and Labwc server decoration colors.
Reset Theme uses the installation's captured defaults, including the previous
absence of optional files. Component selections remain independent.
Agenda's app-specific `GTK_THEME` override was removed. Managed native apps
receive the configuration directories read-only so atomic file replacement
remains visible. Refresh targets the existing Labwc/Waybar systemd units;
applications that cache style state may need reopening.

### Qt6ct defaults and Qt5 compatibility

The following remain `qt6ct`:

- `hosts/themes/base.env`: `LABWC_DESKTOP_QT_PLATFORMTHEME="qt6ct"`.
- `labwc_managed_app/environment.py`: fallback for `QT_QPA_PLATFORMTHEME`.
- `usr/local/bin/labwc-qbittorrent`: fallback for `QT_QPA_PLATFORMTHEME`.

Both `qt5ct` and `qt6ct` packages and configuration support remain. Qt6
palettes contain 22 roles, including Accent; Qt5 palettes contain 21 roles.
The installation check explicitly requires the rendered desktop platform
theme to remain `qt6ct` and verifies the Qt5/Qt6 frontend and style plugins.
Debian's official file lists confirm the frontend paths for
[Qt6ct in Forky](https://packages.debian.org/forky/amd64/qt6ct/filelist) and
[Qt5ct in sid](https://packages.debian.org/sid/amd64/qt5ct/filelist).

The refreshed APT data exposed an incompatible Qt5 Breeze dependency:
`kde-style-breeze-qt5` 4:6.3.5-1 requires
`kde-style-breeze-data (= 4:6.3.5-1)`, while the preferred Qt6 Breeze
4:6.7.4-1 requires the data at its own version. The new Qt5 Breeze package
request was removed. Qt6 continues to use native Breeze; the Qt5 Breeze
compatibility configuration uses built-in Fusion with the matching complete
palette. Qt5 Adwaita and Kvantum providers remain. qBittorrent retains its
existing Fusion crash workaround and receives the Qt6ct palette directories.

### Browser downloads

`DownloadRestrictions` is now 0 in the four staged native policies for
Chromium, Chrome, Edge and Vivaldi. Value 1 was the additional dangerous
file-type restriction. Repository policy and AppArmor source inspection
found the existing Downloads directory bindings/rules already allow arbitrary
extensions, so these rules were not widened. Mullvad and Tor have no matching
repository file-type restriction. Other browser security policies remain.

Policy semantics were checked against
[Chrome administrator documentation](https://support.google.com/chrome/a/answer/7579271?hl=EN)
and [Microsoft Edge policy documentation](https://learn.microsoft.com/en-us/deployedge/microsoft-edge-browser-policies/downloadrestrictions).
No live browser download or installed policy inspection was performed.

## Optimization review corrections

Four concrete reliability and resource-boundary defects were corrected while
preserving the intended menus, theme catalog and pinned vendor asset bytes:

1. **ZIP member allocation.** The theme reader previously checked only the
   entry count claimed by the ZIP end record before constructing `ZipFile`.
   Python walks the central-directory records independently of that count.
   The reader now checks each record header, bounded filename length, record
   extent, disk identifier, actual count and complete directory extent before
   Python allocates its member objects.
2. **Decoder memory.** The expanded-byte budget did not limit an XZ stream's
   decoder dictionary allocation. Each stream now has a 128 MiB decoder
   memory limit, output is drained in bounded chunks, and concatenated XZ
   streams and four-byte padding remain supported. ZIP members accept only
   stored or Deflate data, matching the bundled inputs. The API contract was
   checked against the [Python 3.14 LZMA documentation](https://docs.python.org/3.14/library/lzma.html#lzma.LZMADecompressor).
3. **Diagnostic bytes.** Fuzzel's diagnostic classifier now runs awk with
   `LC_ALL=C`, so its 65,536-byte limit measures bytes even in a UTF-8 desktop
   session. A large multibyte warning cannot pass as a short diagnostic.
4. **Empty Digital Assets picker.** A dismissed or failed empty-state picker
   previously lost its result when `choose_file` cleared the selection and
   returned success. The function now cleans its owned candidate list and
   propagates the original result to its caller.

The additional production edits are exactly:

- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_appearance/theme_archive.py`
- `d-i/forky/hooks/target/usr/local/bin/labwc-fuzzel.tmpl`
- `d-i/forky/hooks/target/usr/local/bin/labwc-digital-assets`

Unexecuted failure cases were added in:

- `d-i/forky/tests/test_theme_installation_20261025.py`: understated ZIP
  counts, truncated central records, unaccounted directory bytes, valid
  asset bytes, XZ dictionary limits, concatenation/padding, truncation,
  expanded-byte overflow and unsupported ZIP decoders.
- `d-i/forky/tests/test_session_repairs_20260919.py`: oversized multibyte
  diagnostic warnings in a UTF-8 session.
- `d-i/forky/tests/test_fuzzel_navigation_20261025.py`: empty Digital Assets
  failure/dismissal propagation and cleanup of the owned candidate list.

The static data review also compared all 193 source pins and staging entries,
all 16 ZIP central directories (2,960 members, all Deflate), and all 10 XZ
archives, including Debian package data. The largest supplied XZ expansion
was 24,473,600 bytes and all fit the decoder memory limit. These were stdlib
archive data reads; no repository archive-reader or fixture code was run.

All 70 Kvantum INIs and 70 corresponding SVGs were parsed as data; SVGs had
no script/foreignObject elements or external href/CSS asset references. An
initial strict ConfigParser read stopped on duplicate vendor keys. The data
inspection was repeated with duplicate handling compatible with the
[Qt QSettings INI reader](https://raw.githubusercontent.com/qt/qtbase/6.10/src/corelib/io/qsettings.cpp),
which inserts each parsed key into its settings map. Vendor bytes were kept
intact. This is a format inspection, not a native Qt rendering result.

The review traced the changed menu adapters through dispatch and AppArmor,
the appearance coordinator through file/settings/greeter recovery, installer
staging through provider/default verification before service enablement,
and the read-only Qt directory binds through the validated application
package. The shared process environment change removes the retired backend
selector; the existing process lifecycle implementation was preserved.
No performance benchmark was run, so no latency or throughput gain is claimed.

## Recorded static and generation checks

- `git diff --check`: exit 0.
- Inline `python3 -I -B` stdlib-only source inspection: 39 changed/new Python
  files parsed with `ast.parse`; no repository module or fixture imported.
- The embedded target appearance check parsed as an AST, without execution.
- Four Fuzzel INI templates parsed with strict `configparser`; shared focus
  loss/cancel settings and the custom Back binding matched the declarations.
- Four native browser JSON policies parsed; unique keys and
  `DownloadRestrictions=0` confirmed. Their staging callers were inspected.
- All 193 input asset length/SHA-256 records matched. The sorted staging list
  matched the source inventory exactly, including its terminating newline.
- Profile literal checks confirmed 42 complete palettes, unique base colors,
  distinct surface states and 16 ANSI colors per profile. Arithmetic results
  are recorded above.
- Static upstream CSS/archive reference inspection covered 28 stylesheets
  and 142 missing references addressed by the explicit repair recipes, with
  zero unresolved references in that comparison. This did not execute the
  repair code, GTK CSS parser or Gio resource loader. Qt SVG href inspection
  found no external references.
- `make build`: final exit 0, `built 2041 payload files`. Earlier rebuilds were
  superseded after the dependency, archive-boundary and navigation corrections.
  One intermediate generation session handle disappeared before its exit was
  collected; the final generation was rerun and its exit 0 was observed.
- Inline stdlib archive comparison: all 2,041 regular members matched current
  source bytes and manifest hashes; archive modes 0644, uid/gid/mtime 0.
  Preseed pins matched the archive, manifest and bootstrap source hash.
- `make inventory`: final exit 0; 2,041 members, 1,975 text files and 510
  relevant source files scanned. Acquired 29 Release files and 97 package
  indexes; retained 21,426 candidates; zero acquisition errors and zero
  unresolved package requests. Earlier inventory output was superseded.
- Final JSON comparison confirmed both inventory payload identities, the
  inventory-to-APT digest, package reference bounds and repository scope.
  An auxiliary version-report script initially stopped on a dependency-only
  package; the corrected report completed with exit 0. No test runner was
  involved.

All newly authored or updated failure, rollback, identity replacement,
concurrent publication, deadline, cleanup, provider availability, dismissal
and Back fixtures remain **unexecuted**. The fingerprint for all 261 files
under `d-i/forky/tests`, excluding `__pycache__`, is:

`e7bc3897b98618ca4b29ba2ee5ac067c2c40225e4a8030bca187ab6de6e9fd6b`

The fingerprint hashes the sorted UTF-8 sequence
`SHA256(file bytes) + "  " + repository-relative path + "\n"`.

## Generated artifact identities

| Product | Bytes | SHA-256 |
| --- | ---: | --- |
| `d-i/forky/payload.tar.gz` | 61,505,368 | `1345c4b55fb7492e8f8824cb1d1c53bdd7a1d18c992ce0349c827bf67b39615d` |
| `d-i/forky/payload.manifest` | 252,246 | `5129cfa7b90fe8407dfe770cdfaf1996182f18c88ebe6a8235de745cb18d49fc` |
| `d-i/forky/preseed.cfg` | 96,407 | `311fdeaf7d9371c5f5184c7156cc14a8f68514f84e572f309bc72f0691d6b1d5` |
| `inventory-apt.json` | 19,249,386 | `c3be7310bbc904ac4696a74ec533233bff57dc2bd708ae3d39606f4f42a1ee56` |
| `inventory.json` | 2,614,477 | `c0366b4875f3081d944a809c32bae14b5523e04542bc42e2386ff6f67646aa39` |

These products match the recorded source. Hash consistency does not establish
vendor signature verification or runtime acceptance. APT metadata acquisition
uses public HTTPS and Release SHA-256 consistency; the collector does not
verify Release OpenPGP signatures or solve an installation transaction.

## Target package evidence and remaining limits

The target remains Debian Forky/systemd 262/Python 3.14. The refreshed metadata
reports these preferred amd64 request candidates; they are not installed
target observations:

| Package | Indexed preferred version |
| --- | --- |
| `python3` | 3.14.7-3 |
| `fuzzel` | 1.15.0+ds-1 |
| `qt5ct` | 1.9-2+b1 |
| `qt6ct` | 0.11-2+b2 |
| `qt-style-kvantum` | 1.1.8-1 |
| `kde-style-breeze` | 4:6.7.4-1 |
| `libgtk-4-1` | 4.24.1+ds-1 |
| `libadwaita-1-0` | 1.10.0-2 |
| `python3-gi` | 3.58.1-1 |
| `python3-tinycss2` | 1.5.1-5 |

`systemd` is a dependency rather than an explicit request in this inventory;
the candidate union includes 262-1 and 262.1-1 as well as the stable version.
GTK3 is also a dependency; the candidate union includes 3.24.52-3. The full
repository, architecture and version records are in `inventory-apt.json`.

No target image was created or inspected. Native application launches,
installed theme extraction/resource loading, GTK/Qt rendering, focus-loss
events, hotkeys, refresh, reset/rollback, browser downloads, boot and loaded
AppArmor policy remain unverified. Source and serialization checks do not
prove those behaviors. The private Xwayland implementation and its exact
Zoom/Discord eligibility boundary were preserved. No deployment, host package
change, service operation, commit or publication was performed.

## Changed paths

The 193 pinned asset additions are exactly the `files` keys in
`d-i/forky/assets/desktop-themes/sources.json`, relative to that directory.
All remaining changed, added or deleted paths at this snapshot are:

```text
d-i/forky/assets/desktop-themes/sources.json
d-i/forky/classes/class-select/role/desktop.cfg
d-i/forky/hooks/target/etc/apparmor.d/abstractions/desktop-runtime
d-i/forky/hooks/target/etc/apparmor.d/desktop-wrappers.tmpl
d-i/forky/hooks/target/etc/apparmor.d/labwc-appearance
d-i/forky/hooks/target/etc/chromium/policies/managed/security.json
d-i/forky/hooks/target/etc/opt/chrome/policies/managed/security.json
d-i/forky/hooks/target/etc/opt/edge/policies/managed/security.json
d-i/forky/hooks/target/etc/skel-desktop/.config/fuzzel/base.ini.tmpl
d-i/forky/hooks/target/etc/skel-desktop/.config/fuzzel/menu.ini.tmpl
d-i/forky/hooks/target/etc/vivaldi/policies/managed/security.json
d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu
d-i/forky/hooks/target/usr/local/bin/labwc-bluetooth.tmpl
d-i/forky/hooks/target/usr/local/bin/labwc-brightness-control.tmpl
d-i/forky/hooks/target/usr/local/bin/labwc-capture.tmpl
d-i/forky/hooks/target/usr/local/bin/labwc-computer-management
d-i/forky/hooks/target/usr/local/bin/labwc-digital-assets
d-i/forky/hooks/target/usr/local/bin/labwc-external-drives.tmpl
d-i/forky/hooks/target/usr/local/bin/labwc-firewall-menu
d-i/forky/hooks/target/usr/local/bin/labwc-fuzzel.tmpl
d-i/forky/hooks/target/usr/local/bin/labwc-fzf-menu.tmpl
d-i/forky/hooks/target/usr/local/bin/labwc-main-menu.tmpl
d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu.tmpl
d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu
d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu
d-i/forky/hooks/target/usr/local/bin/labwc-network-sharing
d-i/forky/hooks/target/usr/local/bin/labwc-podman-menu
d-i/forky/hooks/target/usr/local/bin/labwc-power-menu
d-i/forky/hooks/target/usr/local/bin/labwc-power-settings
d-i/forky/hooks/target/usr/local/bin/labwc-qbittorrent
d-i/forky/hooks/target/usr/local/bin/labwc-remote-desktop.tmpl
d-i/forky/hooks/target/usr/local/bin/labwc-users-groups-menu
d-i/forky/hooks/target/usr/local/lib/hardware_tuning/client.py
d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_appearance/catalog.py
d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_appearance/cli.py
d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_appearance/defaults.py
d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_appearance/editors.py
d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_appearance/engine.py
d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_appearance/greeter.py
d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_appearance/native.py
d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_appearance/service.py
d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_appearance/theme_archive.py
d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_appearance/theme_assets.py
d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_appearance/theme_install.py
d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_appearance/theme_repairs.py
d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_appearance/theme_resources.py
d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_appearance/themes.py
d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_appearance/transaction.py
d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/mounts.py
d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/profiles.py.tmpl
d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/managed_workflows/process.py
d-i/forky/hooks/target/usr/local/libexec/labwc-appearance-themes
d-i/forky/hooks/target/usr/local/share/agenda/schemas/90-desktop-agenda.gschema.override
d-i/forky/payload.manifest
d-i/forky/payload.tar.gz
d-i/forky/preseed.cfg
d-i/forky/scripts/desktop/components/appearance.sh
d-i/forky/scripts/desktop/components/desktop-helpers.sh
d-i/forky/scripts/desktop/components/target-assets.sh
d-i/forky/scripts/desktop/components/user-config.sh
d-i/forky/scripts/desktop/desktop-theme-assets.list
d-i/forky/scripts/desktop/labwc.sh
d-i/forky/scripts/desktop/verify.sh.tmpl
d-i/forky/scripts/firstboot/04-validation.sh.tmpl
d-i/forky/tests/test_categorized_menu.py
d-i/forky/tests/test_compz_qbittorrent_followup.py
d-i/forky/tests/test_desktop_navigation_20260918.py
d-i/forky/tests/test_fuzzel_navigation_20261025.py
d-i/forky/tests/test_gitbuild_appearance_20260928.py
d-i/forky/tests/test_icon_colors_20260923.py
d-i/forky/tests/test_kanshi_fuzzel_followup_20260919.py
d-i/forky/tests/test_menu_apparmor_integration_20260919.py
d-i/forky/tests/test_native_tuning_menu_20260919.py
d-i/forky/tests/test_network_sharing.py
d-i/forky/tests/test_security_refactor.py
d-i/forky/tests/test_session_repair_edges.py
d-i/forky/tests/test_session_repairs_20260919.py
d-i/forky/tests/test_theme_installation_20261025.py
docs/validation/desktop-appearance-navigation-20261025.md
inventory-apt.json
inventory.json
```
