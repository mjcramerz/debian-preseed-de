# Engineering delivery report - R4, 2026-09-07

## Outcome

R4 restores the operator-authorized trusted/insecure APT exception for the
explicitly selected CUDA-legacy class. R3 had made the archive's pinned signing
key and the default signature/freshness policy mandatory; that was incompatible
with the requested legacy behavior. No second opt-in flag is required.

This repair is validated with real Debian 13 APT 3.0.3 and loopback repositories,
not just a shell mock. The current recorded command results are in
`validation/release-checks.json` and `validation/summary.json`. No full physical
installation or live NVIDIA package resolution is claimed.

## Executed repository validation

| Command | Result | Elapsed |
|---|---|---|
| `make build` | PASS (exit 0) | 2.225 s |
| `make check` | PASS (exit 0) | 3.788 s |
| `make test` | PASS (exit 0) | 230.89 s |
| `make audit` | PASS (exit 0) | 1.742 s |
| `make validate` | PASS (exit 0) | 242.396 s |

Both complete runs passed **511 tests with zero skips**: `make test` in the working tree and `make validate` from an extracted candidate archive. The 40 CUDA tests include 10 additional tests and updated policy expectations; all 471 non-CUDA tests are unchanged. The 18 bootstrap and 22 debconf regressions are included, not extra counts.

Shell checks passed 264 files/templates and 539 parser checks. The supplemental whole-tree audit parsed 195 shell and 101 Python sources. The repository audit reports 154 dependency-blocked Perl checks separately. These are not passing Perl compilation checks.

## Code changes and integration

- The shared renderer emits trusted=yes, allow-insecure=yes, allow-weak=yes,
  allow-downgrade-to-insecure=yes, check-valid-until=no and check-date=no only for
  the exact NVIDIA Debian 12 x86_64 HTTPS flat archive.
- Removed the CUDA key download and full-fingerprint gate. Old managed keyrings
  are cleanup-only state. Existing R3 Signed-By sources are replaced atomically.
- Pre-pkgsel and late repair continue using the same source publisher; the
  apt-setup generator defers to the explicitly trusted pre-pkgsel refresh.
- Explicit status propagation protects source publication and late preparation
  under shell conditionals. Cleanup retains the original failure and does not
  hide real APT, network or filesystem errors.
- Generated preseed, payload archive and manifest are rebuilt as one release.
  No lifecycle, stdin/debconf transport, storage, GRUB/MOK, Codex, CrowdSec,
  Mullvad, modern CUDA, package-pin or host-profile behavior is otherwise changed.

Exactly three non-generated runtime files differ from R3: scripts/common/lib.sh,
scripts/late/cuda-legacy.sh, and the apt-setup generator 98-cuda-legacy-source.
All 1,234 payload members are checked against their source files and manifest;
all 13 original profiles still match the original ZIP. The CUDA package list
and all non-CUDA test modules are unchanged. Current README, security guide,
operations guide and incident inventory now describe the exception rather than
claiming strict CUDA authentication. R3's report is retained as historical.

## Risk and preserved boundaries

This intentionally accepts weak, unsigned, unrecognized-key and stale metadata
for this one selected archive. It is not cryptographic authentication. A
compromised origin or trusted TLS interceptor can substitute or replay content.
HTTPS verification and APT package/index consistency checks remain enabled;
unauthenticated index checksums cannot prove provenance.

No global AllowInsecureRepositories, AllowUnauthenticated, Sequoia or TLS override
is added. Ordinary Debian/vendor and modern CUDA sources retain their policies.
The exception is temporary and removed after package repair and at finish-install.
See CUDA-LEGACY-TRUST-R4.md and SECURITY.md for exact options and scope.

## Regression evidence

The focused suite contains 40 tests. Real-APT cases accept SHA-1 certificate
self-signatures, SHA-1 detached and clear signatures, unsigned/missing Release
metadata, weak hashes, stale/future metadata, absent/unrelated keys, and a
previously authenticated repository becoming unsigned. Downloads are inert
fixture packages and are never installed on the host.

Strict-source controls reject weak, unsigned and stale metadata and wrong or
missing keys. Mixed-source tests reject a second unsigned or SHA-1 repository;
missing indexes and corrupted packages remain fatal. Lifecycle cases cover
selected/unselected hooks, late repair, repeated source publication, old-source
migration, source scoping, unsafe paths, conditional callers and cleanup status.
Both POSIX sh and BusyBox execute the changed publisher successfully.

The retained bootstrap and debconf protocol suites are included in the full
validation. Test counts refer to one run, not a sum of repeated executions.
Archive verification is performed after packaging; extraction, file hashes,
modes, generated-file checks and focused execution tests are recorded separately.

## Limitations and deployment

A live NVIDIA metadata fetch was attempted but DNS resolution is unavailable in
this environment (curl status 6 for developer.download.nvidia.com). Live vendor
updates, complete CUDA dependency resolution, package installation, physical
UEFI/Secure Boot/NVIDIA boot and first-boot services are not certified by these
loopback and source tests. The exact d-i initrd is not booted here; prior debconf
fixtures use the installed Perl backend, not compiled cdebconf.

ShellCheck and shfmt are not installed. Perl checks blocked by absent dependencies
remain explicitly identified by the repository audit, not counted as passing
compilation. Generated template inventory and systemd lexical checks are not
runtime acceptance proofs.

Publish the complete release together and start with fresh installer state. Do
not mix old preseed/payload files with the new library or delete fatal markers
to resume a failed run. The release does not contain raw supplied logs, private
keys, credentials, caches or temporary test work.
