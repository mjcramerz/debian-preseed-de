# CUDA-legacy trust exception - R4

## Change and authorization

The operator explicitly requested restoration of insecure/trusted access to the
legacy CUDA archive after reporting `cuda-legacy-apt` rejection caused by SHA-1.
R3 had replaced the previously working exception with a pinned-key Signed-By
requirement. The supplied original installer.log shows the explicitly trusted
CUDA update succeeding; it is not a log of the new R3 failure.

R4 restores the compatibility policy automatically when `addon/cuda-legacy` is
selected. No new boot option or second confirmation is required. The supported
CUDA 12.8/12.9 package list, class requirements, pins and normal CUDA policy are
unchanged. The exception is exactly:

```text
deb [arch=amd64 trusted=yes allow-insecure=yes allow-weak=yes allow-downgrade-to-insecure=yes check-valid-until=no check-date=no] https://developer.download.nvidia.com/compute/cuda/repos/debian12/x86_64/ /
```

## Lifecycle and boundaries

1. Dynamic answer rendering does not expose this source to ordinary apt-setup.
   Its generator defers to the selected pre-pkgsel hook.
2. `91cuda-legacy-apt.sh` calls the shared `installer_cuda_stage_target_source`
   publisher and refreshes only `/etc/apt/sources.list.d/cuda-legacy-temp.list`.
3. No public key is fetched. No fingerprint, GPG or signature acceptance gate
   runs before publication. APT can emit signature diagnostics, but the source
   entry explicitly permits rejection of archive signatures and weak hashes.
4. Pkgsel uses the trusted source for its selected CUDA packages without a global
   unauthenticated-install option. General late refresh hides this temporary
   source while retaining its lists. Late CUDA repair uses the same publisher.
5. The temporary source and any pre-R4 managed keyring are removed after package
   repair and again during finish-install normalization.

Source rendering is restricted to the exact HTTPS archive above and its flat
suite. That restriction and filesystem/symlink checks protect the scope of the
exception; they are not cryptographic acceptance gates. Publication is atomic.
An older managed Signed-By source is replaced without requiring the old key.
Explicit status propagation protects calls made under shell conditionals.
Cleanup preserves the original failure status. Real APT/download failures still
enter the existing terminal-failure lifecycle; errors are not reported as success.
The refresh retains three APT retries and 45-second HTTP/HTTPS I/O timeouts.

## Accepted risk

This intentionally removes archive authentication and metadata freshness
protection for this source. It accepts SHA-1 certificates/signatures, unrecognized
keys, unsigned archives, expired dates and signed-to-unsigned transitions. It is
not evidence that these inputs are authentic. HTTPS verification is still used;
package checksums still detect a payload differing from its index, but that index
is not cryptographically authenticated. A compromised origin or trusted TLS
interceptor can alter both and serve malicious or replayed content.

No global APT or Sequoia policy, no TLS policy, no Debian source and no modern CUDA
source is weakened. Normal-source negative controls are part of the regression
suite. The exception is deliberately temporary rather than left active after
installation.

## Validation

Run `make test-cuda` for lifecycle, publication and real-APT fixtures. The suite
uses private state directories and disposable keys; downloads are inert fixture
packages, never installed on the host. `make test` and `make validate` include
these checks along with all previous bootstrap and debconf regressions.

R4 was tested with Debian 13 APT 3.0.3 and its default installed crypto policy.
The real APT cases cover SHA-1 certificate self-signatures, SHA-1 detached and
clear signatures, unsigned/missing Release metadata, weak hashes, expired/future
metadata, missing/unrelated keys, authenticated-to-unsigned state, successful
package download and repeated update. Ordinary-source controls reject weak,
unsigned and stale metadata and missing/wrong keys; mixed-source checks reject
insecure neighbors. Missing indexes and corrupted packages remain failures.
Current counts and command exit statuses are recorded in ENGINEERING-REPORT.md
and `validation/`.

A live NVIDIA metadata fetch was attempted, but this execution environment could
not resolve developer.download.nvidia.com (curl status 6). Live vendor updates,
full CUDA dependency resolution, package installation and physical boot are not
claimed as passed. The successful loopback tests exercise actual APT rather than
mocking its authentication result.

## Debian documentation

APT documents the source-local Trusted, Allow-Insecure, Allow-Weak,
Allow-Downgrade-To-Insecure, Check-Valid-Until and Check-Date options:

- https://manpages.debian.org/trixie/apt/sources.list.5.en.html
- https://manpages.debian.org/trixie/apt/apt-secure.8.en.html

## Deployment

Deploy the entire release: `preseed.cfg`, `payload.tar.gz`, `payload.manifest`,
canonical helpers and other sources belong together. Their generated hashes are
already rebuilt. Do not mix R3 and R4 files or replace a single helper beneath an
active installer. Start a fresh installation from the published R4 snapshot;
existing terminal-failure markers must not be deleted to force a failed run to
resume.
