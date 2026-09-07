# Engineering delivery report - R2, 2026-09-07

R2 corrects the startup regression reported against the preceding archive. The
previous suite's 461 passing tests did not exercise every generated bootstrap
shell boundary. This release adds that execution coverage; it is not a claim
that a physical installation has been completed.

## Executed validation

| Command | Result | Elapsed |
|---|---|---|
| `make build` | PASS | 2.529 s |
| `make check` | PASS | 4.650 s |
| `make test` | PASS | 125.480 s |
| `make audit` | PASS | 1.826 s |
| `make validate` | PASS | 134.269 s |

The complete suite ran **479 tests with zero skips**, both as standalone
`make test` and independently inside `make validate`. The separate focused
bootstrap run passed **18 tests**. These repeat executions are not summed as
additional distinct tests. All four generated command values passed real private
debconf write/reload/read-back followed by BusyBox bootstrap execution.

The shell checker passed **259 shell sources/environment files/templates** and
**529 parser checks**, including both nested boundaries of the four generated
preseed commands. The separate release inventory parsed **99 Python sources**
and **190 shell scripts**, with no detected syntax errors. ShellCheck and shfmt
were unavailable and are not represented as executed. The repository audit still
reports **154 dependency-blocked Perl checks**; its success status does not mean
those missing-module checks passed.

## R2 changes

The canonical bounded runner no longer uses shell arithmetic or fractional
sleep. It normalizes decimal durations before launching a child and preserves
command status. The delivered baseline reproduced BusyBox's arithmetic syntax
error for accepted leading-zero values; default `180` succeeded. The exact new
installer environment was not supplied, so that specific input is not asserted
to have been used on the failing machine.

The generated command's newline encoding now survives debconf database reload;
its literal backslash-n sequences had caused GET truncation. Generated values
are checked after actual serialization, not only before it. Timeout cleanup now
expands its trusted /proc fallback even if its caller enabled noglob, preventing
orphaned delayed work. Class detection retains its original failure instead of
losing it in a here-document or formatting pipeline.

Lifecycle source, both embedded libraries, preseed commands, payload and manifest
were rebuilt together with recalculated SHA-256 pins. Build/check/validate now
include the stronger parser and serialization checks. See
BOOTSTRAP-PORTABILITY-R2.md for implementation details, reproducible tests and
limitations.

## Preservation of the preceding repairs

All **13 original profile files** match both the original ZIP and preceding
release byte-for-byte. Of **1,233 runtime payload files**, only the three shared
libraries changed in R2; the other **1,230 files** remain byte-for-byte identical.
No runtime member was added or removed. The prior fatal-hold, GRUB/MOK ordering,
late-failure propagation, Codex transaction, early APT normalization, CrowdSec,
Mullvad, signed CUDA, storage-safety and Secure Boot repairs remain incorporated
and their existing regression tests continue to run in the full suite.

CHANGE-MANIFEST.json records the complete source delta from the original ZIP;
validation/bootstrap-regression.json includes baseline failure measurements and
payload preservation evidence. Current validation/summary.json,
validation/release-checks.json, validation/shell-check.json and
validation/whole-tree.json supersede earlier validation evidence.

## Deployment and remaining acceptance

Publish the complete supplied tree, not an individual replacement script.
preseed.cfg, payload.manifest, payload.tar.gz and source.sh must be from this same
build. Restart the installer from trusted fresh media/preseed after deployment;
do not erase fatal markers to bypass the guard in a failed running installer.

The bootstrap execution tests use a closed chroot with the installed regular
BusyBox executable at every /bin/sh boundary, a restricted applet PATH,
integer-only sleep and loopback downloads. They do not claim to run a particular
busybox-udeb or cdebconf image. No real partitioning, firmware/MOK enrollment,
NVIDIA boot, public package transaction, first-boot service activation or desktop
session acceptance was performed. Those still require the intended installer
image and hardware. Tests do not imply that every online package is pinned.

Raw supplied logs, .git, cache files, private credentials and test runtime data
are excluded from the release. Structured validation evidence is retained;
running validation regenerates its detailed local transcripts.
