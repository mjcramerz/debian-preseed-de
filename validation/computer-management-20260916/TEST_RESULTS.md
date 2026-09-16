# Validation results

## Broad suite and baseline comparison

| Source | Tests | Passed | Failures | Errors | Skipped |
| --- | ---: | ---: | ---: | ---: | ---: |
| Untouched uploaded repository | 1,136 | 1,101 | 6 | 2 | 27 |
| Revised repository | 1,180 | 1,145 | 6 | 2 | 27 |

The exact failure/error test names are unchanged. There are **no additional failing/error test cases observed** relative to the baseline. This is not an all-green test suite. No existing failing tests were removed, skipped or relaxed to conceal a failure. One existing Remote Desktop expectation was updated to assert the intentional managed-launch route and preserved wait setting instead of a direct Thunar launch.

The broad run overlapped the final service backup-directory refinement. After the last source edit, all 33 new integration/process/boot tests, all 15 existing policy-review/compiler tests, the source audit, and the generated payload check were rerun. The full suite was not rerun a second time on that final immutable tree. The 11 core-Perl method tests had passed against the final Perl source. Raw logs are included.

## Focused checks

- **33 added tests pass**: boot argument validation, real-file boot transactions with mocked external GRUB commands, interruption/rollback, symlink/hardlink/ownership checks, subprocess deadlines/output limits, remote-log limits, action dispatch and installer/service contracts.
- **11 additional core-Perl tests pass**: actual production method bodies exercise mode commit/restore, failed rollback, concurrent source change preservation, live-disable rejection, workspace cleanup, draft activation and exact-source audit rollback. These tests do not simulate Moo or claim the full application imported successfully. Constructors/accessors, lock acquisition and external parser/kernel boundaries are doubles.
- **15 existing policy/review tests pass**: includes native `apparmor_parser -Q -K` compilation of repository profiles with staged abstractions. No policy was loaded into this environment. Vendor local fragments are compiled under synthetic envelopes; installed vendor-policy integration is still required.
- **Build passes**: 1,338 payload files; generated preseed, manifest and payload are current according to `python3 -B tools/build.py --check`.

## Unresolved broad-suite failures/errors

- `ERROR: test_fixture_exactly_matches_the_supplied_raw_audit_events (test_installed_failures_20260911.RecordedAppArmorCoverageTests.test_fixture_exactly_matches_the_supplied_raw_audit_events)`
- `ERROR: test_terminal_launch_is_argv_only (test_podman_incus_redesign.FuzzelTests.test_terminal_launch_is_argv_only)`
- `FAIL: test_apparmor_complain_incident_is_fully_mapped (test_desktop_sandbox.InstalledFailureRegressionTests.test_apparmor_complain_incident_is_fully_mapped)`
- `FAIL: test_chatgpt_forbidden_installed_dependencies_fail_postinstall (test_managed_external_software.ManagedExternalSoftwareTests.test_chatgpt_forbidden_installed_dependencies_fail_postinstall)`
- `FAIL: test_chatgpt_repacked_depends_excludes_x11_xwayland_and_nvidia (test_managed_external_software.ManagedExternalSoftwareTests.test_chatgpt_repacked_depends_excludes_x11_xwayland_and_nvidia)`
- `FAIL: test_repository_failure_is_reported_for_every_managed_deb (test_managed_external_software.ManagedExternalSoftwareTests.test_repository_failure_is_reported_for_every_managed_deb)`
- `FAIL: test_repository_package_digest_uses_the_512_mib_streaming_bound (test_managed_external_software.ManagedExternalSoftwareTests.test_repository_package_digest_uses_the_512_mib_streaming_bound)`
- `FAIL: test_scope_dropin_covers_all_app_prefixes_and_is_staged (test_log_regressions_20260915.DesktopAssetTests.test_scope_dropin_covers_all_app_prefixes_and_is_staged)`

Two tests require an incident fixture absent from the upload. One scope-drop-in test assumes a single existing file although the original tree also contains its resource-class drop-in. The container terminal test uses a subprocess mock inconsistent with the already-existing implementation. Four managed-external-software tests cannot load Moo. All eight nonpassing cases occur in the baseline as well; they are retained rather than fixed outside this request's runtime scope. The transient signal-test timeout seen in an earlier intermediate run did not recur in the completed broad run.

## Whole-source inventory/syntax audit

The audit contains 1,160 requested target/installer files and 1,266 files when related host/installer inputs are included. Check classifications are: 445 pass, 173 systemd structure-pass, 156 blocked-dependency, 490 inventory-only, and two templates needing rendering. A structure check does not execute systemd, resolve vendor dependencies or exercise a namespace. A missing-dependency result is not a pass. See `audit.json` for per-file classifications and hashes.

The environment has Python 3.13, core Perl 5.40 and a native AppArmor parser; it has no running target systemd, target desktop, real target devices or complete Moo/MooX/Types::Standard stack. Target Python 3.14-specific installed paths were checked as source/installation contracts, not claimed to be a live Python 3.14 session.

## Reproduction commands

Run from the repository root with the target development dependencies installed:

```sh
python3 -B tools/build.py --check
python3 -B -m unittest discover -s d-i/forky/tests
python3 -B -m unittest discover -s d-i/forky/tests -p test_computer_management_20260916.py
python3 -B -m unittest discover -s d-i/forky/tests -p test_management_perl_methods_20260916.py
python3 -B -m unittest discover -s d-i/forky/tests -p test_policy_review_20260916.py
python3 -B d-i/forky/tests/audit_codebase.py --output validation/computer-management-20260916/audit.json
```

The root-owned boot fixtures require an appropriate root test environment and protected temporary directory; do not run tests against a real host's boot paths. These regression fixtures redirect those paths and mock external destructive boundaries. See REVIEW.md for the separate target-system acceptance procedure.
