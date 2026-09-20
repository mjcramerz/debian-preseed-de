# R2 validation: late-command Debconf boundary repair

## Final measured result

The final repository validator completed all stages without a failure or timeout.
Its completion timestamp is `2026-09-19T22:44:06.833677+00:00`. This is offline/loopback and
isolated-chroot validation, not a booted Debian Installer acceptance run.

| Check | Result | Evidence under `validation/late-command-r2-20260919/` |
| --- | --- | --- |
| Installer / desktop unittest suite | 1,771 passed; 37 skipped; 0 failures or errors (1,808 run) | `tests.log`, `summary.json` |
| Repository tooling suite | 179 passed; 0 skipped or failed | `tools-tests.log` |
| Shell syntax / external dependency metadata | 285 files, 581 parser checks; no failures | `shell-check.json` |
| Browser pins, generated build, preseed drift | All checks passed | `browser-check.log`, `build-check.log`, `preseed-check.log` |
| Native target-boundary regressions | All 22 methods passed within the main suite | `tests.log`, `tests/test_target_debconf_boundary.py` |
| Native target maintainer frontend | Passed protocol round trips and saved private database | `maintainer-frontend.json` |
| Native apt / dpkg maintainer transaction | Synthetic package configured; private Debconf database saved | `apt-maintainer-transaction.json` |
| Corrected HTTP short-URL bootstrap | 24 of 24 runs passed, exactly 5 requests each; 3 workers | `http-fixture-framed-repeats.json` |
| Portable repeat harness smoke | 3 of 3 runs passed | `http-framed-portable-harness.json` |
| JavaScript / Polkit syntax supplement | All 11 sources passed native Node syntax checks | `javascript-syntax.json` |
| Embedded payload | All 1,379 entries match manifest, source bytes and build-mode policy | `payload-integrity.json` |
| Previous release preservation | All 3,029 regular files retained; 3,018 byte-identical; 11 changed; no mode changes | `source-preservation.json` |
| Original uploaded repository preservation | All 2,975 regular files retained; no mode changes | `original-upload-retention.json` |

Focused repetitions overlap the main suite and are not added to its test total.
There are 23 added unittest methods relative to the incoming release: 22 target
boundary methods and one redirect-header contract method. Both native package
supplements use disposable private target chroots, not the host package database.
Only the apt supplement installs a generated dependency-free fixture package;
it installs no production package and downloads no package from the network.

## Why this differs from the earlier validation

The old locale-boundary test asserted that installer Debconf state was cleared
before entering in-target. A captured-arguments stub could satisfy that assertion
without executing Debian's chroot setup or shell confmodule. The new tests use
real shell protocol clients and a private frontend. The old-code negative
control reaches the mtab marker but deadlocks before any frontend request or
target command; the fixed path completes the setup queries and target operation.
The negative control remains active and is deliberately terminated by its test
deadline. This expected termination is not an installer failure.

Tests include both BusyBox ash and dash; raw and preinitialized frontends;
stdin from /dev/null, a file or a pipe; stdout capture; all noninteractive
wrappers; literal command arguments; supervised, bounded and looped helpers;
answer-file publication; fail-closed descriptor checks; caller descriptor
preservation; and cleanup with the original child exit code retained. Native
systemd-hwdb and the complete IOCost metadata transaction run through the bridge
using the reported btrfs-de-dual-flex profile. No IOCost device calibration runs.

## Attempt history retained, not overwritten

`attempt-1/` records the initial full run: 1,807 tests, 37 skips, one failure.
The only failure was the existing aggregate HTTP request-count assertion. Each
snapshot artifact was downloaded once, but the short URL was requested twice.
Instrumented Wget output identified an HTTP test-fixture connection-close race;
the production retry recovered correctly. `http-fixture-race.json` preserves
the relevant trace and counts, and `http-fixture-framing.json` compares the old
and corrected headers.

`attempt-2/` is another full run against the same repaired production bridge
before the HTTP fixture was corrected: 1,807 tests, 37 skips, zero failures, and
all remaining validation stages passed. This successful rerun did not resolve
the known fixture race on its own and was not treated as the final result.

The final run adds explicit Content-Length and Connection headers in the local
redirect fixture, keeps the strict five-request assertion, and adds a response
contract test. No production retry, cache or downloader policy was changed.
All final stages pass. `run-history.json` records the three validator results.

Supplement authoring attempts are also retained. The first native maintainer
probe asserted stdout although the real confmodule directs its output to
stderr; the assertion was corrected. Its minimal target locale data was then
provided. The first apt probe lacked the `diff` executable in its minimal
chroot; the fixture was completed and rerun. These were test-harness defects,
not production-code changes. Their diagnostic files are clearly labeled
`first-attempt` or `pre-locale-fixture`, while the final JSON files show success.

## Skipped and blocked checks are not passes

The 37 skipped unittest cases include 27 requiring unavailable Moo-related
Perl dependencies. The other 10 need Btrfs formatting tools, desktop-file-utils,
PyGObject/GioUnix, fzf, rsyslog, OpenSSH, a live filtered D-Bus proxy, an existing
noexec test mount, or original historical audit logs that were not supplied.
`skipped-tests.json` retains the exact reasons and counts. No missing test was
silently converted to success, and no live mount was created for validation.

The static audit reports:

| Audit category | Count | Interpretation |
| --- | ---: | --- |
| pass | 461 | The individual parser/syntax checks passed; not runtime proof. |
| structure-pass | 177 | Systemd lexical structure only, not dependency or activation validation. |
| blocked-dependency | 156 | 155 need Moo; one requires a target-installed generated module path. |
| blocked-tool | 11 | Node was absent from the audit PATH; all 11 were separately syntax-checked using its absolute installed path. |
| inventory-only | 500 | Inventoried data/configuration, not executable runtime tests. |
| template-needs-render | 2 | Not parsed as a fully rendered target file in this audit. |

The audit output is retained unmodified; its blocked-tool classification is not
rewritten after the separate Node check. Polkit JavaScript syntax success does
not establish live policy authorization behavior. The 156 blocked Perl checks
remain blocked and are not included in the passing test counts.

## Archive and source integrity

The three canonical production changes are common/lifecycle.sh,
common/debconf.sh and common/target.sh. Generated embedded helpers and delivery
artifacts account for another six changes; two existing test modules account
for the remaining two. New fixtures, regression tests, reports and validation
evidence are added separately. No existing file or permission is dropped.
Native Fuzzel icon mappings, Hardware Tuning routing, AppArmor rules, profiles,
package selections, browser pins, storage policy and Secure Boot policy are
byte-identical to the incoming release.

The rebuilt products have these SHA-256 values:

```
5069496d0b053f0e1bd31f52a364e78b143d747a3ed3da318dcf34bdfd4927cc  d-i/forky/preseed.cfg
b64c09730474b95799fd89bd3bf7e00a5722d1e6fcd593fd0396830b8b87e3e2  d-i/forky/payload.manifest
b420ddecb81a2dcf43cec2617f34490cb23c87bbfc2c53cd673b926b58024e72  d-i/forky/payload.tar.gz
```

The accompanying external `debian-preseed-de-fixed-20260919-r2-verification.json`
records archive-member checks, a fresh extraction, and subsequent checks run
against that extracted tree. Its archive checksum is also supplied in a normal
`.sha256` file. Neither the raw uploaded host logs nor private probe databases
are packaged into the repository; input log hashes are retained for provenance.

## Reproduction commands

From the repository root, with the needed tools and loopback/chroot privileges
available in a disposable validation environment:

```sh
python3 -B tools/build.py --check
python3 -B tools/validate.py --output-dir /tmp/preseed-r2-validation --test-timeout 1200
PYTHONPATH=d-i/forky/tests python3 -B -m unittest -v test_target_debconf_boundary test_btrfs_locale_boundary
python3 -B validation/late-command-r2-20260919/maintainer-frontend.py
python3 -B validation/late-command-r2-20260919/apt-maintainer-transaction.py
python3 -B validation/late-command-r2-20260919/http-fixture-framed-repeats.py
```

The native supplemental harnesses print JSON; redirect stdout to retain a new
report. They provision disposable chroots from the validation host's installed
binaries and libraries. The exact tested tool versions are in `environment.json`.

## Acceptance limits

No booted Debian Installer, production package-set resolution, physical
partitioning, live Secure Boot enrollment, Wayland rendering, kernel-enforced
AppArmor session or hardware-tuning operation was performed. The native chroot
fixture deliberately reduces chroot-setup to its protocol, locale and environment
sequence; it does not execute real mounts/diversions or the compiled d-i
log-output/cdebconf backend. Unit, syntax, native helper and synthetic package
checks are not substituted for those acceptance tests.

This release corrects the reproduced late-command deadlock and associated stdin
handling defects while retaining the configured installation policy. It does
not establish that every future package mirror or hardware combination is
failure-free. Publish the entire rebuilt tree together and start a fresh
installer boot, not a continuation of the old stalled cached process.
