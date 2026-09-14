# Validation: Btrfs features and complete locale boundary

Date: 2026-09-15. This is a source/fixture validation record, not a claim of a
booted Debian installation.

## Results

| Check | Result |
| --- | --- |
| New regressions | **19 tests: 18 passed, 1 explicit missing-btrfs-tools skip.** |
| Same new tests against unchanged preceding source | Failures reproduce; 18 failure records include subtest failures, not 18 distinct failed methods. |
| GPG recipient/bootstrap/transport suite | **29 passed; no skips.** |
| Full repository suite | **949 tests: 916 passed, 5 failures, 2 errors, 26 skips.** |
| Remaining failure/error identifiers | All seven reproduced on the unchanged prior tarball in the same environment; no new identifiers. |
| Shell syntax | **277 shell files; 565 parser checks passed.** |
| Preseed validation | **59 files passed**, including four generated command values surviving actual private debconf read-back. |
| Generated build/payload/pins | Passed. |
| Payload/source comparison | **All 1,286 regular payload entries match source bytes.** |
| Btrfs/VM profile composition | All eight receive the canonical nondeprecated features list. |
| Real minimal-target locale execution | Passed without locale-gen or installer locale paths; UTF-8 after child unsets LC_ALL. |
| Prior minimal BusyBox no-stat regression | Passed; published checkout, no remaining stages, shared mode 3770 retained. |
| Selected unchanged integration inventory | **276 files** compared byte-for-byte. |
| Previous file retention | **All 1,837 previous regular files and all existing modes retained.** |

Focused tests overlap the full suite. New shell test methods use subtests for
multiple shells/branches; method totals are not the count of all subprocess
checks. The full run took 281.365 seconds in this container; that is
a measured completed duration, not a deployment timing estimate.

## Full-suite failures are not hidden

The full suite is not green. The five failures and two errors match the
unchanged baseline exactly:

- Four managed-external-software cases require Perl Moo.pm, unavailable in this
  validation container. The target package list already requests libmoo-perl.
- Two cases require the absent historical AppArmor incident fixture.
- One Fuzzel case has the existing subprocess-mock error.

Exact identifiers/tracebacks are in full-suite.log, baseline-known-failures.log
and baseline-comparison.json. Neither test data nor a substitute Moo module
was fabricated and no unrelated production code was changed to mask them.

## What is and is not exercised

The in-target fixture captures environment before and after the real target
env/shell invocation and models its documented passthrough and LANG override.
It does not run Debian Installer's mount/diversion setup. A separate real
chroot test copies existing trusted binaries and their libraries into a
throwaway root and executes the actual target_exec helper. Both are identified
accurately in the tests and review.

No btrfs-progs binary is available, and external download was unavailable.
Consequently the real temporary-image test is explicitly skipped. The option
migration is checked against upstream documentation and the exact canonical
argv/composed policy, not claimed as successful physical formatting.
ShellCheck is also unavailable; the successful shell checks above are parser
checks, not ShellCheck lint. The tool-availability record lists these limits.

No private GitLab authentication, live desktop, namespace activation,
AppArmor kernel enforcement or booted installation is claimed. No native
component was compiled and no package was installed to work around a failure.

## Reproduce

From the extracted complete repository:

```sh
python3 -B tools/build.py --check
python3 -B tools/check_shells.py
python3 -B tools/check_preseeds.py
python3 -B -m unittest discover -v -s d-i/forky/tests -p 'test_btrfs_locale_boundary.py'
python3 -B -m unittest discover -v -s d-i/forky/tests -p 'test_gpg_recipient_integration.py'
python3 -B validation/installer-no-stat-fix/minimal-initrd-rootfs-check.py --repository .
python3 -B -m unittest discover -v -s d-i/forky/tests -p 'test_*.py'
```

Use a disposable trusted Debian validation environment for root-only tests.
The complete tarball is separately extracted, content/mode compared, build
checked, and its new regressions rerun. Results of this final packaging check
are recorded beside the tarball in its verification JSON rather than inserting
a self-referential manifest into the archive.
