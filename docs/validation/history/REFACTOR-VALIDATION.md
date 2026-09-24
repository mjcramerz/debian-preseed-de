# Waybar / Fuzzel refactor - 2026-09-24

## Delivered architecture

The archive contains the complete supplied repository with the scoped refactor, tests,
and regenerated `d-i/forky/payload.tar.gz`, payload manifest and preseed artifacts.
No upstream component was compiled or patched. Ten private Xwayland/Zoom/Discord
files retain their original SHA-256; their paths and hashes are in the evidence JSON.

- Waybar: one direct native `waybar.service`, one process, one JSON configuration
  with `internal` and `external` bar definitions, one stylesheet and five XML menus.
- All ten profiles contain 69 paired Waybar geometry keys. Shared visual rules precede
  class-qualified bar geometry; fonts, font weights and border styles are theme inputs.
- Fuzzel: only `base.ini`, `fuzzel.ini`, `menu.ini`, `computer-management.ini` are installed.
  Nested imports remove duplicated policy/palette; `dpi-aware=yes` is common policy.
- Each profile has 33 Fuzzel values for INTERNAL/EXTERNAL/DEFAULT geometry and
  launcher/menu dimensions. The wrapper supplies geometry on the native command line.
- Output precedence is explicit wrapper output, then `WAYBAR_OUTPUT_NAME`, then unknown.
  Unknown uses DEFAULT without inventing an output. Both components use
  `LABWC_OUTPUT_INTERNAL_PREFIXES`. Computer management shares menu geometry.
- Installer rendering/validation, service reload identity checks, AppArmor permissions,
  autostart, hardware-tuning integration, verifiers and regression fixtures were updated.

## Native limitations: these are exceptions to the exact requested behavior

GTK popup menus and tooltips are separate windows, not descendants of the bar window.
With one shared stylesheet and one XML asset per menu, bar-class selectors cannot give
those windows separate internal/external geometry. Their paired profile values must
therefore match, and the installer rejects divergence explicitly. Existing profiles
already use equal values. Bar geometry itself is independently configurable.

Stock Waybar's generic click dispatcher does not guarantee `WAYBAR_OUTPUT_NAME`.
The wrapper honors it when supplied, but an unannotated click cannot be promised to
select the originating output or geometry. It follows the requested unknown/DEFAULT
state rather than guessing. Explicit `labwc-fuzzel launcher --output eDP-1` is supported.

## Validation actually performed

Fresh passing groups: 56 contracts (including 16 new multi-monitor regressions),
28 workspace tests, 21 native theme tests, 9 native menu-verifier tests, one signal
lifecycle test, and 179 tooling tests. Counts describe groups, not a unique-test sum.
All ten profiles rendered; native GTK/Pango checks passed. Shell checks passed for
291 files / 593 parses; theme checks covered 1,993 inputs / 101 tokenized files;
59 preseed files passed. Generated artifacts are current and `git diff --check` passed.
Local and VM bootstrap paths passed; the final isolated HTTP bootstrap passed.
Earlier concurrent HTTP runs exceeded the fixture timeout; the final pass did not
change the test timeout or bootstrap implementation.

A broader 2,559-test run (53 skips) exposed stale fixtures, subsequently repaired and
rechecked. It was NOT rerun end-to-end after those repairs, so no all-green full-suite
claim is made. `test_opposite_role_fails_before_preflight_marker` still failed and the
same failure reproduced on the unmodified ZIP; unrelated bootstrap code was not changed.

Native systemd/AppArmor checks are parser/fixture checks, not target acceptance.
The available systemd parser was 257.9, not the requested 261.2. No real Forky boot,
Wayland monitor hotplug session, native Fuzzel display or enforced AppArmor kernel
acceptance test was performed. A flawless unattended installation is not certified.

## Evidence and repeat checks

Selected logs and machine-readable coverage are in `validation/native-monitor-20260924/`.
Run `python3 -B tools/build.py --check` for generated-product consistency.
Run `PYTHONPATH=d-i/forky/tests python3 -B -m unittest -v test_native_multimonitor_20260924`
for the new layout, profile, output-precedence and argument-safety regressions.
