# Power lifecycle / resctl-bench validation

Date: 16 September 2026.

## Result

The four directly relevant suites pass **94 tests**: 36 existing power/keyboard
regressions, 14 power/I/O-policy regressions, 16 new synchronous-quiescence tests,
and 28 new resctl-bench integration/archive/publication tests. The two new files
contribute 44 tests. No reboot, poweroff, benchmark, live service activation or
kernel AppArmor policy load was performed.

The final repository-wide result is **not all green**. The isolated runs completed
1,136 unittest test methods across 47 test-bearing modules, with 27 skips and no
module timeout. Forty-one modules pass; six retain failures/errors that reproduce
with the same test identifiers on the unchanged uploaded codebase. A 48th file,
`test_environment.py`, is a capability-helper module with zero tests; its Python
3.13 unittest exit status 5 is recorded, not counted as a passing test module.

The broad one-shot validator hit its existing 300-second test-stage deadline.
That result remains recorded as unsuccessful in `summary.json`. The tests were
then run in isolated, bounded module processes rather than weakening production
checks or increasing the repository validator's default deadline.

## Current result locations

All paths below are relative to `validation/power-resctl-20260916/`:

| Record | Meaning |
| --- | --- |
| `summary.json` and stage logs | Original repository validator; five non-test stages pass, test stage times out at 300 seconds. |
| `modules/summary.json` and logs | Initial isolated run of every `test_*.py` module, with no module timeout. |
| `final-reruns/summary.json` and logs | Final profile-integrity/resource-policy checks after the new pin provenance was recorded, plus explicit identification of the no-tests helper. |
| `final-summary.json` | Final-state aggregate using those three rerun records in place of the initial records; all other module results remain unchanged. |
| `baseline/summary.json` and logs | Six failing modules executed against the pristine uploaded source, with the same failing test identifiers. |
| `apparmor-power.log` | Power-wrapper AppArmor profile compiled using `apparmor_parser -Q -K`, without kernel loading. |
| `final-static.log` | Final generated-product consistency and whitespace validation. |
| `run_module_validation.py` | Reproducible bounded module-runner used for these tests. |

Earlier failing logs are deliberately retained; they are not silently relabeled
as successful. `final-summary.json` identifies which log is authoritative for
each module and which remaining failures match the pristine baseline.

## Passing objective-focused checks

| Suite/check | Result |
| --- | --- |
| `test_power_keyboard_20260913` | 36 tests pass. |
| `test_power_io_policy_r6` | 14 tests pass. |
| `test_power_quiescence_20260916` | 16 tests pass. |
| `test_resctl_bench_20260916` | 28 tests pass. |
| `test_log_launchers_20260915_r3` | 29 tests pass, including explicit host PID/user semantics for canonical administration launchers. |
| `test_policy_review_20260916` | 15 tests pass. |
| `test_systemd_resource_policy` | 16 tests pass after excluding only the explicitly added resctl-bench hooks/pin block from the historical-byte preservation comparison. |
| `test_repository_integrity` | 10 tests pass after recording the new profile hashes in the existing provenance ledger. |
| Browser/build/preseed/shell validation | All four stages pass. |
| Repository audit command | Returns success; its blocked/inventory-only classifications are not runtime acceptance tests. |
| Power AppArmor profile compilation | Parser returns success without kernel loading. |
| `tools/build.py --check`; `git diff --check` | Both pass. |

The power tests use mocked manager/guest/power operations: synchronous stop,
complete membership verification, stop failures, pending jobs, remaining PIDs,
late launch guards, post-commit failure behavior, exactly one force submission,
no retry of an uncertain handoff, no forbidden intermediate targets, fixed guest
hooks, and transport descendant cleanup. A successfully drained transport is no
longer subjected to an unconditional process-group SIGKILL.

The resctl-bench tests use synthetic release archives matching the reviewed
packaging layout. They cover all 13 profile pins, architecture/policy rejection,
HTTPS/download/hash bounds, traversal/links/sparse/special/duplicate member
rejection, decompression limits, checksum inventory, required binaries, ELF
validation, no-clobber publication, repeat installation, rollback on a caught
publication failure, directory trust and helper removal. One harmless compiled
ELF fixture exercises real unprivileged `--version` execution; it is not the
actual downloaded resctl-bench release.

## Baseline-reproduced failures and limits

| Module | Remaining result, also observed on pristine input |
| --- | --- |
| `test_codex_clone_staging` | Two signal-handling subcases time out waiting for shell fixture cleanup: SIGHUP and SIGINT. |
| `test_desktop_sandbox` | Historical AppArmor incident-mapping assertion fails. |
| `test_installed_failures_20260911` | Historical raw audit fixture `todo/managed/apparmor/apparmor.log` is absent. |
| `test_log_regressions_20260915` | Historical assertion expects a single app-scope drop-in although the upload also contains the newer resource-class drop-in. |
| `test_managed_external_software` | Four tests cannot load Perl `Moo.pm` in this validation environment. |
| `test_podman_incus_redesign` | Historical Fuzzel terminal-vector test raises a tuple-unpacking error. |

These unrelated failures, missing fixtures/dependencies and stale expectations
were not hidden, deleted, or used as grounds for broad production changes.
Likewise, the additional legacy `tools/tests` directory is not the default
`make test` suite and is not claimed as validated here.

Local tools were Python 3.13.5, systemd 257.9 and AppArmor parser 4.1.0. systemd
261.2 behavior was reviewed from its tagged source; no booted 261.2 system was
available for hardware/session acceptance. Parser/lexical checks do not prove
live AppArmor enforcement or every installed unit's behavior.

The real release archive could not be downloaded into this container. Its
user-supplied SHA-256 is enforced by the target installer, but has not been
independently verified against downloaded release bytes here. The actual native
binaries were not executed. Even a successful target `--version` check cannot
prove CPU-instruction compatibility of every subsequent benchmark workload.

The audit tool reports 433 pass, 171 structure-pass, 490 inventory-only,
155 blocked-dependency, 11 blocked-tool and 2 template-needs-render entries.
A successful audit command is therefore not a claim that all 1,262 inventoried
files were executed or that all runtime dependencies were available.

## Reproduction

Run from the extracted repository root:

```sh
python3 -B tools/build.py --check
python3 -B tools/validate.py --output-dir validation/local-validator
python3 -B validation/power-resctl-20260916/run_module_validation.py \
  --root . --output validation/local-modules --workers 4 --timeout 240
```

The validator may again hit its 300-second all-tests deadline; the module runner
records every test module separately. Do not interpret skips, missing tools or
the baseline-reproduced failures as passing runtime tests.

Before deployment, follow `POWER-RESCTL-2026-09-16.md` on a disposable target with
systemd 261.2: test save-dialog cancellation, concurrent-account refusal, both
power actions, recorder finalization, optional guest shutdown and previous-boot
journals; verify the actual release download and installed provenance. Publishing
this unattended-install tree is not an upgrade of already-installed hosts.

## Input identity

The exact uploaded `debian-preseed-de.zip` used as this change baseline has
SHA-256:

```text
5748223cbf8168f7e81a5a3b534a6384cf1e06a3489b260e9b9dfa99cdf519cb
```

Older manifests in the repository refer to earlier source archives. They remain
historical records and must not be confused with this input identity or the
current validation results.
