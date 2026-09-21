# R2: late-command Debconf target-boundary repair

## Scope and acceptance status

This release starts from the complete previously delivered
`debian-preseed-de-fixed-20260919.tar.gz`. It repairs the live installer-to-target
execution boundary; it does not redesign the desktop, storage layout, package
selection, profile policy or security policy. The existing native Fuzzel icons,
Computer Management / Hardware Tuning integration and atomic environment
publication are retained.

The reported failure has an isolated reproducer and regression coverage. The
corrected bridge also executes the native IOCost metadata transaction for the
reported `btrfs-de-flex-duo` profile. This is not a claim that a booted unattended
installation or every hardware and package combination has been accepted. See
`late-command-debconf-r2-validation-20260919.md` for measured results and limits.

## What the supplied logs establish

The installation log records successful storage-layout completion, pre-pkgsel
Secure Boot preparation and entry into late-command. At 2026-09-19 21:58:23 UTC,
late-command reports a completed fetch of the profile, identity, runtime,
layout, filesystem-specific layout and boot fragments. It then stops logging.
The syslog records an in-target mtab-symlink warning at 21:58:32, followed only by
rescue terminal starts several minutes later. It contains no late-command exit
status or shell trace at this point.

The mtab warning is not the failure: Debian's chroot setup emits it immediately
before its Debconf queries. It is also present during earlier successful target
commands in the same syslog. Reformatting storage, suppressing the warning,
disabling IOCost or retrying environment downloads would not repair the
reproduced fault. The raw logs are not copied into this repository, because they
contain host, disk and network identifiers.

## Reproduced root cause

Before this repair, `scripts/common/target.sh::target_exec` cleared
`DEBCONF_REDIR` and other installer Debconf state **before** invoking Debian's
`in-target`. But `in-target` first sources `/lib/chroot-setup.sh`, which runs
`debconf-get` in a command substitution to retrieve `mirror/protocol`.

The live frontend was still present (`DEBIAN_HAS_FRONTEND`), but its shell
redirection marker had disappeared. Sourcing the shell confmodule therefore
reinitialized FD 3 from the command substitution's stdout, rather than retaining
the established frontend request descriptor. The GET request went into the
capture pipe; the client waited on the frontend reply stream for a request that
the frontend never received. The target command did not start.

The unmodified incoming code reproduced that condition in an isolated frontend
test: setup reached the mtab boundary, zero requests reached the frontend, and no
target-command marker appeared before the test's deadline. The test harness
terminated the stalled process group. Its recorded negative status is the
harness's cleanup, **not** an exit status observed in the user's installation.
A retained negative-control test reintroduces the single premature unset and
continues to detect the same deadlock after this repair.

A second connected defect would remain if only the unset were moved. Logging
wrappers intentionally run target commands with stdin connected to `/dev/null`;
other helpers use file loops and pipelines. Debian's installer-side setup and
its target-side Debconf passthrough need a separate, live reply stream. Leaving
these channels coupled either loses the setup replies or feeds data records to
Debconf. The repair addresses both sides of this same boundary.

## Narrow production changes

### 1. Preserve the frontend reply stream at phase entry

`scripts/common/lifecycle.sh::installer_lifecycle_arm` initializes the shell
confmodule before logging redirections, then preserves frontend input on FD 8.
The exported `INSTALLER_DEBCONF_STDIN_SAVED=1` marker records ownership across
nested phase helpers. Rearming validates the inherited descriptor rather than
recapturing a redirected stdin. An occupied unowned FD 8, an invalid marker, or
a missing inherited stream fails closed through the lifecycle failure handler.

Existing d-i descriptors 3-6 remain untouched. FD 7 is already used by record
readers; FD 9 remains a launch-local descriptor. This is not a new database
writer or a fallback to a second Debconf frontend.

### 2. Separate installer protocol input from target data input

`scripts/common/target.sh::target_exec` retains live installer Debconf state
through `in-target` setup. It requires a valid saved input descriptor, request
descriptor and redirection marker before entering the bridge. Invalid state
returns status 125 with a fixed diagnostic, without printing arguments,
selections, passwords or raw protocol replies.

In the existing subshell-scoped execution function:

```text
phase entry:     frontend replies -> FD 8 (saved once)
per target call: command data stdin -> FD 9 (temporary)
in-target setup: stdin <- FD 8; request output -> FD 3
actual target:   stdin <- FD 9; FD 9 closed after restoration
                DEBCONF_READFD=8; DEBCONF_WRITEFD=3
```

The target command is wrapped by a fixed literal `/bin/sh -c` program and passed
as positional arguments. Arguments are never interpolated into shell source.
The caller's descriptors and environment are unaffected because `target_exec`
is a subshell. The target boundary removes installer-only Debconf overrides;
`in-target`'s `DEBIAN_FRONTEND=passthrough`, priority and proxy remain available.
Installer commands still run in locale C and target commands in C.UTF-8.

The normal Debian setup, chroot, cleanup and child-exit-status path remains in
use. There is no raw-chroot bypass for a live /target installation, no ignored
failure, no new broad timeout around package configuration, and no privilege
or AppArmor relaxation. Non-frontend and alternate-root execution are retained.

### 3. Restore protocol input for explicit Debconf operations

`scripts/common/debconf.sh` restores saved frontend input inside its subshells
before a protocol request or filename-based `debconf-set-selections` operation.
This protects calls made inside redirected class-helper loops and pipelines.
Existing validation, private failure diagnostics, secret-safe errors and
standalone non-d-i behavior remain in place.

## Generated artifacts and unchanged functionality

The build embeds the canonical lifecycle and Debconf helpers into
`scripts/common/source.sh`, `scripts/common/lib.sh` and
`scripts/runtime/common.sh`. It regenerates `preseed.cfg`, `payload.manifest`
and `payload.tar.gz` as one consistent set. Hand-editing just a downloaded
helper would leave stale bootstrap hashes and is not the release procedure.

Only three canonical production files are edited. The existing locale-boundary
test is corrected: it previously required the premature installer-side Debconf
unset, thereby asserting the behavior responsible for this deadlock. New tests
exercise the real shell clients and a duplex frontend instead of relying on a
stub that merely captures the arguments passed to in-target. One existing HTTP
transport test module also has the fixture correction described below; this
does not change the production downloader.

All prior repository files are retained. Except for the three canonical helpers,
three generated embedded copies, three delivery artifacts and two existing
test modules, incoming file contents are unchanged. Native menu mappings, Hardware
Tuning routing, AppArmor rules, host profiles, package and browser pins, storage
and Secure Boot policies are not edited. File-by-file preservation and payload
integrity evidence are included with the validation results.

## Regression coverage

The new `tests/test_target_debconf_boundary.py` has 22 test methods. Coverage
includes the old-code negative control, BusyBox ash and dash, raw and initialized
frontends, all five noninteractive target wrappers, captured stdout, explicit
and piped data stdin, literal metacharacter arguments, nested supervised/bounded
helpers, record loops, answer publication, parent-FD preservation, missing-FD
and collision rejection, and cleanup with the original failure status retained.

It additionally runs the installed Perl Debconf Passthrough frontend over the
saved descriptor while target stdin is closed, executes native `systemd-hwdb`,
and performs the complete native IOCost **metadata** staging/publication
transaction using the reported profile's values. It does not calibrate a disk
or change a live device, cgroup, mount, service or package.

The installer and /target are separate disposable chroots. The Debian
`in-target`, `debconf-get` and shell confmodule clients are used with a private
installed Perl Debconf File-driver backend. The chroot-setup fixture explicitly
retains only the protocol/locale/environment sequence; mount preparation and
package diversions are replaced with harmless markers. Compiled d-i log-output
is represented by a descriptor-preserving shim; its inherited-descriptor
behavior was checked against upstream log-output and libdebian-installer code.
These limits are intentional and are not equivalent to booted d-i acceptance.

## Native package-configuration supplements

The retained `validation/late-command-r2-20260919/maintainer-frontend.py` harness
also invokes the installed native `/usr/share/debconf/frontend`, which drives a
real target shell confmodule over a private Debconf database. It checks protocol
capability negotiation, GET/SET/GET round trips and database persistence.

`apt-maintainer-transaction.py` goes through native apt-get and dpkg to install
one generated dependency-free test package into a disposable target chroot.
Its real postinst uses the native Perl Debconf frontend and shell confmodule;
the harness verifies package configuration and the saved target database. It
uses the repository's explicit noninteractive package invocation, including
`DEBIAN_FRONTEND=noninteractive` and `DPkg::Use-Pty=0`. This deliberately does not
claim that arbitrary interactive apt invocations preserve extra descriptors.
No host or production packages are installed, and the synthetic package needs
no network downloads. These supplements do not run the production package set
or d-i's real mount/diversion lifecycle.

## HTTP test-fixture race resolved without changing download policy

The first full validation run encountered the old strict short-URL request-count
failure: six HTTP requests instead of five. Subsequent instrumented runs traced
it to the local test server, not duplicate snapshot fetches. Its HTTP/1.0 302
response closed the connection without explicit close framing. Wget sometimes
reused that closing connection for the redirect destination, received no data,
and returned status 4. The existing production retry correctly repeated the
short-URL request and then completed the bootstrap. Each source, manifest and
payload request still occurred once.

The test endpoint now declares `Content-Length: 0` and `Connection: close` and
explicitly closes the connection. A new regression test checks that response
contract. The aggregate five-request assertion is retained, with per-path
counts added to its failure message; no threshold is relaxed and no production
retry, cache or transport logic is changed. All 24 post-correction bootstrap
probe runs returned success and exactly five requests. The raw failed-run
record and instrumented connection-race evidence are retained.

There are therefore 23 added test methods in this release: 22 target-boundary
methods and one HTTP response-framing method. The repeated probes and native
package supplements are reported separately, not added to the unittest count.

## Upstream references reviewed

- Debian installer utilities 1.155, `in-target`:
  https://sources.debian.org/src/debian-installer-utils/1.155/in-target/
- Debian installer utilities 1.155, `debconf-get`:
  https://sources.debian.org/src/debian-installer-utils/1.155/debconf-get/
- Debian installer utilities 1.155, `chroot-setup.sh`:
  https://sources.debian.org/src/debian-installer-utils/1.155/chroot-setup.sh/
- Debian installer utilities 1.155, `log-output.c`:
  https://sources.debian.org/src/debian-installer-utils/1.155/log-output.c/
- libdebian-installer 0.125, `src/exec.c` (child execution and inherited FDs):
  https://sources.debian.org/src/libdebian-installer/0.125/src/exec.c/

Fixture provenance, licensing, the reduced fixture's scope and local checksums
are documented in `tests/fixtures/debian-in-target/README.md`. The local fixture
checksums are not presented as upstream signatures. The syslog records version
1.155 for `di-utils-mapdevfs`; it does not separately enumerate the in-target
binary's installed package version.

## Deployment

Verify the release checksum, extract the complete repository, and publish the
whole served tree atomically. Do not combine an older preseed, helper cache or
payload with the rebuilt manifest. Start a fresh installer boot against the
newly published preseed rather than resuming the stalled process with cached
bootstrap code. The storage behavior is unchanged: a fresh unattended install
still performs the actions prescribed by the selected storage profile.
