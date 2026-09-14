# Implementation and validation record

Date: 14 September 2026. Repository: `debian-preseed-de`.

## Delivery status

The four requested changes are implemented in the delivered source: managed Git
SSH/GPG provisioning and desktop agent integration; protected-path GitOps;
SSH-based Codex home on tracking branch `mcr/main`; and the root `debugsys`
collector with explicitly armed/removable initramfs capture.

The tarball is the COMPLETE codebase, not a patch. All 1642 original
regular files remain present. The scoped source inventory records 43
modified files and 22 added files, plus the validation records in this
directory. Generated payload, manifest and preseed hashes are synchronized.
Private deployment keys and `/preseed.env` are not included. The local inspection
`.git` database and interpreter caches are not distribution assets.

No application or system component was compiled. `tools/build.py` regenerates
repository payloads and hashes; it is not a software compilation step.

Read `docs/MANAGED-GIT-DEBUGSYS-20260914.md` for the exact installation inputs,
all 28 aliases, protection semantics, 12-entry menu, rollback and live acceptance.
The same guide is installed at `/usr/local/share/doc/managed-git/README.md`.

## Results on the final source snapshot

| Check | Result |
| --- | --- |
| Browser asset consistency | PASS |
| `tools/build.py --check` | PASS |
| Preseed consistency | PASS |
| Shell parser checks | PASS; see `release-validation/shell-check.json` |
| Focused new managed Git/debugsys suite | 56 tests, OK with 1 explicit skip |
| Focused Codex installer/session suite | 22 tests, OK |
| Focused installer hardening suite | 56 tests, OK |
| Full repository unit suite | 838 tests; FAILED (failures=5, errors=2, skipped=25) |
| Original ZIP comparison | 782 tests; FAILED (failures=18, errors=2, skipped=24) |
| New failing test identifiers versus original ZIP | None |
| Repository audit stage | PASS as a structural/inventory audit, not runtime acceptance |
| AppArmor source parser | Exit 0; syntax only, kernel policy not loaded |
| New boot-report systemd unit verification | Exit 0; no actual service activation |
| Desktop SSH unit verification | BLOCKED: vendor socket and installed helper paths absent in this container |
| Real read-only debugsys smoke | 33 evidence records; all hashes and modes verified |
| `git diff --check` | PASS before packaging |

The full validation driver intentionally reports `success: false`: remaining
failures have NOT been hidden, skipped, or converted into success. The detailed
logs and JSON summaries are included. Some unittest subtests repeat scenarios;
counts above are runner counts, not distinct end-to-end deployment scenarios.

The new suite exercises actual Git trees/commits and actual GPG encryption and
decryption with temporary fixtures. It also tests policy parsing, protected
local absence/content, deletion and file/directory collisions, preview/index
preservation, branch-chain behavior, patch-series handling, installer secret
metadata/rollback, diagnostic bounds, and initramfs transaction/verification
behavior with mocked privileged rebuild operations.

The real OpenSSH agent integration test is the explicit new skip because this
container lacks `ssh-agent`, `ssh-add`, `ssh-keygen` and `ssh`. Mocked orchestration
and static SSH assertions are not proof that a live provider accepts the key.

## Remaining failures, reproduced on the original ZIP

Four managed external-software tests encounter the unavailable Perl `Moo.pm`
dependency in this container. No unrelated package-management implementation
was changed to hide that environment limitation.

Two AppArmor incident-coverage cases fail/error because the supplied repository
does not contain `todo/managed/apparmor/apparmor.log`, the raw fixture required
by those tests. No synthetic evidence was substituted for that missing file.

The existing Fuzzel terminal-launch test errors in its subprocess mock
(`ValueError: not enough values to unpack`). It is unchanged and reproduces on
the original archive.

Thirteen original profile-provenance subtest failures are no longer present:
those same profiles were necessarily edited for the Codex SSH/branch contract,
and their current-content digests were refreshed in `docs/migration-map.json`.
Original provenance digests were retained. No unrelated profile settings were
changed to address the old ledger discrepancy.

Exact remaining failing/error identifiers:

- `ERROR: test_fixture_exactly_matches_the_supplied_raw_audit_events (test_installed_failures_20260911.RecordedAppArmorCoverageTests.test_fixture_exactly_matches_the_supplied_raw_audit_events)`
- `ERROR: test_terminal_launch_is_argv_only (test_podman_incus_redesign.FuzzelTests.test_terminal_launch_is_argv_only)`
- `FAIL: test_apparmor_complain_incident_is_fully_mapped (test_desktop_sandbox.InstalledFailureRegressionTests.test_apparmor_complain_incident_is_fully_mapped)`
- `FAIL: test_chatgpt_forbidden_installed_dependencies_fail_postinstall (test_managed_external_software.ManagedExternalSoftwareTests.test_chatgpt_forbidden_installed_dependencies_fail_postinstall)`
- `FAIL: test_chatgpt_repacked_depends_excludes_x11_xwayland_and_nvidia (test_managed_external_software.ManagedExternalSoftwareTests.test_chatgpt_repacked_depends_excludes_x11_xwayland_and_nvidia)`
- `FAIL: test_repository_failure_is_reported_for_every_managed_deb (test_managed_external_software.ManagedExternalSoftwareTests.test_repository_failure_is_reported_for_every_managed_deb)`
- `FAIL: test_repository_package_digest_uses_the_512_mib_streaming_bound (test_managed_external_software.ManagedExternalSoftwareTests.test_repository_package_digest_uses_the_512_mib_streaming_bound)`

## Smoke-test limits and privacy

The actual collector ran read-only `system` and `credentials` collection as uid 0
inside this container, with a temporary report root. It produced 72592
bytes of evidence, checked each manifest hash/size and verified 0600 files/0700
directories. Missing services/tools and the absent desktop session were recorded
as such. No actual installer credentials were provided. Temporary raw evidence
was removed; only its aggregate `debugsys-smoke-summary.json` is delivered.
This did not arm hooks, modify boot images, reboot, tune hardware or authenticate
to a Git hosting provider.

Repository audit entries marked blocked-dependency, blocked-tool, inventory-only
or template-needs-render are not executable runtime passes. Consult the complete
audit and its counters rather than interpreting its stage exit code as a
successful installation or security certification.

## Live acceptance still required

This environment did not perform an unattended Debian install, real GitLab Codex
clone, GitHub/GitLab authentication, Labwc login/logout, cold/warm/cancelled GPG
pinentry flow, AppArmor enforce-mode loader run, or an initramfs rebuild/reboot
cycle. Verify those on a disposable target with the actual private initrd and
package set before fleet deployment. The guide contains the acceptance sequence.

In particular, verify the actual Debian vendor agent unit contract, a shared
mode-0600 `/run/user/UID/openssh_agent` in terminals/devops, agent teardown at
logout, preserved Codex sandbox agent stripping, tracking `mcr/main`, and both
boot-hook enable/remove rebuilds followed by a real boot. Do not weaken host-key
checking or AppArmor rules to bypass a failure.

GitOps protected synchronization is explicit upstream TREE replacement outside
protected paths, not a three-way merge. Review the preview and protect all local
customizations before `--apply`. Initramfs changes are opt-in, carry boot risk,
and keep transaction/recovery records. Backup/orphan images not rebuilt by
`update-initramfs -u -k all` are retained and reported; they can retain old hooks.

## Reproduction

Run from the extracted repository root, with the documented test dependencies:

```sh
python3 -B tools/build.py --check
python3 -B tools/check_shells.py
python3 -B -m unittest discover -s d-i/forky/tests -p test_managed_git_debugsys.py -v
python3 -B -m unittest discover -s d-i/forky/tests -p test_codex_installer_session.py -v
python3 -B -m unittest discover -s d-i/forky/tests -p test_installer_hardening.py -v
python3 -B tools/validate.py --output-dir /tmp/debian-preseed-validation
apparmor_parser -Q -T -I d-i/forky/hooks/target/etc/apparmor.d -I /etc/apparmor.d \
  d-i/forky/hooks/target/etc/apparmor.d/managed-desktop-wrappers
```

These commands do not supply the missing raw incident fixture or dependencies.
A repeated full run in the same environment is expected to report the remaining
failures above. No assertion has been weakened to manufacture a green suite.

## Validated runtime-product hashes

| Product | SHA-256 |
| --- | --- |
| `preseed.cfg` | `bceb62ac08462f8e27d215cdfd8c4b8ea4b8558385d9a7b5a209c261e19f758e` |
| `payload.manifest` | `0560ea8f2f4cad7588a5dac32dd1cf66aa7c809a193bda594d3329e82a7f95be` |
| `payload.tar.gz` | `e5140aa7d59ddc03ec2e3a0dbe14fbac06d3aa9bd9280771e687943eced07b3f` |

`changed-files.json` provides before/after hashes for every scoped source change.
`baseline-comparison.json` provides the machine-readable failure comparison.
`release-validation/summary.json` is the unmodified final driver result.
The external `.sha256` file authenticates the delivered tarball's bytes against
an independently retained digest; it is a checksum, not a signed provenance claim.
