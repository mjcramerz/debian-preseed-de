# Validation: managed GPG recipient correction

Date: 2026-09-15. The authoritative full test run used an unchanged source and
payload snapshot. This is not a booted Debian Installer acceptance result.

## Results

| Check | Result |
|---|---|
| Pre-fix reproduction with real GnuPG | The previous sealer reproduces exactly `InstallError: managed GPG key cannot encrypt` with a signing-only key plus a valid desktop key. |
| New recipient/bootstrap/transport regressions | **29 passed; no skips.** |
| Existing managed SSH/GitOps/debugsys suite | **55 passed; 1 OpenSSH availability skip** (56 tests). |
| Complete repository test suite | **930 tests: 898 passed, 5 failures, 2 errors, 25 skips.** |
| Baseline comparison | All seven remaining failing/error identifiers reproduce against the unchanged previous delivery; no additional failing identifiers in the final run. |
| Browser artifact check | Passed. |
| Generated payload, manifest and preseed check | Passed. |
| Preseed checks | **59 files passed**, including actual private debconf read-back of the four generated command values. |
| Shell syntax | **277 files; 565 parser checks passed.** |
| Payload/source comparison | **All 1,286 regular payload members match their source bytes.** |
| AppArmor names/source parsing | Passed for all 34 top-level source files; no policy load or kernel-enforcement claim. |
| Prior missing-stat regression | Passed in a minimal BusyBox chroot containing neither `stat` nor Python. Shared root remains `3770`; private stages are cleaned. |
| Unchanged integration inventory | **239 files compared unchanged**, covering selected host, service, AppArmor, runtime credential and diagnostic integration paths. |
| Complete archive retention and extraction | Recorded in the adjacent verification JSON; all baseline regular files and modes retained, then all extracted files compared to the final tree. |

The focused suites overlap the full suite; they are not extra distinct full-suite
tests. The extracted archive is separately build-checked and its new GPG
regressions are rerun after packaging.

## What the real cryptographic test covers

The test runs the actual target GPG bootstrap shell body and the actual Python
sealer with disposable GnuPG 2.4.7 keys as an unprivileged account. The keyring
contains a signing-only Aptly fixture, an unrelated encryption identity and the
new managed desktop identity. It verifies that the returned fingerprint selects
the desktop key, the ciphertext decrypts after the installer agent has stopped,
Aptly's public identity and private-key availability remain intact, repeat
bootstrap/sealing preserves the desktop fingerprint, and the SSH fixture secret
does not appear in plaintext in the home files.

No deployment key or actual private initrd is used. The test supplies a
`pinentry-qt` presence shim because generation/decryption use explicit loopback
mode; it does not pretend to exercise a graphical pinentry. The crypto tools and
keyring operations are real. The negative parser/recipient tests mock GPG output
to cover revoked, expired, disabled, malformed, mismatched, untrusted and
unavailable/card-only key records, exact subkey selection, encryption failure
and preservation of existing ciphertext. Shell boundary tests run under Dash,
Bash and BusyBox ash, including failure and cleanup paths.

## Remaining full-suite failures/errors

The following are reproduced on the unchanged baseline, not classified as passes:

- Four `test_managed_external_software` failures require unavailable `Moo.pm` in
  this validation container. The installer package list already requests
  `libmoo-perl`; it is not removed or replaced by this patch.
- `test_desktop_sandbox` and `test_installed_failures_20260911` depend on the absent
  original historical AppArmor incident fixture.
- `test_podman_incus_redesign.FuzzelTests.test_terminal_launch_is_argv_only` has the
  existing subprocess-mock error.

Exact identifiers, tracebacks and the comparison are in
`validation/gpg-recipient-fix-20260915/baseline-known-failures.log` and
`baseline-comparison.json`. Neither missing incident data nor a substitute Moo
implementation was fabricated to manufacture a passing suite.

## Audit coverage is not runtime acceptance

The deterministic-path audit inventories 1,214 files. It records 431 syntax/data
passes, 130 systemd structural checks, 485 inventory-only files, 155
blocked-dependency entries, 11 JavaScript checks blocked by tool visibility in its
restricted PATH, and two templates requiring rendered context. The complete
per-file audit is included. A zero audit exit status is not interpreted as all
those files having passed execution. AppArmor's parser reports the container's
missing kernel interface/cache support; source/name parsing exits successfully
without attempting to activate policy.

The container has no OpenSSH executables and is not the booted target desktop.
An optional package-tooling check could not reach the package mirrors (network /
DNS unavailable); no replacement binary, downloaded package or compiled
component was introduced into the repository to work around this. Actual
private GitLab authentication, target GnuPG version acceptance, first boot,
graphical prompts, AppArmor enforcement, systemd service/namespace activation,
power transitions and initramfs reboot acceptance remain live-target items.

## Reproduce

From the extracted repository:

```sh
python3 -B tools/build.py --check
python3 -B -m unittest discover -v -s d-i/forky/tests -p 'test_gpg_recipient_integration.py'
python3 -B -m unittest discover -v -s d-i/forky/tests -p 'test_managed_git_debugsys.py'
python3 -B tools/check_shells.py
python3 -B tools/check_preseeds.py
python3 -B validation/installer-no-stat-fix/minimal-initrd-rootfs-check.py --repository .
python3 -B -m unittest discover -v -s d-i/forky/tests -p 'test_*.py'
```

Run the root-only crypto/chroot tests only in a disposable trusted validation
container with GnuPG, runuser and BusyBox installed. They use fixture data, but
execute trusted installer shell code with privilege.

The separate `reproduce-gpg-conflict.py BASELINE_ROOT` script demonstrates the
old bug against an extracted copy of the previous delivery. It is not a target
repair command and must not be pointed at a customer's live home.

## Evidence and scope

The delivery contains **1,837 regular files**. All **1,807** baseline regular files and their modes are retained; nine existing files changed. The complete prior codebase is retained. Existing implementation changes are
limited to four production files, one operations guide and one existing test
file, plus three regenerated artifacts. One new regression module is added.
Review documents and validation evidence are additional non-runtime files.

The first exploratory full run was interrupted and is not used for these counts:
its supervising tool call ended and the source snapshot was regenerated while
its child was still running. That child was stopped. The authoritative final
run was then completed with the repository unchanged throughout. Its result,
complete log and baseline comparison are the validation basis for this delivery.

No application, library, kernel, systemd, OpenSSH or GnuPG component was compiled
as a fix. Supplied raw installation logs and private inputs are not newly added
to the public repository. The detailed issue dispositions and rollout procedure
are in `GPG-RECIPIENT-INSTALLER-REVIEW-20260915.md`.
