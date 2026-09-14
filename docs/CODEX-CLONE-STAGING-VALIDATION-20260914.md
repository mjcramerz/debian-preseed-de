# Codex clone staging correction: validation - 14 September 2026

## Outcome and scope

The previous delivery's exact reported `unsafe Codex clone staging parent`
error was reproduced, repaired at the allocator/validator boundary, and covered
by executable regressions. A directly related checkout/publication permission
problem was also reproduced and corrected with a child-only Git umask.

The source comparison preserves all 1,724 prior regular files and their modes.
Exactly two existing implementation files changed:

- `d-i/forky/scripts/late/devops.sh`
- `d-i/forky/hooks/target/usr/local/libexec/managed-ssh-install.py`

The three other changed existing files are the regenerated `payload.tar.gz`,
`payload.manifest` and `preseed.cfg`. New tests, review and validation records
are included. Existing AppArmor policies, system/user units, 13 host profiles,
SSH/GPG runtime integration, GitOps, debugsys and power/isolation policies were
not broadened or rewritten. No application or system component was compiled.

See `CODEX-CLONE-STAGING-FIX-20260914.md` for the pre-implementation review,
follow-on review and deployment instructions. The exact implementation diff
and per-file before/after hashes are in `validation/clone-staging-fix/`.

## Executed checks on the final source

| Check | Result | Evidence in `validation/clone-staging-fix/` |
| --- | --- | --- |
| New clone boundary/publication regressions | 24 passed, no skips | `regressions.log` |
| Related integration suites | 192 run: 191 passed, one OpenSSH availability skip | `final-related-integrations.log` |
| Full repository suite | 892 run: 860 passed, 5 failures, 2 errors, 25 skips | `final-full-tests.log` |
| Comparison of remaining failures with unchanged previous delivery | All seven identifiers and outcome categories reproduced | `final-baseline-comparison.json`, `baseline-failures.log` |
| Browser/build consistency | Passed | `final-browser-check.log`, `build-check-final.log` |
| Preseed syntax and real debconf command read-back | 59 files passed | `final-preseed-check.log` |
| Shell syntax | 277 files, 565 parser checks passed | `final-shell-check.json` |
| AppArmor source parse | Passed; no kernel activation | `apparmor-parse.log` |
| Runtime payload contents | Both corrected implementation entries byte-identical to source | `payload-source-verification.json` |

The focused/related suites overlap the full discovery run; their counts are not
additional distinct tests. The machine-readable final record is
`final-summary.json`.

## What the new tests prove

The tests create a real root-owned, group-shared `3770` Codex root and reproduce
its inherited `2700` clone stage, including GNU chmod's setgid preservation.
They execute the production shell allocator under GNU, BusyBox ash/applets and
Bash; verify exact `0700`, owner checks and unchanged shared-root policy; and
exercise allocation/normalization failure, ineffective chmod, wrong ownership,
clone/publisher failure, and HUP/INT/TERM cleanup. Unsafe modes, symlinks,
existing destinations and paths outside the allowlist remain rejected.

Real Git inside a disposable chroot clones a two-commit local repository through
a test transport using the production fixed SSH URL/branch, clone arguments,
clean environment and validator. It verifies tracking `mcr/main`, preserved main
`.git/HEAD`, history, unchanged strict SSH configuration, and absence of
installer agent/configuration references from persistent Git configuration.
The fixture transport is NOT OpenSSH and does NOT prove GitLab authentication.
Only preinstalled Git/shell binaries and their libraries are copied; there is
no compiler invocation, daemon installation, mount or host `/data` modification.

The publication test executes the actual config-copy/permission block against
the fixture checkout. Root-owned ordinary configuration files are `0644`,
directories and tracked executables are `0755`, and an actual unprivileged UID
can read but cannot write them. That UID cannot read the checkout while its
root-only `0700` staging parent encloses it. Other tests verify that Git's
child-only `022` umask does not change the parent's `077`, default child file
permissions, SSH staging `0700`, or temporary SSH config `0600`.

## Red tests and earlier validation attempts

The full suite is not green. The same remaining five failures and two errors
were executed against a separately extracted, unmodified copy of the previous
delivery in the same environment. Four failures require unavailable Perl
`Moo.pm`; one failure and one error depend on the absent original
`todo/managed/apparmor/apparmor.log`; the remaining error is the existing Fuzzel
subprocess-mock unpacking error. None was hidden, rewritten or fabricated.

The canonical `tools/validate.py` wrapper's initial test stage reached its fixed
300-second limit. Its other stages passed. The preserved `full-validation/`
records that timeout honestly. A standalone 600-second validation-only wrapper
then completed 888 tests on the initial staging correction, with the same seven
failures. After the four publication/umask regressions and final helper update,
the final full run completed all 892 tests in 397.459 seconds.
No production timeout or validator source was changed to obtain that run.
`full-tests-complete.log` is historical; `final-full-tests.log` is authoritative
for this revision.

`pre-publication-fix-proof.log` is an intentionally failing regression run that
shows the root-owned config mode `0600` before the follow-on fix. The earlier
`baseline-regression-proof.log` similarly records expected failures against the
previous delivery, including the exact user-reported diagnostic. They are
reproduction evidence, not passing validation results.

The broader static audit includes dependency-blocked, inventory-only and
unrendered-template entries. Those categories are not runtime passes; see
`final-audit.json` for their exact counts and limits.

## Remaining live acceptance

No physical/virtual Debian installer was booted. The environment has no OpenSSH
executables, real deployment keys, live Labwc/GPG graphical session or target
systemd/AppArmor enforcement context. Actual private GitLab authentication,
GPG prompting, service namespace activation, hardware access, power transitions
and initramfs rebuild/reboot behavior therefore remain live-target acceptance
items, not claimed successes of this container run.

Deploy the complete matched snapshot and restart the failed installation using
it: the failed run already cached the old payload. Keep private initrd inputs
outside the served checkout. Do not relax the helper guard, change the shared
Codex root to `0700`, or disable AppArmor. The final archive is independently
extracted and checked; its verification record is distributed alongside it.
