# Retained Debian archive repair - 17 September 2026

## Delivery status

The retained-package size-limit mismatch has been repaired and reproduced passing.
This is a complete source-tree delivery, including regenerated installer products,
not a patch-only delivery. It is **not a certification that the entire repository
or an unattended installation is failure-free**. The full validation results below
include inherited failures and blocked checks; none have been hidden or converted
to passing results.

The supplied error does not identify the actual failed file or its size. That vendor
archive and the failed host were not supplied. The size mismatch is a demonstrated
code defect that produces the reported class of error, rather than a claim to have
inspected the original failing package.

## Root cause and affected execution path

`d-i/forky/scripts/late/software.sh` stages the servicing modules and invokes the
managed-software bootstrap with `--bootstrap-chatgpt`. Its CLI obtains a retained
package from `ExternalSoftware::Servicing::Repository::latest`, which delegates to
`Deb::validate_spec` / `Deb::validate` before installing it.

The Python publisher `hooks/target/usr/local/libexec/local-apt-repository` already
accepts Debian archives up to 1,073,741,824 bytes (1 GiB). The old Perl validator
rejected archives larger than 536,870,912 bytes (512 MiB), including valid archives
that the same repository had legitimately retained. The publisher can rewrite
package metadata and recompress packages; the size of a retained package therefore
need not equal the size of the vendor's downloaded package.

A real, sparse Debian archive of **536,875,008 bytes** was passed through the exact
original validation method and through the repaired method. The original returned
255 with `ChatGPT/Codex Desktop retained archive package is not a bounded regular
file`; the repaired method returned 0 and validated the package metadata. Both runs
used real `dpkg-deb`, not fabricated package metadata or file-size responses. The
harness limitations are documented below and in the JSON evidence.

The same path also contained a filename inconsistency: child-name and catalogue
validation allowed `~`, while absolute-path validation rejected it. A tilde is a
valid Debian version character, so a valid retained package could also be rejected
when its filename contains a prerelease version.

## Scoped implementation

| Component | Change |
| --- | --- |
| `ExternalSoftware/Servicing/ArtifactLimits.pm` | New core-Perl module exports the finite 1 GiB `MAX_DEB_BYTES` ceiling. This is the shared Perl limit; regression tests compare it with the existing Python publisher limit. |
| `Deb.pm` | Uses the shared ceiling, checks the opened descriptor against the initial `lstat`, opens with `O_NOFOLLOW` and `O_NONBLOCK`, retries interrupted header reads, and checks for file changes after metadata inspection. Error messages distinguish inspection, type, size, open and mutation failures. Size errors include the path, observed bytes and allowed range. |
| `Atomic.pm` | Permits explicitly bounded streaming SHA-256 requests up to 1 GiB, while retaining 64 KiB reads and the caller's lower bound. Allows literal `~` in absolute path components; traversal and other unsafe pathname forms remain rejected. |
| `ChatGPT.pm` | Aligns the ChatGPT upstream transfer ceiling with the existing 1 GiB Python downloader/publisher ceiling. |
| `Repository.pm` | Uses the retained-archive ceiling for Bitwarden's retained-object digest. Its separate 512 MiB vendor-source receipt check is deliberately preserved. |
| `scripts/late/software.sh` | Stages the new constant module alongside the existing servicing modules, so an installed helper does not reference a missing dependency. |
| `tools/validate.py` | Adds the previously omitted `tools/tests` suite and a positive, configurable per-suite `--test-timeout` (default 900 seconds instead of a fixed 300). Failures still produce a nonzero exit and `success: false`. |
| `tests/test_retained_package_bounds.py` | Adds 24 executable boundary, malformed-file, pathname, digest and catalogue regressions. No existing test is removed or rewritten. |
| Generated installer products | Rebuilds `preseed.cfg`, `payload.manifest` and `payload.tar.gz` together; they include 1,355 payload files, including the new module. |

This does **not** remove the size ceiling or turn an invalid package into an
accepted package. Archives larger than 1 GiB remain rejected; a future vendor
package above that ceiling would require an explicit, coordinated policy change.
Debian framing, `dpkg-deb` validation, approved package identity, version validation,
`amd64`, existing application payload policy and digest checks remain in place.
The retained-archive limit is deliberately distinct from an application's download
budget because local rewriting may change the archive's size.

The descriptor and end-of-validation identity checks are defense in depth, not a
claim of race-proof access against a privileged adversary. `O_NOFOLLOW` applies to
the final pathname component; external `dpkg-deb` processes still reopen a pathname.
The retained pool must continue to be root-controlled and immutable as designed.
No unrelated ownership model or repository trust policy was changed.

All 2,410 input files are retained. All 13 uploaded profiles are byte-identical.
The 510 input files with AppArmor, systemd, labwc, wlroots, Waybar or Crystal Dock
names/paths are unchanged. No desktop power policy, resource class, hardware tuning
setting, AppArmor rule, mixed-suite APT policy or existing trust exception was
altered to make an unrelated test pass. Historical reports and logs remain intact.
The normal builder changes its three generated products to mode 0644; other
original file modes are preserved.

## Validation actually performed

| Check | Observed result |
| --- | --- |
| New retained-archive regressions | 24 tests; all pass; zero skips. |
| Original versus fixed large-archive reproduction | Same real 536,875,008-byte fixture: original exits 255; fixed exits 0. |
| Browser generated assets | PASS (exit 0). |
| Generated snapshot and pins | PASS (exit 0). |
| Preseed include/layout checks | PASS (exit 0). |
| Shell parsing | PASS (exit 0); 279 files, 569 parser invocations. |
| Main suite | 1,295 tests; 17 failure entries; 2 error entries; 28 skipped. Completed without the old timeout. |
| Tools suite | 179 tests; 3 failure entries; 5 error entries; 0 skipped. Completed without the old timeout. |
| Codebase audit | No hard audit failures reported, but dependencies/tools remain blocked; counts below are not an all-pass runtime result. |
| Payload integrity | 1,355 unique regular members match source and manifest; checksum pins agree; two rebuilds produce identical artifacts. |
| Source preservation | All 2,410 original files retained, all 13 profiles unchanged; only the documented source changes and generated products differ. |

**Overall validation status: FAIL**, correctly recorded as `success: false` in
`full-validation/summary.json`. All current failure/error entries match entries
reproduced on the untouched upload; this comparison does not prove that every
possible new runtime defect has been ruled out.

Audit inventory counts: `blocked-dependency` = 156, `blocked-tool` = 11, `inventory-only` = 495, `pass` = 446, `structure-pass` = 173, `template-needs-render` = 2.
Structure-only, blocked, inventory-only and unrendered-template entries are not
successful target-runtime tests. Failure/error counts above are unittest entries;
subtests can produce multiple entries within a single test method.

Generated product SHA-256 values:

```text
3a246e9d74b04b75ec301bb8f64b3d30790247f9b882b25c4e6754bee290cfee  preseed.cfg
8a9a39aa2ca5ed8dc17a4004b1146439b6ed5158c9db9110fa252fa802b1e39b  payload.manifest
34f96b2967cd4aca4fe1baed5f99b56585c34840ab595939a474ed037aae6812  payload.tar.gz
```

### Boundary regression coverage and its limits

The new suite passes all 24 tests without skips. It exercises a small valid
package, an archive just above 512 MiB, the exact 1 GiB ceiling, and an archive one
byte above that ceiling. It rejects missing/empty/truncated files, symbolic links,
dangling links, FIFOs, directories, invalid magic, framing without valid package
metadata, unexpected package names, incorrect architecture and modification during
metadata validation. It checks tilde-bearing version filenames and rejected unsafe
paths, caller-specific digest limits, catalogue selection, and retained Bitwarden
digest/receipt agreement and disagreement. One test hashes an archive above
512 MiB under a 128 MiB address-space limit to verify streaming rather than loading
the package into memory. Large fixture files are temporary and are not delivered.

These tests evaluate the **actual production Perl method bodies** with core Perl
imports and explicit fixture objects. They isolate the methods from Moo constructor
loading; catalogue transport is fixture-provided. The filesystem operations, byte
counts, SHA-256 work and `dpkg-deb` responses are real. This is meaningful method-level
coverage, not end-to-end execution of the full Moo application. No replacement or
stub Moo implementation was added. Full module-loading checks remain dependent on
the real target dependencies.

The check environment is a Debian 13 container, not a booted forky installer. Moo
and some other audit dependencies/tools are unavailable here. The uploaded desktop
package-selection file already declares `libmoo-perl` and the relevant MooX
packages. An attempt to refresh Debian package indexes failed DNS resolution; no
successful dependency installation or network validation is claimed. Blocked
checks are reported as blocked, not as passing.

No destructive disk operation, actual unattended installation, live vendor package
fetch, target systemd activation, AppArmor enforcement run, or labwc/Waybar/Crystal
Dock GUI/hardware acceptance test was performed. A clean installation result cannot
be inferred from offline checks alone.

### Inherited failures that remain visible

The untouched upload was validated before edits. Its fixed 300-second main-suite
timeout expired; its historical supplied log had already recorded a 377-second
main-suite run. The original tool suite completed with 3 failures and 5 errors.
A second untouched source copy was used to reproduce the relevant failing main
checks independently. The evidence retains both the timed-out baseline and those
focused baseline reruns; it does not mislabel the timed-out baseline as a completed
full pass or fail count.

Known independent issues include missing raw AppArmor incident fixtures
(`todo/apparmor.log` and `todo/managed/apparmor/apparmor.log`), an older test's
expectation that every profile enables hardware tuning despite the uploaded
`btrfs-de-dual-flex.env` disabling it, stale provenance hashes for two untouched
profiles, older resctl-bench tests expecting v0.0.1 release pins while two uploaded
profiles explicitly use v0.0.2, an older scope-drop-in expectation, a fuzzel launcher mock that targets an
old subprocess API, and older power/session tests whose expectations disagree with
the subsequently delivered lifecycle implementation. Four managed-software tests
also fail when they attempt to load the unavailable real Moo dependency. An
unmodified Spotify cancellation test failed in the initial timed-out run but passed
in the focused original-tree rerun; it is recorded as intermittent, not dismissed
as proven harmless.

The provenance ledger was not silently updated to bless differing hashes. Raw
incident evidence was not fabricated. Hardware settings and power lifecycle code
were not changed to satisfy contradictory older expectations. These are unresolved
validation/acceptance items, not claims of repaired runtime behavior. See the final
failure inventory for the exact current results and baseline comparisons.

## Deployment and reproduction

Extract the complete release into a **new** directory. Publish the complete served
repository atomically using the deployment mechanism already in use. Do not overlay
only `Deb.pm`, and do not combine a new `preseed.cfg` with an older payload or
manifest. Keep the rebuilt sources, manifest, payload and preseed checksum pins
together. Retain the previous release separately for rollback.

On a disposable validation host with the repository's declared test dependencies:

```sh
cd debian-preseed-de
python3 -B tools/build.py --check
python3 -B -m unittest discover -v -s d-i/forky/tests -p test_retained_package_bounds.py
python3 -B tools/validate.py --test-timeout 900 --output-dir validation/local-recheck
```

The last command deliberately returns failure while any of the independent checks
above remain unresolved in that host/environment. Review both `tests.log` and
`tools-tests.log`, the summary and blocked audit checks rather than relying on one
passing stage.

A failed installer may already hold an older verified snapshot and a fatal-state
marker. Test the new release with a fresh installer boot and its matching preseed
entry point. Do not disable the fatal-state guard or checksum verification to resume
an old mixed snapshot. Before production rollout, perform an unattended installation
in an appropriate disposable VM, validate the retained package actually involved,
then test the required target services and desktop session on representative
hardware. These deployment acceptance steps were not performed in this repair.

## Evidence map

All new evidence is under `validation/retained-archive-fix-20260917/`:

- `before-after-reproduction.json` and `regressions.log`: original/fixed reproduction
  and the 24 new tests.
- `payload-integrity.json`: every payload member checked against both source and
  manifest, safe unique member paths, matching preseed pins, two identical in-memory
  rebuilds, original-file preservation and unchanged profiles/configuration.
- `full-validation/`: complete current logs, summary and detailed audit inventory.
- `baseline/`: original-tree validation, original tool-suite results, focused
  original-tree failures, and the unsuccessful package-index dependency attempt.
- `failure-inventory.json`: exact current failures and their baseline comparison.
- `source-input-inventory.json`, `change-manifest.json` and `source-changes.patch`:
  input hashes/modes and the scoped source/documentation changes. The patch is a
  convenience only; the release tarball contains the entire repository.

Historical validation elsewhere in the tree belongs to earlier revisions and must
not be interpreted as acceptance evidence for this delivery.

## Primary references checked

- Debian `deb-version(7)` (permitted version characters, including tilde):
  https://manpages.debian.org/trixie/dpkg-dev/deb-version.7.en.html
- Debian `dpkg-deb(1)` (archive inspection and compression behavior):
  https://manpages.debian.org/stable/dpkg/dpkg-deb.1.en.html
- Debian `open(2)` (the scope of `O_NOFOLLOW` and `O_NONBLOCK`):
  https://manpages.debian.org/trixie/manpages-dev/open.2.en.html
- Perl `lstat` and `stat`:
  https://perldoc.perl.org/functions/lstat and https://perldoc.perl.org/functions/stat

Code paths and observed results in this report come from the uploaded source and
the included execution evidence, not from assumptions about a current vendor binary.
