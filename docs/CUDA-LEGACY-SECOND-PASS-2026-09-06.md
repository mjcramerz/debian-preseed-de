> Historical report, superseded by [the 2026-09-07 repair](INSTALLER-HARDENING-2026-09-07.md).
> Its TLS/CUDA exceptions, hook ordering and validation counts are NOT current instructions.

# CUDA-legacy and Podman/Incus second pass

Date: 2026-09-06. Input: the complete first-pass `debian-preseed-de-refactored.tar.gz`.
This is a replacement source snapshot, not a patch or an installed-system updater.

## Resolved CUDA failure

The old path performed a strict APT update before a narrow SHA-1 certificate
fallback. That fallback required `/usr/share/apt/default-sequoia.config`, generated
a temporary policy, constrained a signing fingerprint, and expired on 2027-02-01.
Those prerequisites conflicted with the requested unauthenticated legacy source
and explain the reported strict-policy/missing-policy-file failure path. The
actual failed installer log/image was not supplied; the source path was traced
and its replacement exercised with real APT and offline repositories.

The new path has no strict-first update, mandatory signing-key fetch, Signed-By
pin, generated Sequoia policy, dependency on a policy file, or crypto deadline.
The source is exactly:

```text
deb [arch=amd64 trusted=yes allow-insecure=yes allow-weak=yes allow-downgrade-to-insecure=yes check-valid-until=no check-date=no] https://developer.download.nvidia.com/compute/cuda/repos/debian12/x86_64/ /
```

These options belong to this source only. The renderer rejects other origins,
suites and components rather than letting a caller reuse the exception elsewhere.
The isolated refresh removes inherited `APT_SEQUOIA_CRYPTO_POLICY` and
`SEQUOIA_CRYPTO_POLICY` environment overrides for that process. Nothing writes a
system-wide crypto policy or enables global unauthenticated installs.

APT can still invoke its verifier and emit warnings: the change removes signature
authentication as an acceptance gate, not all verifier activity. SHA-1 signatures,
unavailable keys and unsigned metadata are tolerated for this source. Source-local
`trusted=yes` also permits noninteractive package acquisition without a global
`--allow-unauthenticated` flag. Network/index errors remain fatal; they are not
converted into apparent success by ignoring the update exit status.

## Class selection and phase ordering

The pre-pkgsel hook stages the exception only when `addon/cuda-legacy` is selected.
The late-command repair path uses the same source renderer/publisher. Unselected
installations do not create the source or invoke its update.

Explicit selection now takes precedence over GPU discovery for this class. A
compiler/build host with no visible NVIDIA PCI device still receives the requested
userspace package selection and repository setup. The existing architecture and
class-dependency rules remain; the archive is intentionally amd64-only. Other
NVIDIA driver/modern-CUDA hardware gates were not relaxed.

All **68 explicitly requested CUDA 12.8/12.9 package names are unchanged**. This
retains both compiler/runtime sets; it does not assert that every version remains
available upstream or that the live dependency solve has been tested.

The existing temporary-source lifecycle is retained:

1. Pre-pkgsel publishes one mode-0644 source atomically before refreshing it. It
   needs neither an external key download nor a Sequoia baseline. Repeated runs
   produce the same source, and failed publication preserves the prior file.
2. Pkgsel installs the selected packages using the source-local trust settings.
   Late-command repair re-stages/refetches its metadata when missing packages
   need installation.
3. General late-command updates temporarily hide this source and keep its cached
   lists. The source is restored even when the general update fails.
4. After repair the temporary source and obsolete dedicated key are removed.
   The existing finish-install normalizer additionally removes legacy-source
   remnants before modernizing APT sources. No permanent insecure NVIDIA source
   is added to installed hosts.

The pre-pkgsel scratch directory defaults to its existing path; the new
`INSTALLER_CUDA_PREPKGSEL_ENV_DIR` override permits isolated hook fixtures.

## Security tradeoff

This is an explicit removal of archive authentication and metadata freshness
checks for the selected legacy source, not a secure cryptographic repair of SHA-1.
HTTPS certificate verification remains enabled, and package bytes are checked
against the available index checksums. These checks do not restore publisher
authentication when the metadata itself is unauthenticated. A compromised origin
or trusted TLS interceptor can provide executable packages to the target.

No Debian or other vendor source receives this exception. A mixed-source real-APT
fixture proves that an ordinary unsigned source still fails; a separate fixture
proves that normal Signed-By validation accepts the correct strong signing key and
rejects the wrong fingerprint. Source authenticity is deliberately not asserted
for CUDA-legacy. The installer snapshot's own checksum verification is unchanged.

## Additional Podman/Incus findings

### Bootstrap access to the service-user bus

`podman-devops-bootstrap.service` previously set `ProtectHome=yes`. Despite the
account home being under `/data/accounts`, that setting also hides `/run/user`,
which the bootstrap needs to connect to the devops user manager. It is now
`ProtectHome=read-only`: filesystem writes remain restricted, but AF_UNIX bus
connections remain possible. `ProtectSystem=strict`, `NoNewPrivileges=yes`,
AF_UNIX-only communication and the lock-directory write exception remain.
A regression test covers the corrected unit. Rendered-unit verification passes,
but no real systemd service start or reboot was possible in this environment.

### Managed client argument handling

The Podman/Docker/Compose wrappers now consume separate-valued global options
before checking subsequent common endpoint selectors. The old scan stopped on
`debug` in `podman --log-level debug --url=... ps`. Equivalent Docker `--config`
and Compose `-f` cases are now handled. Shorthand connection/remote selectors are
also rejected, missing values are diagnosed, and container arguments following
the subcommand remain unchanged. Inherited `DOCKER_TLS` is cleared for the fixed
local Unix socket. This is a convenience/safety guard, not a security boundary
against authorized users who can execute the native clients directly.

The locked `devops:devops` service identity, rootless shared socket, pool layout,
no-sudo desktop access, root-owned authoritative configuration, Fuzzel operations
and restricted Incus authorization design remain. No `podsvc` account provisioning
was reintroduced. Incus reconciliation and conflict-handling were rechecked through
the existing tests; no additional Incus runtime source edit was needed this pass.
All 13 hardware profile files are byte-identical to this pass's input archive.
Historical comparisons with the original ZIP are separately recorded and are not
misrepresented as second-pass edits.

## Executed validation

| Check | Result |
| --- | --- |
| Full repository suite | **401 passed, 0 skipped**; 56.400 seconds |
| CUDA-focused tests | **28 passed**: 16 lifecycle/hook fixtures and 12 real-APT cases |
| Podman/Incus-focused tests | **81 passed**; included in the 401 total |
| Existing security regressions | **26 passed**, including normal strong-signature/wrong-fingerprint APT control |
| Browser currentness | PASS; no browser input/policy changes |
| Generated payload/preseed currentness | PASS; 1,219 payload files |
| Debconf/preseed checks | **58 files passed** |
| Seven rendered container systemd units | Verification passed with dependency/executable fixtures; no activation |
| Audit | No hard audit failures; see classifications below |

The host was Debian 13 (trixie), with APT **3.0.3** and `sqv` **1.3.0**
(Sequoia OpenPGP 2.0.0). Real-APT tests use disposable keys, private state/config,
loopback HTTP and an inert package. Packages are downloaded only, never installed;
no validation-host APT source or package database is changed. An extracted newer
APT can be selected with `CUDA_TEST_APT_ROOT`, but no newer APT binary was tested
here because the container could not reach external package servers.

The real-APT cases cover default-policy rejection of a SHA-1-certified key;
acceptance with the exception; SHA-1 detached/clear signatures; absent keys;
unsigned and weak-hash metadata; expired metadata; authenticated-to-unsigned
transition; repeated updates; a missing inherited crypto-policy path; rejection
of an ordinary unsigned source in a mixed update; missing indexes; and rejection
of corrupted downloaded package bytes. Several cases share a test method.

Audit categories are **404 pass**, **113 structure-pass**,
**475 inventory-only**, **154 blocked-dependency**,
and **2 template-needs-render**. Inventory, missing dependencies
and unrendered templates are not runtime successes. The general systemd audit is
lexical; the separate seven-unit verification is stronger but still not activation.

`validation/summary.json` and its sibling logs are the current full pipeline.
`validation/second-pass/` contains focused evidence and preservation checks.
The initial transition run is retained there and clearly labeled: one obsolete
strict-policy test failed until replaced by the ordinary-repository authentication
control. No failed test was silently skipped. Earlier revision logs are historical.

## Deployment and remaining acceptance

Deploy the complete new tree atomically, including `d-i/forky/preseed.cfg`,
`payload.manifest` and `payload.tar.gz`. They are rebuilt and mutually pinned.
Changing only a served script cannot replace the checksum-pinned snapshot already
cached by a running installer. Start a new test installation from the new entry
point; do not mix files from the two deliveries.

A live unattended install, real NVIDIA metadata/package availability, the complete
CUDA dependency solve, DKMS/module loading, Secure Boot, container execution,
Incus activation, GPU containers and reboot recovery remain untested. No full
CUDA-stack installation or production certification is claimed.

On a disposable installed host, verify the selected package set with `dpkg-query`,
confirm the temporary legacy source is gone after successful finish-install, and
check that ordinary APT sources still retain their own verification policy. Run
`python3 tools/podman-incus-smoke.py --require-incus` as the authorized desktop
user. The tool's default mode is read-only; its documented explicit exercise mode
is a separate acceptance step with an approved digest-pinned image.

## Primary references

- Debian source-local APT security options:
  https://manpages.debian.org/testing/apt/sources.list.5.en.html
- APT archive authentication and insecure-source behavior:
  https://manpages.debian.org/testing/apt/apt-secure.8.en.html
- APT acquisition implementation:
  https://raw.githubusercontent.com/Debian/apt/main/apt-pkg/acquire-item.cc
- systemd ProtectHome and AF_UNIX behavior:
  https://manpages.debian.org/testing/systemd/systemd.exec.5.en.html
- Podman global and remote-client options:
  https://docs.podman.io/en/latest/markdown/podman.1.html
- Docker CLI configuration, precedence and environment:
  https://docs.docker.com/reference/cli/docker/
