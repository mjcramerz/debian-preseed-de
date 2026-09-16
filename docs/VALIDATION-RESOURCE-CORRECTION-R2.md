# Validation: resource policy correction, revision 2

Date: 2026-09-16. These results apply to the corrected revision, not the rejected
previous delivery. Logs are under `docs/validation-resource-correction/`.

## Environment and limits

Tests ran in this container with Python 3.13.5, Git 2.47.3, systemd-analyze
257.9, dash, and BusyBox. The target requested by the user is systemd 261.2.
The actual systemd 261.2 manager was **not** executed here. No Debian installer
was booted, no running host's cgroups or managers were changed, and no
GitHub/GitLab authenticated acceptance test was performed. This is not a claim
that the full repository suite passes: the selected suites below were run;
the full aggregate suite was not run for this revision.

## Results

| Suite/check | Outcome | Log |
| --- | --- | --- |
| New resource policy | 16 passed, no skips | `resource-tests.log` |
| GitOps mirror/output | 16 passed | `gitops-mirrors.log` |
| Existing managed Git/debug | 55 passed, 1 skipped | `managed-git-debugsys.log` |
| Repository integrity/profile composition | 10 passed | `repository-integrity.log` |
| Btrfs/profile/locale boundary | 18 passed, 1 skipped | `profile-boundary.log` |
| Configuration safety | 19 passed | `config-safety.log` |
| Hardware/restore/template regressions | 25 passed | `hardware-restore.log` |
| Existing log regressions | 23 passed | `log-regressions.log` |
| Desktop sandbox | 68 passed, 1 failure, 1 skipped | `desktop-sandbox.log` |
| Podman/Incus | 87 passed, 1 error | `podman-incus.log` |
| Shell parsing | 565 checks across 277 files passed | `shell-check.log` |
| Payload/preseed/pin freshness | Passed | `build-check.log` |

The three skipped existing tests require unavailable OpenSSH client binaries,
real btrfs-progs executables, or rsyslogd respectively. No replacement mock is
reported as real validation of those programs.

## What the new resource suite actually exercises

The production POSIX-shell map and literal renderer are invoked for all 13
profiles in both I/O modes (26 profile/mode combinations). Tests cover whole-line
weight omission, exact allowed keys, empty per-class weights, zero-size
metadata-only coredumps, invalid/missing/multiline values, BusyBox/dash agreement,
unknown placeholders, and preservation of old files on failed publication.

Real staging functions are exercised against disposable target roots, including
true/false/true republishing, correct locations/modes, cleanup, symlink escape
rejection, and absent optional services. Original journal defaults must render
byte-identically; alternate size/count values must pass the real updated journal
validator. Sixty-three original workload/configuration files and all 13
original profile prefixes are guarded by original-archive hashes.

Systemd parsing uses 11 synthetic base units per mode: three slices, seven
services, and a user-manager service with the actual new drop-ins. It is a
syntax/section check with systemd-analyze 257.9, not execution of vendor units,
manager configuration loading, or validation of live cgroup behavior.

The actual pre-existing desktop home-copy shell routine is executed in a
disposable chroot for UID/GID 1001, with the class I/O switch false. It verifies
rendered files in the account's home, ownership, 0600 files, and 0700 parent
configuration directories. Unrelated calendar/GPG bootstrap steps are stubbed;
the test does not pretend to install or boot the whole desktop. Temporary
fixtures are deleted afterwards and are not shipped in the archive.

GitOps tests use local Git repositories and provider mocks. They cover previews,
mirror identity, private creation requests, guarded/atomic ref plans, failure
behavior, preserved origin settings, output, and commit fingerprints. They do
not prove authenticated provider permissions or remote branch protection.

## Two failures confirmed against the untouched original

The same broader suites were also run against a separate extraction of the
user's original archive:

1. `test_desktop_sandbox.InstalledFailureRegressionTests.test_apparmor_complain_incident_is_fully_mapped`
   fails `incident.is_file()` because the expected incident fixture is absent.
   The same failure and the rsyslogd skip appear in
   `baseline-desktop-sandbox.log`.
2. `test_podman_incus_redesign.FuzzelTests.test_terminal_launch_is_argv_only`
   errors inside `subprocess.run` because the mocked `Popen.communicate()` return
   cannot be unpacked into stdout/stderr. The same error appears in
   `baseline-podman-incus.log`.

No original test or affected application code was changed to suppress these
results. These two failures are specifically baseline-reproduced; this says
nothing about unexecuted tests elsewhere in the repository.

## Reproduction

Run from the repository root with Python 3.11 or newer. The resource suite's
chroot test requires root privileges in a disposable test environment; without
those prerequisites it reports a skip. Other tests also report unavailable
external prerequisites rather than silently claiming acceptance.

```sh
python3 -B tools/build.py --check
python3 -B -m unittest discover -s d-i/forky/tests -p test_systemd_resource_policy.py -v
python3 -B -m unittest discover -s d-i/forky/tests -p test_gitops_mirrors.py -v
python3 -B -m unittest discover -s d-i/forky/tests -p test_managed_git_debugsys.py -v
python3 -B -m unittest discover -s d-i/forky/tests -p test_repository_integrity.py -v
python3 -B -m unittest discover -s d-i/forky/tests -p test_btrfs_locale_boundary.py -v
python3 -B -m unittest discover -s d-i/forky/tests -p test_config_safety.py -v
python3 -B -m unittest discover -s d-i/forky/tests -p test_hardware_restore.py -v
python3 -B -m unittest discover -s d-i/forky/tests -p test_log_regressions_20260915.py -v
python3 -B -m unittest discover -s d-i/forky/tests -p test_desktop_sandbox.py -v
python3 -B -m unittest discover -s d-i/forky/tests -p test_podman_incus_redesign.py -v
```

## Release checks

The complete archive is separately checked for safe unique paths, file content
and mode equality with the final working tree, preservation of every original
file, and original-file permission equality. The publishing artifacts are
rebuilt through the existing builder and checked again after archive extraction.
The adjacent release verification JSON and SHA-256 file contain the final
archive-specific results. The scope manifest omits its own hash to avoid a
self-reference; final whole-archive hashing covers it as well.
