# Lifecycle review validation - 14 September 2026

## Result

The complete updated repository contains the four selected PrivatePIDs changes
and the scoped SSH/GPG, GitOps, AppArmor, power-transport and diagnostics fixes.
The pre-implementation review was written before source edits and inventories
99 service definitions, templates and drop-ins. All 1,685 regular files from the
previous delivery remain present. The implementation changes 28 existing files
(including documentation and three generated products); it adds a regression
module and review/validation documentation. There are no deleted source files.

**The full repository suite is not green.** It completed 868 tests: 5 failures,
2 errors and 25 skips. All seven failing/error test identifiers were rerun against
the previous delivered tarball in this same environment and reproduced there.
No new failing/error identifier was introduced. The 30 added lifecycle-review
regressions pass. This is not a claim that skipped, blocked or unexercised runtime
paths pass.

## Validation evidence

| Check | Observed result |
| --- | --- |
| New lifecycle review regressions | 30 passed, no skips; includes real TERM/HUP child-group cleanup and bounded power-reap error handling. |
| Managed SSH/GitOps/debugsys suite | 56 tests: 55 passed, 1 OpenSSH-binary availability skip. |
| Existing lifecycle suite | 22 passed. |
| Existing security refactor suite | 28 passed. |
| Existing power/keyboard suite | 34 passed. |
| Existing hardware restoration suite | 25 passed. |
| Existing Codex installation/session suite | 22 passed. |
| Full repository suite | 868 tests; 5 failures, 2 errors, 25 skips; completed without timeout. |
| Browser configuration generation check | Passed. |
| Payload/build consistency and preseed checks | Passed; 1,286 payload entries regenerated. |
| Shell syntax | 277 shell files, 565 parser checks; passed. |
| AppArmor source parse | Exit 0 using apparmor_parser -Q -T; no kernel policy load. |
| systemd 257.9 unit fixture | 10 unit names verified, exit 0 and no diagnostics; synthetic root/stub dependencies, not activation. |
| Read-only debugsys smoke | 26 evidence records; root ownership, 0700 directories, 0600 files and every manifest evidence hash verified. |
| Host-key comparison | Unchanged GitLab/GitHub Ed25519 entries match official published key/fingerprint evidence; no authentication attempted. |
| Source/installed operations guide copies | Byte-identical. |

The standalone focused-suite runs are useful localizations, not extra distinct
tests to add to the full-run count. The final full run and the last 30-test run
both include the final bounded-wait refinement in the power worker.

The read-only diagnostic smoke recorded 13 successful probes, 6 nonzero probes,
4 unavailable tools, 2 no-match records and 1 no-session record. These are honest
coverage outcomes, not a clean bill of health. The raw container report was
removed and is not included in the archive; its hash/permission verification
summary is included.

The canonical source-audit command returned zero, but its coverage inventory is
**not** all-pass: 431 pass, 130 structure-pass, 485 inventory-only, 155 blocked by
dependencies, 11 blocked by tools, and 2 templates needing rendering. Its complete
JSON is retained. Do not count inventory-only or blocked records as tests passed.

## Unchanged failing tests

Four managed-external-software assertions fail because this validation container
has no Perl Moo.pm. The desktop package selection already includes libmoo-perl;
this review does not replace that dependency with a stub or rewrite those tests.

Two AppArmor-incident fixture assertions (one failure, one error) require the
missing original file `todo/managed/apparmor/apparmor.log`. That absent incident
log was not fabricated. The remaining error is the existing Fuzzel terminal
subprocess-mock unpacking failure in `test_terminal_launch_is_argv_only`.

`baseline-comparison/comparison.json` and its log record the exact seven test IDs
and their reproduction against the previous delivered tarball, whose SHA-256 is
`a77a8158bfec910bc281aa827d88558c8ab7fa717fb9053d75fdaae383f9f532`.

## What the review changed

PrivatePIDs is enabled only for bluetooth-controller-init,
managed-nvidia-char-links, zram-writeback and zram-writebackd. All explicitly keep
PrivateUsers=no, control-group cleanup and bounded stop behavior; zram retains
aggregate proc access. Namespace-init signal handling is explicit. Power handoff,
forking lock, diagnostic collection, tmpfs pre-clean and SSH agent/loader retain
host namespace semantics. No new identity/full/self user mapping is installed.

SSH unlock now verifies the agent can sign after the loader transaction; skipped
conditions cannot masquerade as unlock success. Lock can still stop a session
agent with broken key metadata. Agent lifetime is explicitly gated and ordered
against the active Labwc target and compositor. Private directories remain 0700;
public-key reread/rollback respects the supported public modes without relaxing
private-key/ciphertext permissions. Pinentry signal mediation has matching exact
AppArmor peer rules.

GitOps cancellation unwinds independent Git children; canonical protected-path
validation and rooted directory-glob matching close protection gaps. Power bridge
cleanup is unconditional and retains a bounded reap timeout. Debugsys records
nonsecret namespace/cgroup/agent-lifecycle metadata and budgets its dynamic root
filesystem probe. Existing authorization, save/lock/commit order, Codex sandbox
and mcr/main tracking, initramfs transaction/rollback and private-initrd secret
boundaries are preserved.

See `LIFECYCLE-ISOLATION-REVIEW-20260914.md` for the complete rationale, exclusions,
primary documentation sources and live acceptance sequence.

## Reproduction and environment

From the repository root, with the normal project test dependencies installed:

```sh
python3 -B tools/build.py --check
python3 -B tools/validate.py --output-dir /tmp/debian-review-validation
python3 -B -m unittest discover -v -s d-i/forky/tests \
  -p test_lifecycle_review_20260914.py
apparmor_parser -Q -T -I d-i/forky/hooks/target/etc/apparmor.d \
  -I /etc/apparmor.d \
  d-i/forky/hooks/target/etc/apparmor.d/managed-desktop-wrappers
```

The actual host runner was `/opt/pyvenv/bin/python3` with PyYAML, using a controlled
standard system PATH. Installed target scripts retain their Debian interpreter
paths. An earlier run using a Python without PyYAML and interrupted preliminary
runs are not treated as validation success. No package, library, kernel, OpenSSH,
GnuPG or systemd component was compiled to resolve an issue. Build scripts here
regenerate repository assets and checksums, not application binaries.

The container is Debian 13, uses supervisord rather than systemd as PID 1, and
rejects PID namespace creation with Operation not permitted. systemd-analyze is
257.9; its isolated fixture uses stub executables and dependencies while preserving
reviewed directives/order. OpenSSH executables and the graphical desktop are
absent. AppArmor parsing does not establish enforce-mode behavior. Package-index
access did not install dependencies; missing-tool/dependency outcomes remain
visible instead of being hidden.

## Remaining target gates

A disposable real target must verify actual PID namespace creation and unchanged
user namespace identity, hardware operations, service stop/restart, GPG cold/warm/
cancelled pinentry, authenticated Git provider access, shared normal/devops agent,
logout cleanup, Codex socket isolation, and AppArmor enforcement. Power denial,
save cancellation, other-user protection, lock readiness, suspend and authorized
reboot/shutdown need the live desktop. Initramfs arm/rebuild/boot/remove/rebuild
acceptance must also happen there. This container did not rebuild or boot an
initramfs or perform a power action.

The archive is accompanied by a SHA-256 file and a separate extracted-package
verification record to avoid a self-referential archive hash. Historical reports
from the previous delivery are retained as historical evidence, not substituted
for this revision's results.
