# Engineering delivery report - 2026-09-07

The supplied repository was modified and its executable validation entrypoints
completed successfully. It is a tested repair candidate, not a claim of completed
physical-machine, firmware or live-vendor acceptance. All 13 supplied profile
files are byte-for-byte unchanged; architecture/class logic was repaired around
them. See CHANGE-MANIFEST.json for changed source hashes and source provenance.

## Observed validation

| Command | Result | Elapsed |
|---|---|---|
| `make build` | PASS | 2.291 s |
| `make check` | PASS | 2.235 s |
| `make test` | PASS | 68.068 s |
| `make audit` | PASS | 1.950 s |
| `make validate` | PASS | 74.205 s |
| `whole-tree syntax/security inventory` | PASS | 1.721 s |

One complete suite contains **461 tests**, **0 skipped.
Both standalone make test and the independent make validate run completed.
They are not added together as distinct tests. The untouched baseline contained
410 tests and failed one stale profile-provenance assertion. Baseline build/check
and audit completed; baseline validate failed the same assertion.

The repository audit covered 1161 files and reported:
`{"blocked-dependency": 154, "inventory-only": 476, "pass": 414, "structure-pass": 115, "template-needs-render": 2}`.
A blocked dependency is NOT a pass. The supplemental whole-tree pass checked
190 shell files (POSIX and BusyBox parsers)
and 97 Python sources (AST syntax).
ShellCheck and shfmt executables were unavailable. Remaining data/configuration
and template inventories are identified separately, not represented as runtime
validation. No physical disks were partitioned in this environment.

## Material repairs

Non-returning fatal supervision prevents d-i late/finish re-entry and freezes the
actual main-menu ancestor. Atomic first-failure and explicit completion records
replace ambiguous error-only return paths. The implementation uses udeb-available
applets, not desktop-only stat/setsid/timeout. The finish hooks validate the target
before unmount, with a separate guarded final exit-11 success handoff.

Independent late shells and explicitly checked conditional helper calls propagate
failure. GRUB architecture policy initializes required MOK/removable EFI paths
before any renderer. Codex runtime links and immutable/mutable state policy agree;
validated publication is transactional and rollback is scoped to newly created
components. The base APT boundary removes CD-ROM sources before its first update.
CrowdSec configuration precedes bouncer installation and the package-generated
API key is authenticated on first boot. Mullvad profile provenance/offline parsing
is required, with actual AppArmor load deferred to a mandatory runtime unit.

Legacy CUDA now requires signed metadata and a full pinned key fingerprint. TLS
bypass requests are rejected. Disk selection protects mounted/removable/hd-media
devices and ambiguous choices, and keeps 4Kn capacity units correct. Generic
arm64 CPU detection no longer requires an x86 vendor. Kernel/initrd repair precedes
final GRUB generation, including missing initrds for unchanged Debian-signed
kernels. Final PE checks require a signature record rather than a zero listing
exit alone. Virtual package providers no longer trigger false package repairs.

## Evidence and limitations

INCIDENT-2026-09-07.md maps meaningful supplied log findings to fixes and identifies
benign/chroot diagnostics. INSTALLER-HARDENING-2026-09-07.md documents actual
lifecycle, markers, retry/rerun behavior, storage, trust, MOK and recovery rules.
SECURITY.md supersedes the earlier CUDA/TLS exception policy.

No full d-i boot, target package transaction against current public repositories,
real Secure Boot/MOK enrollment, NVIDIA/DKMS boot, first-boot CrowdSec/Mullvad,
or graphical session acceptance was performed. Those require the deployment
image and hardware. Missing Perl dependencies block 154 compile checks; they are
listed in the audit rather than hidden. Mixed-suite policy remains intentional;
the source payload is pinned, but all online packages are not version-locked.

Raw supplied logs, intermediate work, .git, caches, private credentials and prior
validation transcripts are excluded. The release retains structured validation
results; rerunning validation regenerates detailed logs.
