# Bootstrap portability repair R2 - 2026-09-07

This release replaces `debian-preseed-de-refactored.tar.gz`. It retains the prior
installer repairs and adds execution coverage at the earliest boot boundary.
The preceding 461-test suite passed on the broken release: that suite was not
sufficient evidence for the generated bootstrap. R2 does not represent a completed
physical-machine installation acceptance test.

## Reproduced defects and corrections

The preceding `installer_run_bounded` validated timeout strings with `test` and
then evaluated them using shell arithmetic. `0180` and `08` passed numeric range
checks but failed at arithmetic expansion. Running the actual delivered helper
under BusyBox produced `sh: arithmetic syntax error` and status 2. Dash likewise
rejected those inputs. The ordinary default `180` succeeded in that reproduction.
The new installer invocation's environment and complete error log were not
provided; this reproduction is not proof that its timeout contained a leading
zero. See `validation/bootstrap-regression.json` for the measured baseline cases.

The embedded bootstrap now contains **no shell arithmetic expansion**. Its
private normalizer removes leading zeroes, rejects zero, non-decimal input and
values above 900 before starting any child, and preserves the 45-second read and
180-second per-attempt polling defaults. A finite sequence and integer sleeps
replace arithmetic counters and fractional sleeps. Neither optional `timeout`
nor `setsid` nor `stat` is required. GNU wget's permanent configuration, TLS and
protocol errors stop retries; transient failures remain bounded to three attempts.
A private, atomically published `.fetch-error` records status and attempt count.
The first seed fetch's original status reaches the fatal supervisor.

A second defect was reproduced through the installed Debian debconf 1.5.91
File/RFC822 backend. Serializing and reloading the old generated command changed
literal backslash-n sequences into newlines; an ordinary GET returned only the
first line. Syntax checking the original string could not detect this corruption.
The generator now uses octal LF escapes only in the embedded command, retaining
readable source-file escapes. The shell, printf, awk and tr semantics are checked
by executing the resulting command. All four generated values are written into a
private debconf database and compared byte-for-byte after read-back. This is a
real debconf test, not a claim that a booted cdebconf installer was exercised.

Failure injection also exposed an inherited `set -f` problem: it suppressed the
numeric `/proc` glob used when a kernel does not expose task children. The
private tree-cleanup helper enables globbing for that trusted pattern. Timeout
tests now prove that delayed grandchildren cannot continue after the caller has
returned status 124. No host-wide kill or process-name matching was introduced.

Automatic class detection previously ran inside a here-document substitution,
which discarded its exit status. Its output is now captured with an explicit
status check, class-line formatting preserves failures, and the original detector
failure is recorded before a later missing-class error can obscure it.

## Generated-product contract

`tools/build.py` synchronizes the one canonical lifecycle into `source.sh` and
`lib.sh`, rebuilds the payload and manifest, recalculates transport/payload pins,
and checks all four generated commands at both outer and inner shell boundaries.
The command encoding is a generator concern: do not hand-edit `preseed.cfg`.
The supplied release is already built. Publish the entire `d-i/forky` tree as one
revision, including `preseed.cfg`, `payload.manifest`, and `payload.tar.gz`.
Old initrd/preseed copies containing old pins must not be mixed with this payload.
Start a fresh installer boot after replacing a failed deployment; do not delete
the terminal-failure marker to bypass the existing lifecycle guard.

## Repeatable validation

Build/validation hosts require Python 3.11+, make, Dash, Bash, BusyBox, Debian's
debconf tools and the existing test dependencies. Use a disposable Linux test
host. Root/CAP_SYS_CHROOT is needed for the complete isolated bootstrap tests;
without it those tests explicitly skip rather than pretending to run.

```sh
make build
make check
make test-bootstrap
make test
make audit
make validate
python3 -B tools/release_audit.py
```

`make check` parses shell sources, shell environment files and templates with the
appropriate Dash/BusyBox or Bash parser. Both quoted command boundaries are
checked. `make validate` additionally round-trips the commands through a private
debconf database and runs the full regression suite.

The bootstrap execution sandbox copies the installed BusyBox executable and wget
with their shared libraries. Every nested `/bin/sh` and script shebang resolves
to BusyBox inside that sandbox, unlike a PATH-only test that silently returns to
host Dash. Its restricted applet PATH excludes stat, setsid, timeout and Bash;
sleep accepts integer durations only. The sandbox has no real disks, real /proc,
package manager or destructive disk tools. Network fixtures bind only loopback.
The installed full BusyBox binary is **not** relabeled as busybox-udeb. The exact
installer image, firmware, live repositories and boot-time services still need
acceptance on the intended deployment image/hardware.

Tests exercise HTTP redirects, local media, padded and malformed timeout values,
actual payload verification and class/context preparation, debconf read-back
followed by execution, all generated phase entrypoints, missing-source fatal
hold, original status retention, late re-entry blocking, class-detection failure,
integer-only sleep, and descendant cleanup. Target-customization bodies in phase
entrypoint tests are controlled fixtures; no actual partitioning takes place.

## Evidence

The current results are `validation/summary.json`, `validation/release-checks.json`,
`validation/shell-check.json`, `validation/whole-tree.json`, and
`validation/bootstrap-regression.json`. The audit reports missing Perl modules
as blocked dependencies, not successful compilation. ShellCheck/shfmt and full
physical installer acceptance were not available in this execution environment.
Raw installation logs and test runtime data are not distributed in the archive.
