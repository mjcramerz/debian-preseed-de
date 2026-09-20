# Packaged labwc/KWallet and native thumbnail switching

Date: 20 September 2026

## Scope and result

This revision removes the installer-time labwc and KWallet source builds from
`debian-preseed-de(4).zip`. Both applications continue to come from the existing
Debian binary package selection: `labwc` and `kwallet6`. No replacement compiler,
patcher, source repository, local binary, package hold or error-ignore fallback
has been introduced.

The installer no longer calls the step labelled **build native Labwc thumbnail
and KWallet repairs from authenticated Debian source**. That step and both of
its implementation files are deleted. It is not conditional, deferred to first
boot or suppressed with `|| true`. Consequently, new installations cannot fail
inside that removed source-build step. The supplied complaint identifies that
step, but does not include its compiler/build traceback; this report does not
invent a more specific compiler or dependency diagnosis.

This is an installation/configuration repair, not a claim to have fixed every
upstream compositor, Qt, driver or hardware defect. Unrelated workload policy,
KWallet storage, AppArmor rules, output coordination, desktop application
launchers and systemd services are retained.

## Source-build removal

Removed from `d-i/forky/scripts/desktop/labwc.sh`:

* `desktop_install_native_session_repairs()` and its call in the desktop late
  command.
* Creation/staging of `/root/.installer-native-session-repairs`.
* The Python source-builder invocation and its staging cleanup.

Deleted from `d-i/forky/hooks/target/usr/local/share/labwc/native-repairs/`:

* `build_native.py`.
* `patch_sources.py`.

The generated payload archive and manifest are rebuilt without those files,
and the generated preseed contains the corresponding new integrity hashes.
The build tool used for this regeneration, `tools/build.py`, creates the
installer's tar archive and preseed: it does **not** compile labwc or KWallet.

The source-package dependency installation, temporary build user, custom
`+managed20260919.2` package versions, locally generated packages and repair
receipt are no longer part of the installation path. The ordinary development
tools already selected by the desktop role remain selected; removing the
user's development environment would be an unrelated change.

## Native thumbnails, not a window list

The compositor's configuration retains the native `windowSwitcher` OSD with
`show="yes"` and `style="thumbnail"`. Default preview, outline and unshade settings
remain enabled. Application icons, thumbnail labels, emerald selection tint,
thumbnail sizing, current-workspace filtering and output selection are retained.

The two keyboard shortcuts remain native compositor actions:

```xml
<keybind key="A-Tab">
  <action name="NextWindow" workspace="current" output="all" identifier="all" />
</keybind>
<keybind key="A-S-Tab">
  <action name="PreviousWindow" workspace="current" output="all" identifier="all" />
</keybind>
```

The Waybar button keeps its existing session-bound transient service. Its
one-shot launcher sends F13 through `/usr/bin/wtype`; F13 invokes native
`NextWindow`. It does not launch Fuzzel, a `ShowMenu` window list, an external
thumbnail application, a polling daemon or a held-modifier process.

`LABWC_WINDOW_SWITCHER_STYLE` accepts only `thumbnail`, defaulting to that value
when unset/empty as before. The full policy validator and the independent XML
renderer both reject `classic` or malformed values. The renderer rejects these
values before overwriting an existing configuration. The installed-configuration
verifier rejects classic OSD mode and classic list fields in either the skeleton
or account configuration. The now-unused list fields and classic theme entries
are removed.

Stock compositor behavior replaces the old private C patches. In particular,
this release does not promise the deleted patch's active-window-first selection,
F13-as-cancel, Enter-to-accept, wheel handling or outside-click semantics. The
packaged compositor owns those behaviors. Alt+Tab and Shift+Alt+Tab use its normal
modifier lifecycle; the documented arrow-key and Escape handling is native.
No source patch is needed to enable thumbnail rendering itself.

## KWallet and isolation

`kwallet6` remains in the Debian package selection, with `qt6-wayland` and the
existing session environment. `labwc-kwallet-portal.service` still launches the
packaged `/usr/bin/ksecretd`, uses the Secret Service D-Bus name, and remains
bound to the compositor/session with control-group termination. No KWallet
contents are deleted, no password is cleared and no empty-password wallet is
created. The former private QWizard/GPG/Wayland-parenting patches are removed,
not reimplemented as insecure configuration workarounds.

The compositor still launches `/usr/bin/labwc`. The existing private
Zoom/Discord compatibility boundary is unchanged: public Xwayland is removed
by the existing installer, inherited X11/Xwayland selectors are cleared for
the compositor, and `/opt/xwayland` is hidden in its service mount namespace.
The Debian compositor is **not** claimed to be compiled without Xwayland;
that compile-time change belonged to the deleted patcher.

The AppArmor profiles and systemd service/drop-in files are byte-for-byte
unchanged from the supplied archive. The output-authority, batching, no-op
modeset and Kanshi pause/resume tests from the preceding revision are retained.
There is no service-disable or confinement-relaxation workaround in this change.

## Regression and publication checks

The new `test_packaged_native_session_20260920.py` checks binary package
selection, absence of source helpers in the active tree and published payload,
stock executable paths, retained service isolation, the real shell late-command
control flow under dash and BusyBox, failure propagation, and refusal to render
classic/injected switcher settings over an existing configuration.

Existing workspace tests exercise all 12 supported workspace counts, native
Alt+Tab/Shift+Alt+Tab/F13 actions, both monitor-panel configurations, installed
configuration rejection and broker retirement. The old tests for the deleted
source builder and C patch fragments were retired with their implementations;
output-authority and theme tests remain. The workload-policy preservation test
now compares against the original native-build-free source without the former
exception for inserting the build hook.

Current evidence is in `validation/packaged-native-session-20260920/`.
`summary.json` records the full validation stages, actual test counts, skipped
tests, audit categories and generated product hashes. Separate scope and
packaging evidence documents precisely which files changed and verifies the
published tar archive. Historical validation directories describe older
revisions and must not be treated as new execution results.

Validation does not boot an unattended installation or create a real Wayland
session. This execution environment has no labwc display/GPU session; its package
network DNS is unavailable. Dependency-gated skipped checks are recorded rather
than silently replaced with fake success. Live thumbnail interaction, wallet
creation/unlock, AppArmor enforcement under the target kernel, driver behavior
and a complete installation remain on-host acceptance checks.

### Executed results for this release

All seven validation stages completed with exit status zero. The repository
suite ran 1,802 tests with 37 explicit skips; the tooling suite ran
179 tests with 0 skips. Neither suite reported failures or errors.
The focused output/theme, workspace, package-only and resource-policy runs
completed 61 tests with no skips. Those focused runs overlap the full suite;
they are not additional distinct coverage.

The shell checker passed 581 parser checks over 285 shell files. The publication
check verified all 1,377 payload members against both source bytes and manifest
hashes, checked the preseed pins, and confirmed byte-identical regeneration.
The scope audit found 17 modified originals, two deleted source helpers and two
new source/documentation files; 3,076 original files remain byte-identical.
All retained original file and directory permissions are preserved. All 79
AppArmor files and 190 systemd-path files are unchanged.

The static audit reports 156 dependency-blocked checks and
11 tool-blocked checks, separately from successful checks. Its
inventory-only, structure-only and unrendered-template categories are not live
runtime validation. `skipped-tests.json` lists every skipped test and its actual
reason, including missing tools/dependencies, absent original audit logs and an
unavailable noexec test condition. These are limitations, not passing tests.

Reproduce the main validation in a suitably provisioned Linux environment:

```sh
python3 -B tools/validate.py \
  --output-dir validation/local-packaged-native-session \
  --test-timeout 1800
```

## Deployment

Publish the **complete** new `debian-preseed-de/` directory as one release. Do not
mix an old `preseed.cfg`, `payload.manifest` or `payload.tar.gz` with this tree.
Extract into a new directory and atomically switch the served release; do not
overlay individual files over a previously served snapshot. Verify the supplied
SHA-256 checksum before publishing and keep the existing site-specific/private
credential handling outside the served tree.

The archive repairs the code served to future installations. It is not an
in-place package downgrade/repair script for an already partially installed
machine. A system on which the old builder already installed custom packages
requires inspection of its package versions and the old repair receipt before
restoring distribution packages. Existing user wallets must be backed up and
preserved; no blanket purge, autoremove or wallet deletion is authorized here.

On a disposable target, the remaining acceptance checks are: complete d-i
through first login without any native source-build step; verify Debian-managed
labwc/KWallet versions; exercise native thumbnail switching from both keyboard
and Waybar; verify wallet unlock/Secret Service; and confirm session shutdown,
AppArmor enforcement and the private Xwayland boundary. These checks are not
represented as performed by the offline regression suite.

## Primary references checked for this change

* [Debian forky labwc package](https://packages.debian.org/forky/labwc)
  (the retrieved listing reports 0.20.2-1).
* [Debian forky kwallet6 package](https://packages.debian.org/forky/kwallet6).
* [Debian kwallet6 file list](https://packages.debian.org/forky/amd64/kwallet6/filelist)
  confirms `/usr/bin/ksecretd`.
* [labwc configuration manual](https://labwc.github.io/labwc-config.5.html),
  `windowSwitcher/osd`: `thumbnail` is a grid of window previews, icons and titles;
  `classic` is the vertical information list.
* [labwc action manual](https://labwc.github.io/labwc-actions.5.html),
  `NextWindow`/`PreviousWindow`.
* [labwc theme manual](https://labwc.github.io/labwc-theme.5.html),
  `osd.window-switcher.style-thumbnail.*`.
* [labwc 0.20.2 cycling implementation](https://raw.githubusercontent.com/labwc/labwc/0.20.2/src/cycle/cycle.c)
  and [keyboard handling](https://raw.githubusercontent.com/labwc/labwc/0.20.2/src/input/keyboard.c).

Package listings are a point-in-time reference, not a new version pin or a
promise about the contents of a future testing-suite mirror.
