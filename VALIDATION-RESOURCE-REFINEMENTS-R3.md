# Validation - resource policy revision 3

> Historical R3 report. Superseded by RESOURCE-POLICY-APPARMOR-R4.md and VALIDATION-R4.md.

Date: 2026-09-16. Base: accepted revision 2; all protected workload files are
checked against the original user archive as well.

## Result

The selected 16 test modules ran **453 tests: 444 passed, 3 skipped, 5 failed,
and 1 errored**. All 25 resource-policy tests passed. The six unresolved cases
were reproduced against a fresh extraction of the original archive under the
same environment. This is not a claim that the full repository aggregate suite
passed; that aggregate suite was not run for R3.

Environment: `systemd 257 (257.9-1~deb13u1)`, `Python 3.13.5`, `git version 2.47.3`.
The available systemd parser is 257.9, **not 261.2**. Relevant systemd 261.2
Debian documentation was consulted. No Debian installer boot, live desktop
session, real cgroup scheduling benchmark, crash-flood test, or authenticated
GitHub/GitLab acceptance test was performed.

## Selected module results

| Module | Tests | Result |
|---|---:|---|
| `systemd_resource_policy` | 16 | OK |
| `systemd_resource_refinements` | 9 | OK |
| `gitops_mirrors` | 16 | OK |
| `managed_git_debugsys` | 56 | OK (skipped=1) |
| `repository_integrity` | 10 | OK |
| `btrfs_locale_boundary` | 19 | OK (skipped=1) |
| `config_safety` | 19 | OK |
| `dbus_broker` | 16 | OK |
| `lifecycle` | 22 | OK |
| `lifecycle_review_20260914` | 30 | OK |
| `desktop_integration_20260914` | 28 | OK |
| `desktop_sandbox` | 70 | FAILED (failures=1, skipped=1) |
| `log_regressions_20260915` | 23 | OK |
| `managed_external_software` | 6 | FAILED (failures=4) |
| `hardware_restore` | 25 | OK |
| `podman_incus_redesign` | 88 | FAILED (errors=1) |

## Focused checks

The resource tests cover all 13 profiles in both I/O modes through the production
POSIX renderer, exact six-weight allowlisting, malformed and missing values,
CPU/socket bounds, atomic publication failure behavior, symlink/path rejection,
optional package-unit availability, enabled/disabled/enabled republication, and
the unchanged original workload hash fixture. Dash and BusyBox agree.

The home installation test executes the original complete home-copy shell body
in a disposable chroot. It checks account ownership, private file/directory
permissions, rendered compositor policy and sensitive-unit drop-ins. Global
vendor-user policy staging uses the real publisher with an explicitly mocked
unit-availability lookup. The unchanged lookup library has its own existing
DBus/systemd tests. The four optional system-workload publishers are also
executed using their original functions with only fetching replaced by local
copies; full network/package installers are not executed.

36 synthetic service/slice/socket fragments are checked in each I/O mode, using
the real drop-in files. Offline `systemd --user --test` runs under UID 65534 and
checks loaded class ancestry, compositor and audio weights, sensitive-process
soft/hard LimitCORE values, prefix matching with a negative control, and socket
MaxConnections. No target service is started. There are 38 unit-policy drop-ins
in the fixture set; the one scope policy is structurally checked separately
because a scope requires runtime/API creation. This test is not a claim of live
transient-service/scope activation on systemd 261.2.

The original scope regression test was updated to expect exactly two files: the
unchanged lifecycle policy and the new class-only policy. Its original lifecycle
assertions remain. No baseline failures were hidden by weakening those tests.

## Publishing and source checks

* Shell syntax: **277 files, 565 parser checks, all passed**.
* Preseed validation: **59 files passed**; all four generated command values
  survived private debconf read-back unchanged.
* Publishing: **1,330 payload files**; two builds produced identical payload,
  manifest and preseed bytes. The build freshness check passed.
* The three regenerated publishing files have their original archive modes
  restored after building. Other original files retain their original modes.
* GitOps production files are unchanged from R2; current GitOps and managed Git
  tests were rerun successfully (one dependency-related skip).

The exact content/mode comparisons and final extracted-archive verification are
recorded in `docs/resource-refinements-r3-scope.json` and the separately delivered
`ARCHIVE-VERIFICATION-R3-20260916.json`. The latter is produced after packaging
and cannot include its own archive hash inside that archive.

## Unresolved baseline cases

`test_desktop_sandbox` has one failing incident-evidence assertion: the expected
incident file is absent from the original archive. Its other 68 cases pass and
one is skipped. The identical missing-file failure is reproduced on the original.

`test_managed_external_software` has four failures because Perl `Moo.pm` is not
installed in this container. Those same cases fail on the original for the same
missing dependency; two other tests pass. No substitute or stub Moo module was
introduced to manufacture a successful result.

`test_podman_incus_redesign` has one existing mock error in
`test_terminal_launch_is_argv_only`: the mocked subprocess result does not supply
the two values expected by `subprocess.run`. The same error reproduces on the
original; its other 87 tests pass. Production Podman code is unchanged.

These are recorded limitations, not evidence that those production features
were end-to-end validated. Raw results and original-archive baseline logs are
in `docs/validation-resource-r3/`.

## Reproduce focused checks

```sh
python3 -B -m unittest discover -s d-i/forky/tests -p 'test_systemd_resource_policy.py' -v
python3 -B -m unittest discover -s d-i/forky/tests -p 'test_systemd_resource_refinements.py' -v
python3 -B -m unittest discover -s d-i/forky/tests -p 'test_gitops_mirrors.py' -v
python3 -B tools/build.py --check
python3 -B tools/check_shells.py
python3 -B tools/check_preseeds.py
```

Root is required only for the disposable-chroot and UID-isolated offline checks;
tests that require those capabilities declare skips when unavailable. Actual
post-installation inspection commands are in `RESOURCE-POLICY-REFINEMENTS-R3.md`.
