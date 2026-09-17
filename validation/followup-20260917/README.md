# Follow-up validation - 2026-09-17

This records validation of the complete **hardware-tuning-r2** repository. It supplements, rather than rewrites, the previous release's historical validation under `validation/hardware-tuning/`. This is not an on-hardware stability certificate and the complete test suites are not all-green.

## Results

| Check | Actual result | Evidence in this directory |
| --- | --- | --- |
| Hardware tuning tests | **79/79 passed**, no failures, errors or skips | `hardware-tests.log` |
| resctl-bench tests | **39 passed, 1 skipped; 40 total**, no failures or errors | `resctl-tests.log` |
| Main repository tests | **1271 total: 1235 passed, 28 skipped, 6 failures, 2 errors** | `final-tests.log`, `final-tests-status.json` |
| Untouched previous tarball, main failure cases | The same **6 failures and 2 errors** reproduced | `baseline-main-failures.log`, `baseline-main-failures.json` |
| Additional tools suite | **179 tests; 3 failure entries and 5 error entries** | `tool-tests.log` |
| Untouched previous tarball, tools failure cases | All **8 failure/error entries** reproduced | `baseline-power-tool-tests.log`, `baseline-tool-comparison.json` |
| Generated systemd units | **6/6 offline checks passed**: Intel, NVIDIA, both; system and user | `generated/generated-integration.json` |
| AppArmor policies | **3/3 compilations passed**, including affected desktop parent domains | `generated/apparmor-*.log` |
| Shell parsing | **279 files, 569 parser checks, all passed** | `shell-check.json` |
| Preseed validation | **59 preseed files passed**; four generated command values survived private debconf read-back | `preseed-check.log` |
| Browser artifacts | Current; no generated browser changes | `browser-check.log` |
| Payload/build verification | **1,354 members** matched source and manifest; all preseed pins matched; two successive rebuilds were byte-identical | `payload-verification.json`, `rebuild-*.log`, `build-check.log` |
| Broader syntax/inventory audit | 456 syntax passes, 173 structural passes, 156 dependency-blocked, 495 inventory-only, 2 templates needing rendering | `source-audit.json` |

`summary.json` provides machine-readable totals. The recorded Python-source hashes in `final-tests-status.json` were rechecked against the final source after the test run.

## Scope and regression coverage

Only two production Python files change: the resctl-bench installer and the NVIDIA temperature aggregation helper. Existing profile settings, release pins, hardware/class gates, application mappings, Waybar left-click actions, delegation and AppArmor permissions remain unchanged. Documentation, two regression-test modules and rebuilt payload artifacts accompany the changes. `source-changes.patch` contains the source/test/documentation changes; it is evidence, not a substitute for the complete release.

The resctl regression tests cover verified-copy staging, unchanged 0700 archive privacy, root-owned 0711 probe-directory and 0555 binary modes, checksum corruption, invalid inventory, symlinks, writable ancestors, explicit noexec-destination refusal, permission-denial diagnostics, nonzero exits/timeouts and cleanup. Real harmless ELF fixtures assert nobody UID/GID, no supplementary groups, version-only argv, a private home and no executable write access. They also exercise final publication of the original verified files. The existing download/archive/provenance/rollback/shell-staging tests remain in the run.

The NVIDIA tests reproduce the pre-fix multi-GPU sensor gap (`hardware-before-fix.log`) and verify complete/missing/invalid sensor readings, rejection of risky writes before mutation, and health-interlock restoration. No real GPU settings were changed. Existing tuning tests cover the 32 gate combinations, profile/config schemas, vendor menus, arbitration, seat authorization, recovery, reports and application/DevOps lifetime behavior.

## Known inherited main-suite failures

The same eight cases fail on the untouched previous tarball in this environment. Their earlier reproduction on the original uploaded ZIP is retained in `../hardware-tuning/repository/original-failure-comparison.json` and its log.

Two cases need historical AppArmor incident files that are absent from the supplied repository. Four cases cannot load the environment's missing Perl **Moo** dependency. The desktop package class still explicitly includes `libmoo-perl` and the MooX packages; they were not removed from target installation. One case has a pre-existing app-scope drop-in expectation mismatch. One case has a pre-existing Podman terminal subprocess mock mismatch. No production behavior was changed to satisfy these unrelated expectations, no tests were removed, and these failures are not counted as passes.

The tools suite's eight failure/error entries are all in the pre-existing `test_labwc_power_handoff.py` cases, which expect older APIs/capability settings. They are reproduced on the untouched previous tarball and are unrelated to either changed production file. Entries can include subtests; the report does not infer a successful-test count by subtracting entries from 179.

## Environmental limits

The actual systemd checker is **257.9**, not the target's **261.2**. Offline generated-unit fixtures substitute harmless executables and fixture session/AppArmor dependencies; the real services were not started. AppArmor was compiled with no kernel load, not enforced on the target hardware. Native CPU/loader compatibility of the pinned resctl-bench binary, GUI menu behavior, systemd 261.2 runtime lifecycles, actual driver writes, suspend/resume and thermal stability remain installed-host acceptance checks.

The supplied audits show `/var/tmp` mounted `noexec`; exact archive members, line numbers and records are in `audit-noexec-evidence.json`. This container's `/var/tmp` and `/dev/shm` are executable. An isolated mount-namespace capability probe was denied, so the real-noexec regression is **skipped**, not represented as passing. The injected noexec/EACCES paths and real credential-dropped ELF tests are separate passing tests. See `noexec-runtime-limit.txt`; no mount or AppArmor policy was weakened.

An initial run used the container's system Python, which lacks PyYAML and therefore could not import the existing configuration-safety module. `full-tests.log` and `system-python-tests.log` retain those superseded runs. The final run uses the available `/opt/pyvenv/bin/python3` with PyYAML; that module is included. A dependency-index attempt could not reach the Debian mirror because of DNS resolution; no packages or repository policies were changed (`dependency-index-attempt.log`). The remaining blocked Perl checks are explicitly recorded rather than bypassed.

## Reproduction

Run from a trusted checkout with the project's test dependencies installed. The ownership/credential-drop fixture tests require root. They do not install release binaries onto the host or change hardware. Use an isolated build/test machine.

```sh
python3 -B -m unittest discover -v -s d-i/forky/tests -p 'test_hardware_tuning*.py'
python3 -B -m unittest discover -v -s d-i/forky/tests -p 'test_resctl_bench*.py'
python3 -B -m unittest discover -v -s d-i/forky/tests -p 'test_*.py'
python3 -B -m unittest discover -v -s tools/tests -p 'test_*.py'
python3 -B tools/check_hardware_tuning.py --output-dir /root/tuning-unit-validation
python3 -B tools/build.py --check
```

Publish the whole repository atomically with the matched payload, manifest and preseed. On the actual hosts, retain `/var/tmp` noexec and follow `docs/hardware-tuning/ACCEPTANCE.md` plus the resctl acceptance steps in `HARDWARE-TUNING-FOLLOWUP-2026-09-17.md`.
