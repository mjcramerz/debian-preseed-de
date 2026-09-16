# Validation - revision 4

Date: 2026-09-16. See RESOURCE-POLICY-APPARMOR-R4.md for the implementation and
research boundaries. This report supersedes the root-level R3 validation report.
All commands operated on a disposable working copy, not on the installed host.

## Results

| Check | Outcome |
| --- | --- |
| Resource policy and systemd refinements | 25 passed |
| New R4 policy/AppArmor checks | 15 passed |
| GitOps mirrors | 16 passed |
| Managed Git/debug helpers | 55 passed, 1 skipped |
| Repository integrity/profile composition | 10 passed |
| Selected regression modules, including the above | 614 tests: 604 passed, 5 failures, 2 errors, 3 skips |
| Repository AppArmor source files | 34 compiled without kernel loading |
| Package-local AppArmor snippets | 13 compiled under synthetic package envelopes |
| Declared repository AppArmor domains | 231; no duplicate names |
| Systemd fixtures | 36 fragments checked in each I/O mode |
| Shell syntax | 277 files, 565 parser checks, passed |
| Preseed | 59 files; generated command read-back passed |
| Publishing payload | 1326 files; two rebuilds byte-identical |
| Original source paths | All 2003 retained with original file modes |

The systemd tests use the production POSIX renderer across all 13 profiles with
I/O enabled and disabled. Tests cover literal omission of all six managed weights,
invalid values, optional-package staging, core-limit prefixes, vendor concurrency
preservation, retained audio placement, application-class panels and the original
private-home copier inside a disposable chroot. The local unprivileged
`systemd --user --test` graph verifies actual loaded fixture properties, including
MaxConnections=16, MaxConnectionsPerSource=8, polling 2s/64, compositor 300/300,
audio CPU 200 and unrelated core-limit preservation. It does not execute services,
create live transient scopes, enforce controller policy or exercise a real socket.

The R4 tests also verify restoration of the documented 150 polling burst, removal
of the obsolete concurrency knob and scope resource catch-all, inherit-only
no_new_privs dispatch, owner-scoped editor metadata, exact read-only peers, and
Edge's negative Workspace boundary. AppArmor compilation is run with -Q and -K:
no policy is loaded and no host cache is modified. The container has no compatible
kernel policy interface; the parser reports cache-interface warnings. Source
compilation and package-envelope syntax do not prove runtime enforcement or the
exact target vendor-profile integration.

## Remaining failures and skips

All seven failing/error cases below were reproduced against the untouched original
ZIP in this same environment. Raw original-baseline and revised logs are retained
under docs/resource-policy-r4/regressions/.

* Four managed-external-software failures require Perl Moo, absent in the
  container. The attempted package-index update timed out; no dependency install
  or target package configuration was changed.
* The desktop-sandbox incident assertion references a missing historical fixture.
  The installed-failures audit comparison separately references missing
  todo/managed/apparmor/apparmor.log. The new user log is a different incident and
  is not substituted for either fixture to manufacture a pass.
* The Podman terminal test has an existing subprocess mock that produces an
  invalid communicate() tuple. Production Podman code remains untouched.

The three skips are an OpenSSH-client integration test, a live filtered D-Bus
proxy test, and rsyslog parsing, each lacking its named validation dependency.
No test expectation was weakened to hide these cases. The earlier profile
integrity failures caused by stale R3 current_sha256 values were fixed by updating
the provenance ledger to the actual new profile content, preserving source hashes.

Two multi-module command wrappers exceeded their outer tool deadline; modules
without a completed result were rerun independently. The final per-module logs
used in the totals all contain unittest completion summaries. The full aggregate
repository suite was not run; the selected 23 modules are enumerated in
selected-regressions-final.json, not represented as every repository test.

## Preservation, publishing and archive checks

74 R3 target paths containing Podman/zram and 3 GitOps target paths
are byte-identical to R3. All original profile content prefixes are retained.
The existing resource tests separately check their protected original workload
fixture. No changed application, service generator or sandbox launcher source is
needed for this revision's configuration fixes.

The final archive is extracted into a second clean directory and compared file
by file for contents and permissions. The extracted tree is then checked with
build.py --check and the 66 focused resource/R4/GitOps/integrity tests. The external
ARCHIVE-VERIFICATION-R4-20260916.json records actual results and the archive hash;
it is not inserted into the archive to avoid a circular checksum dependency.
The package includes the full repository, rebuilt payload, manifest and pins.
The scope manifest excludes only its own recursive content digest.

The raw uploaded AppArmor log is not republished. Its SHA-256, complete record
counts and exhaustive family partition are in apparmor-log-triage.json. This is
triage and code review, not a simulated kernel replay of 153879 operations.

## Reproduction

```sh
python3 -B tools/build.py --check
python3 -B tools/check_shells.py
python3 -B tools/check_preseeds.py
cd d-i/forky/tests
python3 -B -m unittest test_systemd_resource_policy test_systemd_resource_refinements test_policy_review_20260916 test_gitops_mirrors test_repository_integrity -v
```

Systemd 257.9 and AppArmor parser 4.1.0 were available. No booted installer,
261.2 manager, kernel-enforced AppArmor session, authenticated GitHub/GitLab
acceptance test, crash flood, NVMe weight benchmark, realtime-audio test or live
logout/lock sequence was executed. The implementation report provides acceptance
checks for the intended installed system.
