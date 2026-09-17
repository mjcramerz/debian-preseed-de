# resctl-bench release URL and profile repair

Release date: 17 September 2026.
Base: `debian-preseed-de-2g-4g-package-safe-power-20260917.tar.gz`.

## Reproduced installation blocker

The supplied SHA-256 is a valid 64-character lowercase hexadecimal value and
matches GitHub's published digest for the requested asset. The installer's
`policy()` constructed only the legacy `...-native.tar.gz` URL. It rejected the
new `...-native-aa3786abb93aa646.tar.gz` filename before downloading anything,
and used a combined URL/tag/version/SHA-256 diagnostic. This made the valid
checksum appear to be the problem.

`validation/resctl-release-20260917/policy-reproduction.json` records the same
requested arguments passed to the actual previous and repaired policy methods.
The previous method raises `release URL/tag/version or SHA-256 is invalid`;
the repaired method accepts them. No installer or benchmark was executed in
this reproduction.

There was also profile drift: two profiles already used the requested release;
eleven still selected the older `resctl-bench-v0.0.1-P15s` asset/digest. All
thirteen profiles now contain each of the following settings exactly once:

```sh
RESCTL_BENCH_VERSION="2.2.6"
RESCTL_BENCH_TAG="resctl-bench-v0.0.2-P15s"
RESCTL_BENCH_ARCHITECTURE="amd64"
RESCTL_BENCH_URL="https://github.com/mjcramerz/resctl-bench/releases/download/resctl-bench-v0.0.2-P15s/resctl-bench-2.2.6-x86_64-unknown-linux-gnu-native-aa3786abb93aa646.tar.gz"
RESCTL_BENCH_SHA256="bb132e73ffe5cdf32e205569b8a5cd7e2f52872dae6ffeace57b28337f2d6857"
RESCTL_BENCH_MAXIMUM_BYTES="536870912"
RESCTL_BENCH_MAXIMUM_EXTRACTED_BYTES="2147483648"
RESCTL_BENCH_MAXIMUM_MEMBERS="8192"
```

## Implementation

`d-i/forky/scripts/desktop/resctl-bench-install.py` now accepts the exact HTTPS
GitHub origin/repository/tag/version/architecture path with either the legacy
basename or the upstream `-[0-9a-f]{16}` build-ID suffix. Matching is anchored
to the complete URL. Different origins, userinfo, ports, encoded path aliases,
query strings, fragments, traversal, wrong versions/architectures, and invalid
build-ID lengths/characters are rejected. The build ID is not treated as a
prefix of the archive SHA-256: upstream derives it from the build settings.

Malformed SHA-256 configuration has its own field-specific diagnostic. An
actual downloaded-byte checksum mismatch reports both the expected and
observed digests and stops before unpacking or publishing. The release's
internal `SHA256SUMS` and complete member inventory remain checked. Archive
path, link, special-file, size, member-count, ELF, credential-drop, private
staging, noexec, no-clobber publication, and rollback protections are unchanged.
No check was disabled and no downloaded installer or benchmark is run.

The new `--validate-only` option returns immediately after argument/policy
validation, before root checks, target architecture subprocesses, umask changes,
lock acquisition, temporary files, network access, or installation. Its behavior
was exercised in a real process running as UID/GID 65534 with no supplementary
groups, as well as with unit-test side-effect traps.

`tools/check_resctl_bench.py` is a new offline publishing gate. It reads profile
pins as literal data, never sources shell, rejects missing/duplicate/unknown or
nonliteral assignments, calls the target installer's actual policy, and requires
all eight values to agree across profiles. Both normal build and `--check` run
this gate before generating any products. Regression fixtures demonstrate that
invalid URLs and profile drift leave existing preseed/payload/manifest sentinel
files untouched. This prevents the original error from passing shell syntax
validation and only becoming visible late in an installation.

## Scope and preservation

Every one of the previous release's 2,507 regular-file paths is retained.
Existing source-file modes are unchanged. Eleven profiles needed three value
changes each (tag, URL, digest); the other two already held the requested values.
All thirteen profiles are byte-identical to the previous release outside their
resctl pin lines. The APT publisher's 2 GiB ceiling, retained archive's 4 GiB
ceiling, and package-aware power implementation are unchanged. The resctl
archive and decompression limits remain the smaller explicit values above.

The only changed existing implementation/test/build files are the resctl
installer, its existing pin regression, and the build entry point. README points
to this report. The migration ledger updates only `current_sha256` and appends
to `current_change` for the thirteen profiles: all original `source_sha256`,
migration `destination_sha256`, other record fields, and unrelated records are
preserved. Two current hashes were already stale in the previous release; all
thirteen now match the synchronized profiles. New files provide the publishing
gate, scoped regressions, and this revision's validation evidence. Generated `preseed.cfg`,
`payload.manifest`, and `payload.tar.gz` were rebuilt together. Earlier reports
and evidence remain historical; they are not rewritten as current successes.
`validation/resctl-release-20260917/scope-verification.json` lists all nineteen
changed existing files and verifies scope; `provenance-repair.json` records the
ledger update. There are no profile changes outside the requested resctl pins.

## Verification

The dedicated release suite runs the actual installer definitions, validates
all thirteen profiles, and exercises a synthetic release archive using the exact
requested root-name shape. Its **63 tests completed with no failures or errors;
one existing real-noexec test was skipped** because this container has no
existing noexec `/dev/shm`. Other synthetic compiled-ELF/unprivileged smoke tests
passed. The tests never mount a filesystem or execute the real upstream binary.

The complete repository-integrity module plus the isolated HTTP bootstrap
regression passed **11 tests without skips**, including all profile compositions
and current provenance. The preserved archive/publisher/power-action suites
passed **64 tests without skips**. The first attempt at those 64 tests hit the
container tool's execution deadline; the unmodified, fully rerun suite completed
successfully. Both logs are retained rather than representing the interrupted
attempt as a passing run.

The generated runtime payload has **1,358 members**. Every member's source hash,
manifest hash, type and mode was checked, including exact pins in all thirteen
embedded profiles and the embedded repaired installer. Two builds produced
byte-identical `preseed.cfg`, `payload.manifest`, and `payload.tar.gz`. Preseed
checksum pins match those products. The whole-tree non-executing source audit
reports 175 Python syntax passes and 210 shell syntax passes; inventory-only
entries, unrendered templates, unavailable ShellCheck and Perl dependencies are
not counted as runtime passes.

### Complete final run and baseline comparison

The final whole-tree validator completed without timeouts. Browser generation,
build consistency, preseed checks, and shell parsing all passed. Shell parsing
covered **280 files and 571 parser invocations**. The complete tools suite passed
**179 tests, with 0 skips**.

The main suite completed **1,358 tests**, with
**7 failures, 2 errors, and 28 skips**. It is **not** an all-green result.
The untouched previous release ran **1,335 tests**, with
**17 failures, 2 errors, and 28 skips** in the same environment. Every
remaining failure/error entry was also observed in that baseline; there are no
new final-run failure entries. 10 baseline failure entries were resolved by
this repair. All 2,507 baseline file hashes and modes were rechecked against the
original previous-release tarball after validation to verify it stayed untouched.

The remaining entries consist of missing original AppArmor incident logs,
four managed-software tests blocked by unavailable Moo, an existing hardware
profile enablement expectation, an older scope-drop-in expectation, and a
mock/subprocess error in an unrelated Fuzzel test. The old digest test's name
still refers to a 512 MiB bound; its observed failure here is missing Moo, not
an executed digest assertion. No unrelated production setting was changed to
make those tests appear green. The audit additionally records **156 dependency
blocks and 11 unavailable-tool blocks**; its successful exit code does not
turn those blocked checks into passes.

An initial pre-final run is also retained: it found current-profile provenance
hash drift and one HTTP-bootstrap request-count assertion (six requests versus
five). The ledger was corrected with original hashes/history preserved. That
HTTP test and the entire integrity module passed on an isolated 11-test rerun;
the HTTP test also passed in the final complete run without changing its source,
assertions, or the production bootstrap. The initial result is not silently
replaced by the rerun.

Evidence is under `validation/resctl-release-20260917/`: `baseline/`, `repaired/`
(the initial pre-final run), `final/`, `baseline-comparison.json`, focused logs,
`baseline-integrity.json`, and snapshot/scope/provenance verification. Delivery
checksum, every tar member's hash/mode, and fresh-extraction verification are
provided in the separately delivered `-verification.json`.

Useful repeatable checks, from the extracted repository root:

```sh
python3 -I -B tools/check_resctl_bench.py
python3 -B tools/build.py --check
python3 -B -m unittest discover -v -s d-i/forky/tests -p 'test_resctl_bench*.py'
PYTHONPATH=d-i/forky/tests python3 -B -m unittest -v test_repository_integrity
python3 -B tools/validate.py --output-dir validation/local-rerun --test-timeout 900
```

The last command is a broad check and is expected to expose the inherited
limitations documented above in this container; it is not a promise that the
entire test suite or a physical host installation is green. Validation commands
must be run in a disposable checkout, not an active installation target.

## Upstream evidence and limits

The following official project pages were inspected on 17 September 2026:

- Release: https://github.com/mjcramerz/resctl-bench/releases/tag/resctl-bench-v0.0.2-P15s
- Asset metadata: https://github.com/mjcramerz/resctl-bench/releases/expanded_assets/resctl-bench-v0.0.2-P15s
- Packaging source: https://raw.githubusercontent.com/mjcramerz/resctl-bench/resctl-bench-v0.0.2-P15s/scripts/build.py

GitHub lists the exact requested filename, digest, displayed size of 40.2 MB,
and asset timestamp `2026-09-17T07:42:52Z`. The packaging source generates the
16-hex build identifier from canonical settings and includes it in the package
directory and archive filename. Its regular-file SHA256SUMS format and bin/debug
layout are compatible with the retained validation policy; the new synthetic
archive test exercises the exact requested directory-name shape.

**The binary release was not downloaded or independently rehashed here.** The
container's direct download failed and its curl API attempt could not resolve
GitHub. Metadata/source verification is not byte-level release verification.
The target installer still verifies the downloaded bytes against the requested
full digest before doing anything with the archive.

**No booted Debian unattended installation or actual release-binary execution
was performed.** Real CLI smoke-test regressions use explicitly synthetic,
harmless compiled ELF fixtures. The requested artifact is a native CPU build;
`amd64` alone does not guarantee compatibility with every CPU/loader in the
thirteen hardware profiles. The target's unprivileged `--version` checks remain
mandatory rather than being bypassed. Network/asset availability, actual target
CPU/library compatibility, partitioning, and live service/AppArmor behavior
still require target-host acceptance. This revision does not claim the entire
inherited codebase is failure-free.

## Deployment

Extract the complete delivery into a **new directory**, not over a partially
published release. From its repository root, run the non-installing checks:

```sh
python3 -I -B tools/check_resctl_bench.py
python3 -B tools/build.py --check
```

The preflight should report thirteen identical valid profiles. Publish the
complete built repository through the existing atomic deployment process,
including these matching generated files:

```text
d-i/forky/preseed.cfg
d-i/forky/payload.manifest
d-i/forky/payload.tar.gz
```

Do not deploy only edited `.env` files or the helper: installations consume the
verified snapshot, not arbitrary newly changed server files. Start a **fresh
installer boot** using the matching newly generated preseed. Do not resume a
failed install against a mixed/cached snapshot, clear its fatal-state marker,
turn off checksum validation, or alter the requested digest merely to make a
mismatch disappear.

This repair preserves the existing refusal to overwrite different/unmanaged
installed executables. It is an unattended-install release, not authorization
to replace local files on an already modified host. No resctl benchmark,
resource-policy tuning, or package transaction is started by the publishing
checks above.
