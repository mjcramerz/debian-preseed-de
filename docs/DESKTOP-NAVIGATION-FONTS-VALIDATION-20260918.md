# Desktop navigation and fonts: validation ledger

Execution date: 18 September 2026. Baseline: the previously delivered complete
`debian-preseed-de-refactored.tar.gz`, SHA-256
`95597d727adfe818daee0e64fa72ad153f9bf944f1e36b90a9ba9ca1e5db1394`.
This follow-up retains the previous root reconciliation, GIO/XDG application
menus, user-launcher responsibilities and isolated Waypaper implementation.

## Environment and acceptance boundary

Execution host: Debian 13, Python 3.13.5, systemd-analyze 257.9, AppArmor parser
4.1.0 and Fontconfig 2.15.0. The deployment target remains Debian Forky and
systemd 261.2. No real target Wayland/Labwc session or enforcing target AppArmor
kernel was available. The host lacks fzf, wtype, shellcheck, desktop-file-validate
and the Python GI binding. Existing GIO tests use the real installed libgio via
the repository's test-only C ABI fixture, not a claim that GI was installed.

All **72 module patterns** were attempted. Final module results: **65 PASS,
5 FAIL, 1 incomplete timeout, and 1 zero-test support module**. Completed modules
report **1,745 tests: 1,706 passed, 31 skipped and 8 failure/error outcomes**.
These totals use the final reruns below, do not double-count repeated commands,
and exclude partially completed timed-out tests.

The new navigation suite has **35 passes and 1 dependency skip**. The new font
suite has **28 passes**, including real unprivileged publication and Fontconfig
font discovery using a temporary copy of a font already installed on the host.
All temporary font data stays outside the project and is removed by fixtures.
No released font binaries are included in the source archive.

The five final failing modules were also run against a clean extraction of the
prior delivered baseline; all eight corresponding failures/errors reproduced.
They are not hidden or removed. The original validation ledger remains available
for the preceding change; its dated results are not replaced by this follow-up.

## Every test-module command

Commands ran from the project root, individually with a 45-second process-group
limit in the full-suite driver. PASS can include explicitly counted skips.
Latest targeted reruns supersede initial results only where described below.

| Command | Final result | Tests | Skips |
|---|---|---:|---:|
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_boot_runtime_20260913.py` | PASS | 31 | 23 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_boot_runtime_second_pass.py` | PASS | 6 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_bootstrap_portability.py` | PASS | 18 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_btrfs_locale_boundary.py` | PASS | 19 | 1 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_categorized_menu.py` | PASS | 40 | 2 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_codex_clone_staging.py` | PASS | 33 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_codex_installer_session.py` | PASS | 22 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_codex_standalone_chroot.py` | PASS | 3 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_computer_management_20260916.py` | PASS | 33 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_config_safety.py` | PASS | 19 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_cuda_legacy_apt.py` | PASS | 40 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_dbus_broker.py` | PASS | 16 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_debconf_protocol.py` | SKIPPED completion: 45-second timeout | incomplete | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_desktop_fonts_20260918.py` | PASS | 28 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_desktop_integration_20260914.py` | PASS | 28 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_desktop_navigation_20260918.py` | PASS | 36 | 1 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_desktop_sandbox.py` | FAIL | 70 | 1 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_environment.py` | SKIPPED: support module, no tests | 0 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_gitops_mirrors.py` | PASS | 16 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_gpg_recipient_integration.py` | PASS | 29 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_hardware_restore.py` | PASS | 25 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_hardware_tuning_20260916.py` | PASS | 74 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_hardware_tuning_followup_20260917.py` | PASS | 5 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_hardware_tuning_handover_20260917.py` | PASS | 52 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_hardware_tuning_refactor_20260917.py` | PASS | 37 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_initrd_credentials.py` | PASS | 24 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_initrd_target_tools.py` | PASS | 11 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_installation_fixes_20260912.py` | PASS | 34 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_installed_failures_20260911.py` | FAIL | 21 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_installer_hardening.py` | PASS | 56 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_lifecycle.py` | PASS | 22 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_lifecycle_review_20260914.py` | PASS | 30 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_log_followup_20260915.py` | PASS | 9 | 1 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_log_launchers_20260915_r3.py` | PASS | 29 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_log_regressions_20260915.py` | FAIL | 23 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_managed_external_software.py` | FAIL | 6 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_managed_git_debugsys.py` | PASS | 56 | 1 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_management_perl_methods_20260916.py` | PASS | 11 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_nvidia_580_recovery.py` | PASS | 10 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_nvidia_72_interfaces.py` | PASS | 19 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_nvidia_legacy_dkms.py` | PASS | 14 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_nvidia_power.py` | PASS | 13 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_package_power_guard.py` | PASS | 38 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_podman_incus_redesign.py` | FAIL | 88 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_policy_review_20260916.py` | PASS | 15 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_power_io_policy_r6.py` | PASS | 14 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_power_keyboard_20260913.py` | PASS | 36 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_power_quiescence_20260916.py` | PASS | 16 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_process_capture.py` | PASS | 10 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_repository_integrity.py` | PASS | 10 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_repository_transport.py` | PASS | 27 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_resctl_bench_20260916.py` | PASS | 28 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_resctl_bench_docs_20260917.py` | PASS | 5 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_resctl_bench_noexec_20260917.py` | PASS | 12 | 1 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_resctl_bench_release_20260917.py` | PASS | 23 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_retained_package_bounds.py` | PASS | 26 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_root_login.py` | PASS | 32 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_security_refactor.py` | PASS | 28 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_shutdown_policy_r5.py` | PASS | 8 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_system_desktop_overrides.py` | PASS | 30 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_systemd_resource_policy.py` | PASS | 16 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_systemd_resource_refinements.py` | PASS | 9 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_workspace_no_broker.py` | PASS | 27 | 0 |
| `python3 -B -m unittest discover -v -s tools/tests -p test_apt_vendor_normalization.py` | PASS | 13 | 0 |
| `python3 -B -m unittest discover -v -s tools/tests -p test_installed_session_failures_20260913.py` | PASS | 23 | 0 |
| `python3 -B -m unittest discover -v -s tools/tests -p test_labwc_power_handoff.py` | PASS | 24 | 0 |
| `python3 -B -m unittest discover -v -s tools/tests -p test_local_apt_integration.py` | PASS | 1 | 0 |
| `python3 -B -m unittest discover -v -s tools/tests -p test_local_apt_refresh.py` | PASS | 37 | 0 |
| `python3 -B -m unittest discover -v -s tools/tests -p test_local_apt_repository.py` | PASS | 15 | 0 |
| `python3 -B -m unittest discover -v -s tools/tests -p test_persisted_package_policy.py` | PASS | 12 | 0 |
| `python3 -B -m unittest discover -v -s tools/tests -p test_scoped_desktop_fixes.py` | PASS | 11 | 0 |
| `python3 -B -m unittest discover -v -s tools/tests -p test_scoped_lifecycle_keyrings.py` | PASS | 43 | 0 |

## Reruns and deliberately updated expectations

The following commands were additionally rerun directly after inspection or
fixture correction. Their exact commands are identical to the corresponding
rows above.

- `test_codex_clone_staging.py`: PASS, 33 tests on a direct foreground rerun.
  The initial signal-sensitive test failed in the asynchronously launched driver;
  neither its production code nor its assertions were changed.
- `test_desktop_sandbox.py`: the new Symbols Nerd Font fallback is now part of
  the exact expected font string. Final result remains FAIL solely for the absent
  historical AppArmor incident fixture (one failure; one dependency skip).
- `test_resctl_bench_20260916.py`: PASS, 28 tests; the exact fetch-module list now
  includes the requested fonts module without changing resctl-bench requirements.
- `test_workspace_no_broker.py`: PASS, 27 tests. The existing negative Alt+Tab test
  now modifies that exact XML binding, not the first arbitrary workspace token
  (which is now F13). Two new negative tests reject global-workspace F13 and a
  missing window-switcher button. A first added-test run expected a different
  diagnostic spelling; only the expected diagnostic was corrected.
- `test_installed_session_failures_20260913.py`: PASS, 23 tests; every panel click
  is still checked for the full session-isolation contract. The expected count
  changes from 56 to 58 for the two new bar buttons.
- `test_desktop_fonts_20260918.py`: PASS, 28 tests in the final rerun, including
  no-follow descriptor-based parent ownership and symlink-target preservation.
- `test_desktop_navigation_20260918.py`: PASS, 36 tests with one missing-fzf skip.

Additional focused runs of `test_categorized_menu.py`,
`test_desktop_integration_20260914.py`, and `test_computer_management_20260916.py`
were executed during implementation and then again in the module sweep. Initial
UI-fixture mismatches were corrected only to reflect this requested redesign.
The original child-action handlers, privilege confirmations and workload policy
checks remain; no historical failure is bypassed to obtain a green result.

Other intentional fixture changes: icon-prefixed top-level choices are validated
exactly; Computer Management's old graphical sizing-retry expectation is replaced
by the terminal exact-choice contract; its action-completion test now drives the
Python controller and the actual maintenance child. The resource-policy byte
guard normalizes only the exact new `desktop_install_fonts` call.

## Baseline failures

Each command below was executed from a separate clean copy of the preceding
archive, with no source modifications. All returned the same final failure count.

| Baseline command | Result and reason |
|---|---|
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_desktop_sandbox.py` | FAIL: one missing historical `todo/managed/apparmor/apparmor.log` assertion; one unrelated skip. |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_installed_failures_20260911.py` | FAIL: one error reading that same missing historical log. |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_log_regressions_20260915.py` | FAIL: one historical single-drop-in assertion; baseline already has the later resource drop-in. |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_managed_external_software.py` | FAIL: four Perl-backed checks lack the host's Moo dependency. |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_podman_incus_redesign.py` | FAIL: one pre-existing subprocess mock/communicate incompatibility. |

`test_debconf_protocol.py` did not finish within its 45-second limit. The prior
archive's ledger also records an incomplete baseline run; it is not reported as
passed here. `test_environment.py` is a support module with zero test cases,
not a passing test suite or a production failure.

## Static, integration and packaging checks actually executed

`$AUDIT` denotes an external temporary validation directory, never part of the
project payload. External harnesses only relocate paths/transports for validation.

| Command/check | Result |
|---|---|
| `python3 -B tools/build.py` | PASS, including the final rebuild: 1,369 installer payload files. |
| `python3 -B tools/build.py --check` | PASS: payload, pins and preseed current. |
| `python3 -B tools/build_browser_config.py --check` | PASS: browser artifacts current. |
| `python3 -B tools/check_shells.py --output "$AUDIT/shell-check-final.json"` | PASS: 281 shell files, 573 parser checks. This is not ShellCheck. |
| `python3 -B tools/check_preseeds.py` | PASS: 59 preseed files, four real debconf command-value readbacks. |
| `python3 -B d-i/forky/tests/audit_codebase.py --output "$AUDIT/audit.json"` | PASS for audit execution; dependency-blocked and inventory-only entries remain explicitly classified, not claimed as runtime successes. |
| `python3 "$AUDIT/render_profiles.py"` | PASS: all 13 real profiles rendered through the production renderer; both bars, native XML, F13/Alt+Tab, menu order, resolved tokens and font config syntax checked. |
| `apparmor_parser -Q -K -T --base "$AUDIT/apparmor" -I "$AUDIT/apparmor" "$AUDIT/apparmor/managed-desktop-wrappers"` | PASS, including final compilation against staged project abstractions; no kernel loading/enforcement. |
| `systemd-analyze --root="$AUDIT/systemd-root" verify labwc-system-desktop-overrides.service labwc-system-desktop-overrides.path` | PASS with systemd 257.9 and offline target fixtures; not live 261.2 execution. |
| `systemctl --root="$AUDIT/systemd-root" enable labwc-system-desktop-overrides.path labwc-system-desktop-overrides.service` | PASS: real offline enablement links created. |
| `git diff --check` | PASS: no patch whitespace errors. |
| Source/cache/font-file audit | PASS: no font binaries, Python caches, editor files, extracted dependencies or temporary test artifacts in the deliverable tree. |

Python compilation was also executed successfully, with bytecode directed outside
the source tree:

```sh
PYTHONPYCACHEPREFIX="$AUDIT/compile-cache" /usr/bin/python3 -m py_compile \
  d-i/forky/hooks/target/usr/local/bin/labwc-computer-management \
  d-i/forky/hooks/target/usr/local/bin/labwc-fzf-menu \
  d-i/forky/hooks/target/usr/local/bin/labwc-main-menu \
  d-i/forky/hooks/target/usr/local/bin/labwc-podman-menu \
  d-i/forky/hooks/target/usr/local/bin/labwc-remote-desktop \
  d-i/forky/scripts/desktop/fonts-install.py \
  d-i/forky/tests/test_categorized_menu.py \
  d-i/forky/tests/test_desktop_fonts_20260918.py \
  d-i/forky/tests/test_desktop_integration_20260914.py \
  d-i/forky/tests/test_desktop_navigation_20260918.py \
  d-i/forky/tests/test_desktop_sandbox.py \
  d-i/forky/tests/test_resctl_bench_20260916.py \
  d-i/forky/tests/test_systemd_resource_policy.py \
  d-i/forky/tests/test_workspace_no_broker.py \
  tools/tests/test_installed_session_failures_20260913.py
```

## Explicitly unexecuted runtime acceptance

- **SKIPPED:** ShellCheck and desktop-file-validate, because their host binaries
  are absent. Syntax/unit validation is not represented as those tools running.
- **SKIPPED:** a real fzf terminal-selection session, wtype key injection and
  real Labwc/Waybar/Fuzzel GUI behavior; no matching binaries/session here.
- **SKIPPED:** target systemd 261.2 lifecycle, AppArmor kernel enforcement and
  real Waypaper wallpaper persistence through logout/reboot.
- **SKIPPED:** download/extraction of the five actual release archives in this
  environment. Runtime download attempts could not obtain the bytes. Public
  GitHub release metadata was read and all five published SHA-256 values match
  the user's pins; that is not independent hashing of downloaded archives.
  The installer performs real byte verification before extraction on the target,
  fails closed on mismatch, and never executes archive contents.

Native right-click cancellation is intentionally **not implemented**: reviewed
Forky Labwc 0.20.2-1 sources route cycle-item pointer release to selection and
bypass ordinary mouse bindings while cycling. Escape invokes cancellation without
switching focus. F13 uses normal key-press binding; both Alt+Tab directions remain
unchanged. No compositor fork, global input interception or modified Alt behavior
was introduced to simulate unsupported right-click semantics.
