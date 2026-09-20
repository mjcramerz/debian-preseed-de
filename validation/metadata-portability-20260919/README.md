# Metadata portability release qualification

The original missing-command error was reproduced in IOCost line 108. The
credential reader and the complete IOCost stage now run in a restricted
BusyBox environment, including a two-level chroot with no external metadata
program under either installer or target root. Target-side command dependencies
were removed across the complete production tree, not just the failing line.

`make build`, `make check`, `make audit`, all 179 tooling tests, the hardware
integration checker and both modified AppArmor policy parser checks pass.
The 1,647-test full suite and the full `make validate` run retain exactly the
same six failures and two errors as the untouched 1,634-test input archive.
There are 31 skips in each full run. No baseline assertion was suppressed.
See `report.json` for exact identifiers and the complete command results.

The focused suites pass: 11 metadata portability tests, 23 IOCost tests,
12 target-boundary tests and 16 original workload-policy preservation tests.
Every one of the 1,375 payload files agrees with its source bytes and manifest.
The prior 13 profiles and font, Intel, theme and module policies are preserved.

The word `stat` remains in native language APIs, kernel procfs paths, negative
tests and historical evidence. Those are not calls to the missing shell
executable. Security checks and process discovery were not removed or disguised.

This is deterministic static/unit/chroot validation, not a booted hardware
installation. Native Intel HWP writes, real IOCost behavior, PCIe/USB hardware
policy and full desktop acceptance still require the intended target machine.
