# Installer staging repair - 24 September 2026

This repair continues from the previously delivered `debian-preseed-de-refactored.tar.gz`. It does not replace or redesign the Waybar/Fuzzel work.

## Reproduced faults and corrections

The generator was present in the payload. `network.sh` copied it into `/target/run/network-install`, then `in-target` invoked `/run/network-install/network-generate.pl`. Debian's chroot setup can bind-mount the installer's `/run` over `/target/run`, hiding the files staged before the call. The hardware-tuning installer had the same error with `/target/run/hardware-tuning.*`.

A shared `target_private_stage_dir` helper now allocates unique 0700 directories beneath the target's real `/tmp`. Both installers use the same target-relative path for fetching, rendering and execution, protect temporary inputs with a private umask, and remove staging on normal exit, failure and handled HUP/INT/TERM. The helper rejects invalid labels and missing or symlinked temporary parents. Runtime service directories under `/run` remain unchanged.

Real target execution then exposed a second installation blocker: the Perl renderer greedily combined adjacent SEARCH, WIFI and PERFORMANCE placeholders into one name. Non-greedy token matching now renders each fragment independently while retaining rejection of unknown/unresolved tokens.

Explicit failure guards also stop failed downloads, missing assets, failed generators and failed AppArmor parsing, including when a caller places the installation function in a shell conditional. The network state is accepted only as a regular, non-symlink file before publication.

## Narrow change scope

Four production files changed:

- `d-i/forky/scripts/late/target-assets.sh`
- `d-i/forky/scripts/late/network.sh`
- `d-i/forky/scripts/late/network-generate.pl`
- `d-i/forky/scripts/desktop/hardware-tuning.sh`

One existing hardware-test fixture was updated, and `test_target_staging_20260924.py` adds regression coverage. The payload archive, payload manifest and generated preseed were rebuilt. No baseline files were deleted: 1,736 of 1,744 baseline regular files remain byte-for-byte and mode-for-mode unchanged. The remaining eight are the four production files, the existing test fixture, and three generated artifacts. All 40 baseline paths containing Waybar, Fuzzel, Xwayland, Zoom or Discord remain unchanged.

No upstream package source was patched, no new build-from-source installation path was introduced, and hardware tuning values, activation gates, vendor policies and opt-in defaults were not altered.

## Validation

| Check | Result |
| --- | --- |
| New target-staging regressions | 11 passed; also passed in the full suite |
| Freshly extracted complete archive | All 11 staging tests and the build-consistency check passed again |
| Existing hardware/menu/multi-monitor group | 197 passed |
| Full repository suite | 2,580 total: 2,526 passed, 53 skipped, 1 inherited layout assertion failed |
| Tooling suite | 179 passed, no skips |
| Native hardware systemd/AppArmor parser matrix | 9 checks passed across Intel-only, Nvidia-only and combined configurations |
| Shell parsing | 291 files; 593 parser checks passed |
| Preseed validation | 59 files passed, including real debconf round trips |
| Generated artifacts and payload integrity | Passed; all 1,523 payload files match manifest hashes and the builder's mode policy |
| Whole-tree source inventory/syntax audit | Passed; 1,733 files inventoried, excluding Git and validation evidence |
| Wider configuration audit | Completed; 158 dependency-blocked and 11 tool-blocked checks are explicitly not passing validation |

The complete suite was rerun end-to-end, without timeout. Its sole failure is `test_repository_cleanup.SourceContracts.test_no_archived_reports_or_wildcard_dropin_directories`: the test forbids any root-level `validation*` path, but the unmodified input tarball already contains `validation/native-monitor-20260924`. The same assertion was reproduced on a fresh extraction of that input (`baseline-packaging-test.log`). The assertion and historical evidence were not removed or weakened to make the suite green. The previously reported opposite-role bootstrap assertion passed in this run.

The 53 skipped tests require dependencies or original logs unavailable in this environment; their reasons are retained in `full/tests.log`. The wider audit likewise retains explicit blocked states in `full/audit.json`. Missing validation dependencies are not evidence of missing target packages. `full/summary.json` correctly records overall success as false because of the inherited layout assertion.

Evidence lives in `validation/installer-staging-20260924/`. The final archive was repacked only to include the successful extracted-archive check logs and this report; executable source was verified unchanged after those checks. `baseline-reproduction.log` reproduces both original missing-file errors; `renderer-baseline-reproduction.log` reproduces the original adjacent-token error with corrected staging. The 11 new tests cover both /bin/sh and BusyBox, real Perl/Python target execution, private paths, repeat installation, dual-stack Ethernet/Wi-Fi, Intel-only/Nvidia-only/combined tuning, opt-in lifecycle wiring, failed assets, invalid state files, strict placeholder rejection and external SIGTERM cleanup.

## Test boundaries

Tests ran in a disposable Debian 13 environment with Perl 5.40.1, Python 3.13.5 and AppArmor parser 4.1.0. Systemd parser checks used 257.9, not the requested target's 261.2. Real interpreter chroots were used, but covering `/run` was simulated by moving/replacing its directory; this environment did not permit a real bind mount. Native systemd/AppArmor parser checks passed with fixture dependencies; no target services or AppArmor kernel policies were activated.

This is not a booted Forky installation, physical Intel/Nvidia tuning trial, monitor hot-plug test or target AppArmor enforcement acceptance test. The prior Waybar/Fuzzel limitations documented in `REFACTOR-VALIDATION.md` are unchanged. No claim of a flawless complete target installation is made.

## Deployment

Publish the complete extracted repository as one release, including the regenerated `d-i/forky/preseed.cfg`, `payload.manifest` and `payload.tar.gz`. Do not combine the new scripts with the old generated artifacts. Restart the failed installation using this release so that a previously cached payload is not reused. The served preseed location should continue to point at this release's `d-i/forky/preseed.cfg`.
