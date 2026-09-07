# Validation evidence - 2026-09-07 repair

For R3, `make test-debconf` executes Debian's installer shell clients against
an explicitly private live protocol backend. The whole suite includes these
regressions automatically. This is stronger than the R2 host-Perl parser and
prepare-context-only bootstrap tests; see DEBCONF-TRANSPORT-R3.md for boundaries
and substitutions. Current counts and observed statuses are in the R3
ENGINEERING-REPORT.md and validation/release-checks.json. Historical counts below
refer to the original repair, not the current release.

Current machine-readable results are `validation/release-checks.json`,
`validation/summary.json`, `validation/audit.json`, and
`validation/whole-tree.json`. The release report records actual return codes;
blocked dependency checks and source inventories are not runtime passes.

The untouched baseline ran 410 tests with one failing profile-provenance
assertion. Build/check and audit completed; baseline validate also failed that
assertion. The migration ledger now records the correct supplied file hash
without changing that profile. The repaired suite adds fault injection and
regressions for terminal d-i failure, original status retention, early renderer
failure in Btrfs/F2FS/VM, both EFI architectures, Codex publication/ownership,
early APT normalization, signed CUDA metadata, storage media exclusion, kernel
repair and udeb tool availability. No original profile was removed.

Run all entrypoints from the repository root:

```sh
make build
make check
make test
make audit
make validate
python3 -B tools/release_audit.py
```

`make validate` includes the generated browser/preseed/payload checks, the complete
suite, and the repository audit. The separate `make test` and validate test runs
are repetitions, not additive counts. The release report states the count of
unique tests in one run. Test counts inside historical reports apply only to
those earlier revisions.

The full-tree supplemental audit includes every source/document/configuration
file outside `.git` and generated validation evidence. It checks ordinary shell
sources with the POSIX shell and BusyBox syntax parsers and Python with AST
parsing. Template files are identified, not falsely marked rendered. The existing
repository audit includes available Perl compilation checks; absent dependencies
are explicitly BLOCKED. ShellCheck is NOT RUN when its executable is absent.
Systemd lexical or isolated fixture checks do not establish running service
behavior on a real target.

APT tests use private loopback repositories and test keys: they do not install
packages on this host or turn off the host's APT authentication. Storage tests
use private fake sysfs/device files and never format host disks. Process tests
terminate only spawned fixture processes, including a fixture named main-menu.
Actual d-i hooks/packages, physical UEFI/MOK enrollment, NVIDIA/DKMS activation,
first-boot services and live mixed-suite dependency resolution still require
acceptance on the exact deployment image and hardware. See the operations guide.

Raw supplied logs, earlier validation logs and private intermediate diagnostics
are excluded from the release. JSON results are retained; rerunning validation
creates the detailed stage log filenames referenced in `summary.json`.
