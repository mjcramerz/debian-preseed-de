> Historical R3 report. Its strict CUDA policy is superseded by R4; see ENGINEERING-REPORT.md.

# Engineering delivery report - R3, 2026-09-07

## Outcome and validation scope

R3 fixes a regression in the replacement supervision layer. The reported
`debconf-set-selections` status 2 / `return: line 88: illegal number` is reproduced
with the previous launch redirection and removed with the repaired code. The
original uploaded logs predate this failure; they are not presented as a log of
the new installation. This report does not claim that a physical installation
has completed successfully.

| Command | Observed result | Elapsed |
|---|---|---|
| `make build` | PASS (exit 0) | 2.336 s |
| `make check` | PASS (exit 0) | 3.786 s |
| `make test` | PASS (exit 0) | 224.538 s |
| `make audit` | PASS (exit 0) | 1.631 s |
| `make validate` | PASS (exit 0) | 233.027 s |

The complete suite passed **501 tests with zero skips** in each of two recorded
runs: `make validate` in the working tree and `make test` from an independently
extracted candidate tarball. The latter also passed `make check`. These are
repetitions, not 1,002 distinct tests. The release contains **22 new live-debconf
regressions** and retains all **479 existing tests**. The 18 R2 bootstrap tests
are included and still pass.

Shell checks passed **264 sources/environment files/templates**
and **539 parser checks**, including generated command
boundaries. The full-tree audit parsed **101 Python sources** and **195 shell
scripts** without syntax errors. ShellCheck and shfmt were unavailable. The
repository audit reports **154 dependency-blocked Perl checks**; its zero exit
status does not mean those missing-module compilation checks passed. Source
inventories, template counts and systemd structure checks are not runtime proofs.

## Actual cause and repair

`"$@" <&0 &` does not preserve the parent's stdin in a noninteractive shell:
BusyBox and dash install `/dev/null` for the asynchronous list before `<&0`.
The child retained debconf's output descriptor but lost its reply input. The
upstream shell confmodule then tried to return an empty reply status at line 88.
This was not an incorrectly typed numeric answer in the preseed file.

Both canonical launchers now snapshot stdin in the parent on launch-local FD 9,
then start the child with `<&9 9<&-`. Existing FD 9 is restored on return; d-i's
FDs 3-6 are not repurposed. Raw inherited frontend setup happens through the
installed confmodule before repository log redirection. Nested, bounded,
captured, BusyBox and dash calls are executed by the new tests.

The new canonical `scripts/common/debconf.sh` owns live protocol requests and
file-based selection application. The installer shell selector requires a
filename and does not support the installed Perl tool's `-c` interface. Calls
now use private files, do not pipe answer data onto debconf's reply channel, and
do not retry a failed application as an unsupported syntax check. An inherited
frontend is reused rather than competing with another database writer. Runtime
answer iteration uses FD 7 so requests can read replies from stdin.

Protocol replies are validated before being used as exit statuses. EOF and
malformed replies fail explicitly; genuine nonzero statuses propagate unchanged.
Password questions are registered without values before direct protocol SET,
preventing the upstream selector from logging runtime credentials. Literal
backslashes, empty password hashes and seen flags remain correct. Failed
application diagnostics remain private and are not dumped into the main log.
Injected cleanup failures retain the original nonzero error, and failed cleanup
after otherwise successful work is itself a failure.
No repository authentication, TLS, ownership or terminal-failure policy was
weakened; neither the vendor debconf selector nor its shell confmodule is patched
at runtime.

All four generated preseed commands are checked byte-for-byte after loading
through Debian's shell selector and a real private database. Early, partman and
late commands execute via upstream `preseed_command`; include/preseed-run execute
through upstream `preseed.sh`. The generated fatal-detail translation also removes
an unnecessary duplicate replacement space so its command value survives both
backends' whitespace handling. Full upstream include/preseed-run paths now reach
the actual apply phase for local and HTTP bootstraps, Btrfs, simulated arm64/F2FS,
and VM profiles. Failure injection reaches the real terminal hold; completed
apply re-entry performs no second batch of database mutations.

## Integration and preservation

The canonical helpers, their embedded copies, `preseed.cfg`, payload archive,
manifest and SHA-256 pins were rebuilt together. All **1,234 payload files**
were compared against the source tree. All **13 original profiles** still match
the original ZIP byte-for-byte.

Compared with R2, **1,228 runtime files are unchanged**, five existing files
changed and one helper was added. No runtime file or pre-existing test was
removed. The earlier fatal-state, late-family status propagation, GRUB/MOK,
Codex transaction, APT/CD-ROM, CrowdSec, Mullvad, signed CUDA, storage and Secure
Boot repairs remain in the payload and their regressions remain in the suite.
Test-only process cleanup was corrected to freeze a parent before enumerating
children; transport fixtures now explicitly use private debconf databases.

`DEBCONF-TRANSPORT-R3.md` describes the descriptors, tests and operational limits.
`ENGINEERING-REPORT-R2.md` and `BOOTSTRAP-PORTABILITY-R2.md` are historical reports.
Current results are in `validation/release-checks.json`, `summary.json`,
`debconf-regression.json`, `shell-check.json`, `audit.json` and `whole-tree.json`.
`bootstrap-regression.json` is explicitly marked as historical R2 evidence.
`CHANGE-MANIFEST.json` records changes from the original ZIP.

## Deployment, diagnostics and remaining acceptance

Publish the complete release together. Do not mix a new script with old
`preseed.cfg`, `source.sh`, `payload.manifest` or `payload.tar.gz`. Restart with
fresh installer state after publishing the release; do not remove fatal markers
to force a failed installer to continue. Existing diagnostic and success/failure
marker semantics are documented in the operations guide.

The protocol tests use Debian preseed 1.125 shell source fixtures and debconf
1.5.91 confmodule inside a BusyBox chroot. The real backend is the installed Perl
debconf File driver, **not a compiled cdebconf frontend**. log-output and local
preseed_fetch have narrow test replacements. Hardware and destructive phase
children are simulated. Fixture source references, checksums and licenses are
included. The exact deployment initrd, physical partitioning, UEFI/MOK/Secure
Boot, NVIDIA boot, live mixed-suite packages, first-boot services and desktop
session still require image/hardware acceptance. No destructive host-disk test
or live target customization was performed in this environment.

The clean release excludes raw supplied logs, .git, caches, intermediate
artifacts and credentials. Structured validation evidence is retained; detailed
stage logs are regenerated by running validation. The final archive is verified
separately after packaging; the source/runtime file hashes are checked against
this tested tree.
