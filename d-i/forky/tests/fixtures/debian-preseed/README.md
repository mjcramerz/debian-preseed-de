# Debian Installer protocol regression fixtures

These are test-only shell source fixtures, not packages installed on a target.
The three `preseed` files were transcribed from Debian source version 1.125
with insignificant whitespace differences; no functional changes were made.
The shell `confmodule` is an exact copy from installed Debian debconf 1.5.91.
Its line 88 is the `return` statement implicated in the reported failure.
`SHA256SUMS` pins the copies used by this test suite, not a vendor signature.

Sources inspected on 2026-09-07:

- https://sources.debian.org/src/preseed/1.125/debconf-set-selections/
- https://sources.debian.org/src/preseed/1.125/preseed.sh/
- https://sources.debian.org/src/preseed/1.125/preseed_command/
- https://sources.debian.org/src/preseed/1.125/debian/copyright/
- https://sources.debian.org/src/debconf/1.5.91/confmodule/

Preseed is GPL-2-or-later (see preseed.COPYRIGHT and GPL-2); confmodule is
BSD-2-Clause (see debconf.COPYRIGHT). Upstream error swallowing is deliberately
retained in these fixtures: the tests must exercise that contract, not an
idealized replacement. Do not copy them over installer system files.

The harness supplies a live stdin/FD-3 socket, saved stdio on FDs 4-6, BusyBox
at every installer /bin/sh boundary, and a real, explicitly private Perl debconf
File-driver backend. The backend is not a compiled cdebconf frontend. The
log-output shim preserves descriptors while capturing child output. The
preseed_fetch shim accepts only local files. Repository HTTP download tests use
loopback. These substitutions and simulated sysfs/architecture data mean this
is protocol/control-flow integration, not a booted installer/hardware test.
