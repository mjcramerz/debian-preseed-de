# Measured validation results - 2026-09-19

Final source: the complete corrected `debian-preseed-de` tree. All commands ran
in this response in a disposable Linux container. Results below distinguish
executed checks from skipped, blocked, static-only, and unperformed acceptance.

## Final validation

| Check | Measured result |
| --- | --- |
| Installer/desktop regression suite | 1785 tests: 1748 passed, 37 skipped, zero failures/errors |
| Repository tooling suite | 179 passed; zero skips, failures, or errors |
| Shell parsing and dependency metadata | 282 shell files; 575 checks passed |
| Build/payload pins | `tools/build.py --check` passed; generated products match source |
| Preseed/debconf syntax | `tools/check_preseeds.py` passed |
| Browser generated artifacts | Current; check passed |
| New environment tests | 12 passed, including all-fragment fault injection and all 13 profiles |
| New native-menu tests | 13 passed, including control rejection, icons, exact routes and confirmations |
| Focused menu/AppArmor integration | 27 passed, including offline parsing of managed policies |
| Real profile shell compatibility | All 13 profiles fetched/composed with dash and BusyBox ash; fresh strict source checks passed |
| Additional JavaScript parsing | All 11 Polkit policy sources passed `node --check`; no policy was executed |

The 25 new regression tests are included in the installer/desktop suite; the
focused runs are additional executions, not additional distinct test counts.

Machine-readable final results: `validation/native-icons-env-20260919/summary.json`.
Full stdout/stderr is retained in the adjacent stage logs. No result file was
edited to convert a failure or blocked check into a passing result.

## Static audit coverage and limitations

The audit inventoried 1307 files. Its exact counts were:

| Audit classification | Files |
| --- | --- |
| blocked-dependency | 156 |
| blocked-tool | 11 |
| inventory-only | 500 |
| pass | 461 |
| structure-pass | 177 |
| template-needs-render | 2 |

The audit process returning success means no definite syntax/structure failures
were found in the checks it could perform. It does **not** make blocked checks
or inventory-only files successful runtime tests.

Of the 156 blocked Perl checks, 155 stop on unavailable `Moo.pm`. The remaining
launcher requires `LabwcNetworkScanAction/Root.pm`, whose supplied `.pm.tmpl` is
rendered by `desktop_render_labwc_network_scan_action_perl_root_module` during
target installation. The standalone audit does not materialize that target
library. These checks were not claimed as compilation passes. Desktop package
selection already includes the Moo/MooX dependencies and was not changed.

The 11 blocked-tool entries are JavaScript rules: the validator uses a restricted
PATH that does not include this container's Node installation. They were checked
separately using its absolute path; see `javascript-syntax.json`. The original
audit classification remains intact. Two raw TOML templates require rendering;
inventory-only configuration files have not been executed.

## All final regression skip reasons

| Count | Reason |
| --- | --- |
| 23 | Moo dependencies missing; MANAGED_TEST_PERL_ADAPTER=1 enables fixture-only control-flow tests |
| 1 | real btrfs-progs executables unavailable; no mock claimed as format validation |
| 1 | desktop-file-utils not installed on test host |
| 1 | python3-gi/GioUnix typelib unavailable on test host |
| 1 | fzf binary unavailable; fixed-argv/data behavior is unit tested |
| 1 | original todo/apparmor.log not supplied; policy/fixture checks remain enabled |
| 1 | rsyslogd is unavailable |
| 1 | original managed/apparmor/apparmor.log not supplied; parsed fixture checks remain enabled |
| 1 | live filtered-bus test requires preinstalled dbus-daemon, busctl and xdg-dbus-proxy |
| 4 | Perl validation dependency unavailable: Moo.pm; install libmoo-perl libmoox-strictconstructor-perl libmoox-types-mooselike-perl |
| 1 | OpenSSH client binaries are not installed in this validation container |
| 1 | no existing noexec /dev/shm; test never mounts filesystems |

The optional `MANAGED_TEST_PERL_ADAPTER` was not enabled to simulate missing
Moo modules. Historical raw audit logs absent from the upload were not invented;
their supplied parsed fixture and independent policy checks still ran.

## Earlier attempt and investigation

An earlier complete validator run is retained under `attempt-1/` rather than
overwritten. It had two failures. One was a stale pipeline-adjacency assertion
which ignored a pre-existing Kanshi installation step; only that test contract
was corrected, not the production pipeline.

The other was an aggregate request-count assertion: the generated HTTP bootstrap
completed successfully, with each source/payload artifact fetched exactly once,
but the server counted six total GETs instead of five. The cause of that extra
request was not established. Four standalone repeats, one repeat with complete
test discovery and original order, and the final full validator passed the
original strict count. No downloader policy or assertion threshold was relaxed;
the assertion only gained diagnostic output listing paths on future failures.
See `run-history.json`, `bootstrap-repeats.log`, and `bootstrap-original-order.log`.

A further intermediate run is preserved under `attempt-2/`. Separately, the
new SIGTERM process-group test demonstrated that an interrupted real transport
copy could leave a temporary file inside the private composer workspace. The
previous complete environment remained intact. Cleanup now removes the whole
private mktemp workspace, including nested transport temporaries, rather than
assuming it contains only the two main staging files. The red/green evidence
is in `signal-cleanup-regression.json`; the new case passes under both dash and
BusyBox ash. The final validator includes that case and the rebuilt payload.

## Delivery and preserved scope

All 2975 regular files from the upload are retained. Modified original
files comprise 11 production sources, 10 existing tests, and three generated
products. New source files comprise 1 optional AppArmor abstraction and 2 test
modules. Documentation and validation evidence are additional non-runtime files.

The readable patch omits generated product contents but the change manifest
includes their hashes. Archive verification separately compares every packaged
file's hash and mode against the final source tree and confirms no original
file is missing.

## Acceptance not performed

This is not a booted Debian Installer acceptance run or a guarantee against all
future failures. No target disk was partitioned, target service activated,
Wayland/Fuzzel GUI displayed, kernel AppArmor profile enforced, or hardware tuning
operation performed. Repository/mirror/package availability was not exhaustively
verified. Systemd audit checks are static structure checks, not live dependency
or lifecycle acceptance. Validate representative VM/Btrfs/F2FS and hardware cases
in a disposable installation environment before broad deployment.

## Runtime product hashes

```text
9b9dcff6226fb10b5d51000a1bd4087207100a4d9de4b0492773b779e183143d  d-i/forky/preseed.cfg
a333103f4a92de006c1bbd672b2ddfff0ecdac14491db657087f56b0a325c5e5  d-i/forky/payload.manifest
6aaaa412a29aa200d1e61d4e87b3ee1f5870d35080c04e1c4718175129705654  d-i/forky/payload.tar.gz
```
