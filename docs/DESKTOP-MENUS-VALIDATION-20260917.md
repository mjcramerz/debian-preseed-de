# Desktop menus and system overrides: validation ledger

Execution date: 17 September 2026. This is the record for this change, not the dated historical incident reports.

## Environment and result boundary

The execution host was Debian 13 (trixie), Python 3.13.5, libgio 2.84.4, systemd-analyze 257.9 and AppArmor parser 4.1.0. The requested target is Debian Forky with systemd 261.2. There was no real target graphical session or usable target systemd/AppArmor enforcement environment.

All 70 test-module patterns were attempted separately: **61 PASS modules, 5 FAIL modules, 3 timed-out modules, and 1 zero-test support module**. Completed modules report **1647 tests: 1609 passed, 30 skipped, and 8 failure/error outcomes**. Partially executed timed-out modules are excluded from those test totals. All five failing modules and all three timeouts were reproduced against the unmodified uploaded archive.

The new focused suites report **30/30 root reconciler tests passed; 38/40 menu tests passed, 2 skipped**. Root filesystem, flock, atomic replacement and recovery operations are real; package ownership/classification, desktop validator and MIME subprocesses are isolated spies in these tests. Menu semantic probes call the real libgio through a test-only C ABI adapter as an actual non-root user. That is not a claim that the unavailable PyGObject binding or live AppArmor enforcement was exercised.

## Every test module command

Commands below ran from the project root. Each module had a 45-second process-group limit in the execution driver. PASS may include the explicitly counted skips. FAIL means actual assertion/error outcomes, not that the whole module was skipped. The latest successful targeted rerun replaces an earlier result where stated below.

| Command | Result | Tests | Skips |
|---|---|---:|---:|
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_boot_runtime_20260913.py` | PASS | 31 | 23 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_boot_runtime_second_pass.py` | PASS | 6 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_bootstrap_portability.py` | SKIPPED: incomplete after 45-second timeout | incomplete | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_btrfs_locale_boundary.py` | PASS | 19 | 1 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_categorized_menu.py` | PASS | 40 | 2 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_codex_clone_staging.py` | PASS | 33 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_codex_installer_session.py` | PASS | 22 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_codex_standalone_chroot.py` | PASS | 3 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_computer_management_20260916.py` | PASS | 33 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_config_safety.py` | PASS | 19 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_cuda_legacy_apt.py` | PASS | 40 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_dbus_broker.py` | PASS | 16 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_debconf_protocol.py` | SKIPPED: incomplete after 45-second timeout | incomplete | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_desktop_integration_20260914.py` | PASS | 28 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_desktop_sandbox.py` | FAIL (also reproduced on original) | 70 | 1 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_environment.py` | SKIPPED: support module, no test cases | 0 | 0 |
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
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_installed_failures_20260911.py` | FAIL (also reproduced on original) | 21 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_installer_hardening.py` | PASS | 56 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_lifecycle.py` | PASS | 22 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_lifecycle_review_20260914.py` | PASS | 30 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_log_followup_20260915.py` | PASS | 9 | 1 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_log_launchers_20260915_r3.py` | PASS | 29 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_log_regressions_20260915.py` | FAIL (also reproduced on original) | 23 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_managed_external_software.py` | FAIL (also reproduced on original) | 6 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_managed_git_debugsys.py` | PASS | 56 | 1 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_management_perl_methods_20260916.py` | PASS | 11 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_nvidia_580_recovery.py` | PASS | 10 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_nvidia_72_interfaces.py` | PASS | 19 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_nvidia_legacy_dkms.py` | PASS | 14 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_nvidia_power.py` | PASS | 13 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_package_power_guard.py` | PASS | 38 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_podman_incus_redesign.py` | FAIL (also reproduced on original) | 88 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_policy_review_20260916.py` | PASS | 15 | 0 |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_power_io_policy_r6.py` | SKIPPED: incomplete after 45-second timeout | incomplete | 0 |
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
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_workspace_no_broker.py` | PASS | 25 | 0 |
| `python3 -B -m unittest discover -v -s tools/tests -p test_apt_vendor_normalization.py` | PASS | 13 | 0 |
| `python3 -B -m unittest discover -v -s tools/tests -p test_installed_session_failures_20260913.py` | PASS | 23 | 0 |
| `python3 -B -m unittest discover -v -s tools/tests -p test_labwc_power_handoff.py` | PASS | 24 | 0 |
| `python3 -B -m unittest discover -v -s tools/tests -p test_local_apt_integration.py` | PASS | 1 | 0 |
| `python3 -B -m unittest discover -v -s tools/tests -p test_local_apt_refresh.py` | PASS | 37 | 0 |
| `python3 -B -m unittest discover -v -s tools/tests -p test_local_apt_repository.py` | PASS | 15 | 0 |
| `python3 -B -m unittest discover -v -s tools/tests -p test_persisted_package_policy.py` | PASS | 12 | 0 |
| `python3 -B -m unittest discover -v -s tools/tests -p test_scoped_desktop_fixes.py` | PASS | 11 | 0 |
| `python3 -B -m unittest discover -v -s tools/tests -p test_scoped_lifecycle_keyrings.py` | PASS | 43 | 0 |

## Baseline comparison and intentionally updated expectations

The following commands were also executed from a clean extraction of the original uploaded ZIP. They reproduced the final non-passing module results:

| Original-tree command | Result and cause |
|---|---|
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_bootstrap_portability.py` | SKIPPED: incomplete after the same 45-second timeout. |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_debconf_protocol.py` | SKIPPED: incomplete after the same 45-second timeout. |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_power_io_policy_r6.py` | SKIPPED: incomplete after the same 45-second timeout. |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_desktop_sandbox.py` | FAIL: one assertion depends on the absent historical `todo/managed/apparmor/apparmor.log` fixture (70 tests; one additional skip). |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_installed_failures_20260911.py` | FAIL: one error reads that same absent historical AppArmor log fixture (21 tests). |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_log_regressions_20260915.py` | FAIL: one historical assertion assumes only one app-scope drop-in; the original already contains the later resource-class drop-in (23 tests). |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_managed_external_software.py` | FAIL: four Perl-backed tests cannot load missing Moo dependencies on this host (6 tests). |
| `python3 -B -m unittest discover -v -s d-i/forky/tests -p test_podman_incus_redesign.py` | FAIL: one pre-existing subprocess mock/communicate mismatch (88 tests). |

No unrelated historical failures were removed or weakened. Three existing test files were adapted only for requested behavior: the valid desktop fixture now has mandatory `Type=Application` and calls `main([])`; the workload-byte guard normalizes only the exact requested menu assignment and GIO binding check before retaining its historical hashes; ownership tests relocate new state paths into their fixture and isolate the new external validator.

The first broad per-module pass exposed integration/provenance failures in repository integrity, resctl release pins/current hashes, the resctl staging adjacency guard, the historical workload guard, and the old scoped ownership fixture. Those were corrected narrowly and rerun. Final targeted reruns executed the same listed module commands: repository integrity 10 PASS, resctl release 23 PASS, resctl integration 28 PASS, workload guard 16 PASS, scoped ownership 11 PASS, installation fixes 34 PASS, root reconciler 30 PASS, and categorized menu 38 PASS / 2 SKIPPED.

Two monolithic discovery attempts also ran: `python3 -B -m unittest discover -s d-i/forky/tests -p 'test_*.py'` against the original, and `timeout 65s python3 -B -m unittest discover -v -s d-i/forky/tests -p 'test_*.py'` against the modified tree. Both were incomplete/time-limited. Neither is reported as a passing full-suite run; the per-module matrix above supersedes them for bounded coverage.

## Static, build and installation validation commands

Project-relative paths below identify the exact checked files. `AUDIT` denotes the temporary external validation directory used during execution; it was not inside the delivered tree. Commands displaying that variable have the original temporary directory replaced by the symbolic name only.

| Command or executed check | Result |
|---|---|
| `python3 -B tools/build.py` | PASS: installer payload rebuilt, 1,364 files; 13 valid release-pin profiles; browser artifacts unchanged. |
| `python3 -B tools/build.py --check` | PASS, including final rerun: payload, pins and preseed current. |
| `python3 -B tools/build_browser_config.py --check` | PASS. |
| `python3 -B tools/check_shells.py --output "$AUDIT/shell-check.json"` | PASS: 280 shell files, 571 parser checks using dash, BusyBox ash and bash. This is not ShellCheck. |
| `python3 -B tools/check_preseeds.py` | PASS: 59 files; all four generated preseed commands passed private real debconf readback. |
| `python3 -B d-i/forky/tests/audit_codebase.py --output "$AUDIT/audit.json"` | PASS for audit execution: 1,292 inventoried files, 462 syntax-pass, 177 unit-structure-pass, 156 dependency-blocked, 495 inventory-only and 2 templates requiring rendering. Not a claim of 1,292 runtime passes. |
| `apparmor_parser -Q -K -T --base "$AUDIT/apparmor" -I "$AUDIT/apparmor" "$AUDIT/apparmor/managed-desktop-wrappers"` | PASS: complete modified policy compiled against staged host/project includes without loading into the kernel. Cache-interface warning was expected. |
| `systemd-analyze --root="$AUDIT/systemd-root" verify labwc-system-desktop-overrides.service labwc-system-desktop-overrides.path` | PASS: offline staged root, host systemd 257.9 checker. |
| `systemctl --root="$AUDIT/systemd-root" enable labwc-system-desktop-overrides.path labwc-system-desktop-overrides.service` | PASS: both actual multi-user.target.wants symlinks created offline. No service was started. |
| Python ElementTree parsing of `menu.xml` and `rc.xml.tmpl` | PASS: both XML documents parsed. |
| Actual trusted `btrfs-de-p15s.env` shell loading, Waybar placeholder substitution and `json.loads` | PASS: both internal/external configurations rendered and parsed; menu command tails checked. Hardware-dependent output/module values were explicit fixtures. |
| Render all project `.desktop` / `.desktop.tmpl` candidates outside the tree | PASS for rendering: 19 candidates, no unresolved application placeholders. External desktop-file validation remains skipped below. |
| `shellcheck` capability check | SKIPPED: binary absent; package installation unavailable in the execution environment. |
| `desktop-file-validate` capability check and capability-gated test | SKIPPED: desktop-file-utils binary absent on the execution host. It is already a selected target dependency and is invoked before publication in production. |
| `/usr/bin/python3 -I -c 'import gi'` | SKIPPED dependency path: import probe returned failure because PyGObject is absent. Real libgio C ABI probes passed; the actual GI test was skipped. |
| Actual target GIO import, running root path activation, systemd 261.2 transient processes, live Fuzzel/Waybar/Labwc, wallpaper persistence and AppArmor enforcement | SKIPPED: target/session runtime unavailable. Installation contains the target GIO binding check. |

The Python compiler command below was executed with all nine listed paths and an external bytecode cache. It passed:

```sh
PYTHONPYCACHEPREFIX="$AUDIT/pycache" /usr/bin/python3 -m py_compile \
  d-i/forky/hooks/target/usr/local/bin/labwc-main-menu \
  d-i/forky/hooks/target/usr/local/bin/labwc-sync-application-launchers \
  d-i/forky/hooks/target/usr/local/libexec/labwc-wrap-desktop-files \
  d-i/forky/tests/test_categorized_menu.py \
  d-i/forky/tests/test_system_desktop_overrides.py \
  d-i/forky/tests/gio_desktop_fixture.py \
  d-i/forky/tests/test_installation_fixes_20260912.py \
  d-i/forky/tests/test_systemd_resource_policy.py \
  tools/tests/test_scoped_desktop_fixes.py
```

No Perl production code changed. Perl-related static/test coverage is recorded in the module/audit results; missing Moo/MooX packages are not presented as a successful Perl runtime validation.

## Final acceptance boundary

The implementation and its installer payload are complete. Live target acceptance remains necessary: boot the resulting Forky/systemd 261.2 installation, exercise an actual dpkg transaction, launch both Fuzzel interfaces under enforced AppArmor, and confirm that Waypaper changes and persists a wallpaper across logout/reboot. Custom absolute XDG paths outside the default AppArmor allowlist require narrow local policy reads rather than a broad filesystem grant.

The source audit retained every original source file and only intentional additions. Original source modes were restored after rebuilding the generated artifacts. Validation caches, logs, fixture outputs, baseline copies and external dependency trees are not part of the project archive. The repository's pre-existing installer payload and wallpaper asset archive are required project files, not accidental nested deliverables.
