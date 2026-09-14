# Installer no-stat correction: validation and release record

Date: 2026-09-14

This record describes the correction based on
`debian-preseed-de-codex-clone-fixed.tar.gz`, SHA-256
`0c3b411848f0c9c23c07cd7b9eb5a1671ebfed02a80d8bac456599aa92f049a3`.
The detailed design and deployment notes are in
`docs/INSTALLER-NO-STAT-FIX-20260914.md`.

## Result and scope

The reported missing-`stat` / false-non-root failure is reproduced against the
previous source and corrected without relaxing the staging boundary. One
production function changed, in `scripts/late/devops.sh`. The existing staging
test module gained nine test methods; the existing 24 methods remain. The
payload, manifest and preseed configuration were regenerated together.

All 1,772 original regular files remain, with their original archive modes.
Exactly five existing files have changed contents: the production helper,
staging test module, payload, manifest and preseed. The added files are review,
validation and reproducibility records. No application or system component was
compiled. No installer credential was used or included.

## Executed checks

| Check | Result / evidence |
| --- | --- |
| Previous allocator, stat absent on PATH | Exact missing-command and false ownership errors under Dash, BusyBox ash and Bash; `pre-fix-no-stat.log`. |
| Focused staging suite | 33 passed, no skips, 23.317 seconds; `clone-staging-tests.log`. |
| Complete generated common library under all three shells | Passed with restricted PATH and no stat; `common-library-no-stat-integration.log`. |
| Minimal disposable root filesystem | Previous allocator fails; fixed allocator succeeds with no stat or Python inside the root. Both clean staging and preserve the shared 3770 parent; `minimal-initrd-rootfs-check.json`. |
| Browser artifacts and build consistency | Passed; `browser-check.log`, `build-check.log`. |
| Preseed validation | 59 files; all four command values passed private debconf read-back; `preseed-check.log`, `preseed-check-final.log`. |
| Shell syntax | 277 files; 565 parser checks passed; `shell-check.json`. |
| AppArmor source names-only parse | Exit 0; no policy load or enforce-mode test; `apparmor-names-parse.log`. |
| Runtime payload integration | Corrected helper and unchanged canonical readers/Python validator match payload; payload and manifest pins occur in preseed; `payload-source-verification.json`. |
| Full suite, initial run | 901 tests: 868 passed, 6 failures, 2 errors, 25 skips, 282.496 seconds; `tests.log`. |
| Full suite, confirmation | 901 tests: 869 passed, 5 failures, 2 errors, 25 skips, 283.594 seconds; `full-suite-confirmation.log`. |
| Remaining seven identifiers on unchanged input code | Same 5 failures and 2 errors reproduced; `unchanged-baseline-failures.log`. |

The focused suite is included in the full suite. The runs are not additive
counts of distinct tests. The initial full driver correctly records
`success: false`; that record is retained, not rewritten to hide failed tests.
The confirmation also has a nonzero exit status.

## Remaining full-suite failures

**The full suite is not green.** The seven remaining failures/errors are not
attributed to this fix merely because they reproduced on the baseline; their
observed causes are recorded explicitly:

| Cases | Observed cause |
| --- | --- |
| Four `test_managed_external_software` cases | Perl cannot load `Moo.pm` in this container. |
| `test_apparmor_complain_incident_is_fully_mapped` and `test_fixture_exactly_matches_the_supplied_raw_audit_events` | Original historical `todo/managed/apparmor/apparmor.log` fixture is absent. It was not fabricated. |
| `test_terminal_launch_is_argv_only` | Existing Fuzzel test subprocess mock produces a `ValueError` in the `subprocess.run` path. |

The exact identifiers and original tracebacks are in `final-results.json` and
the baseline comparison log. No unrelated production code or test expectation
was changed to manufacture a green suite.

### Additional initial-run HTTP assertion

The first full run also failed
`test_repository_transport.TransportTests.test_shortener_and_relative_redirect_chain`:
the expected `/short` request count was 1 and observed count was 2. The resolver
returned the correct URL. That test and its production transport code are
unchanged. The isolated test passed three times on the unchanged baseline,
three times on the updated tree, and again in the complete confirmation run.
The cause of the one extra request was not established. Both the initial
failure and successful rechecks are retained; this is not represented as an
implemented transport fix. See `redirect-assertion-recheck.log`.

## Audit and integration limitations

The repository inventory/audit tool returned zero, but it is not a universal
runtime pass: 155 checks were blocked by dependencies, 11 by missing tools,
485 were inventory-only, 431 passed, 130 were structure-only passes and two
templates needed rendering. See `audit.json` and `summary.json`.

Byte-for-byte comparison confirms no changes to the selected AppArmor policy
(72 files), systemd unit assets (138), SSH/GPG integration assets (14), GitOps
assets (3), debugsys assets (6), host profiles (21), power-named assets (11), or
Codex runtime assets (11). These sets are review groupings, not additional
tests and not necessarily disjoint. The rest of `devops.sh` outside the
allocator function is identical. See `unchanged-integration-inventory.json`.

The BusyBox fixtures use the installed container binary with explicitly
restricted applet exposure, not a downloaded busybox-udeb binary or a booted
Debian installer. The real-Git fixture uses local transport in a disposable
chroot; it does not authenticate to GitLab using OpenSSH. OpenSSH executables
are absent here. No actual install, partitioning, reboot, systemd service
activation, graphical GPG dialog, AppArmor enforcement or hardware/power
acceptance was performed. Those boundaries still require a disposable live
target. These checks cannot establish that every possible installation is
failure-free.

## Archive integrity

The original archive contains only regular files and directories under
`debian-preseed-de`, with no symlinks or hardlinks. Extraction safety filtering
initially removed some writable source-mode bits; the original file and
directory modes were restored from the input tar metadata before packaging.
This preserves the user's source tree rather than silently changing repository
permissions. No production target permission policy is derived from that
extraction metadata.

`source-change-inventory.json` compares contents and modes to the actual input
archive, not to extraction defaults. The final external `.verification.json`
records the release tar checksum, regular-file count, complete archive-to-tree
comparison and checks run again from the extracted delivery. Historical logs
under other validation directories belong to previous releases.

## Reproduction

Run in a disposable root-capable Linux environment with Python, BusyBox and Git:

```sh
python3 -B tools/build.py --check
python3 -B tools/check_shells.py
python3 -B -m unittest discover -v -s d-i/forky/tests \
  -p test_codex_clone_staging.py
python3 -B validation/installer-no-stat-fix/minimal-initrd-rootfs-check.py
```

The staging suite explicitly skips root-dependent cases when root is
unavailable. All 33 ran here. The minimal-root standalone checker fails with a
clear dependency error instead of silently skipping. To reproduce the old
failure as well, pass `--before` pointing to `devops.sh` extracted from the
previous tarball; do not replace the corrected active source.

Publish the complete matched snapshot and start a fresh installer boot. Do not
resume the old cached helper under `/tmp/install-runtime`. Private initrd keys
and passphrases stay outside the served codebase and do not need to change.
