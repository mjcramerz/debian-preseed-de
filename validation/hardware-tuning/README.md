# Hardware tuning validation - 2026-09-16

## Result

The new hardware-tuning suite passes **74/74 tests**, with no skips. The final full repository suite completed **1254 tests: 1219 passed, 27 skipped, 6 failures and 2 errors**. All eight remaining failing/error cases also reproduce against the untouched supplied archive with the same interpreter and environment. This is NOT an all-green full repository run. No failing test was skipped, removed or silently converted to a success.

The existing failures are two absent historical raw AppArmor incident files, four Perl checks blocked by the build container's missing Moo dependency, an existing app-scope drop-in expectation that excludes the already-present resource-class file, and an existing Podman-menu subprocess mock mismatch. See `repository/original-failures.log`, `repository/original-failure-comparison.json`, and the complete tracebacks in `repository/final-tests.log`.

The initial full run in `repository/tests.log` found two additional integration assertions. The tuning module fetch position was adjusted without changing the explicit source order. The historical resource-policy guard now strips exactly the one new, count-checked `desktop_install_hardware_tuning` call, in addition to its two previously approved calls; the historical hash fixture remains unchanged. Both assertions pass in `repository/integration-recheck.log` and in the final full run. The initial aggregate validator's outer execution limit interrupted its wrapper; its test child completed. The final full run was separately supervised to completion and its actual status is recorded in `repository/final-tests-status.json`.

## Passed offline checks

- Hardware tuning: 74 fixture, lifecycle, validation, fault-injection and real Unix-peer-credential/pidfd tests (`unit-tests.log`). No build-host hardware was changed.
- Generated units: six systemd parser/dependency checks, system/user scopes for Intel-only, NVIDIA-only and combined installs. The checker is systemd 257 (257.9-1~deb13u1). Executable lines and session/AppArmor dependencies are explicitly replaced only in temporary fixtures; target units are not started.
- AppArmor: three vendor-selection combinations compiled with `-Q -K`, including the two existing desktop parent domains. The host parser notes an unavailable kernel cache interface; these are no-kernel-load checks, not enforcement acceptance.
- Browser artifact consistency, payload/manifest/preseed consistency and preseed checks: pass.
- Shell syntax: 279 files, 569 parser checks, no failures.
- Full source audit: 456 syntax passes and 173 lexical systemd structure passes. Separately: 156 dependency-blocked, 495 inventory-only and 2 templates needing rendering. These categories are not combined into a fabricated pass count.

## Reproduce

From a trusted checkout:

```sh
python3 -B -m unittest discover -v -s d-i/forky/tests -p 'test_hardware_tuning_20260916.py'
sudo python3 -B tools/check_hardware_tuning.py
python3 -B tools/build.py --check
python3 -B tools/check_preseeds.py
python3 -B tools/check_shells.py --output validation/hardware-tuning/repository/shell-check.json
python3 -B -m unittest discover -v -s d-i/forky/tests -p 'test_*.py'
python3 -B d-i/forky/tests/audit_codebase.py --output validation/hardware-tuning/repository/audit.json
```

The existing aggregate `tools/validate.py` retains its original per-stage timeouts; the full suite can exceed its 300-second test-stage budget on a slow build host. The direct full-suite command above does not add that wrapper limit. No unrelated validation timeout or pre-existing test was relaxed for this implementation.

## Acceptance boundary

Actual Flex/P15s firmware and write permissions, target systemd 261.2, AppArmor enforcement, Waybar/Fuzzel interaction, multi-window lifecycle behavior, suspend/resume, thermal behavior and stability must be checked on the installed hosts. Use `docs/hardware-tuning/ACCEPTANCE.md`; its checks are intentionally not marked complete by this offline validation.
