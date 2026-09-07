# R3: repair of the live Debian Installer debconf connection

## Incident and reproduced cause

The new report was `preseed-answers debconf-set-selections failed with status 2`
and `/bin/debconf-set-selections: return: line 88: illegal number`. The original
uploaded logs predate this regression; they are not evidence of the new run.

R2's supervisor used `"$@" <&0 &`. Both dash and BusyBox ash replace stdin of an
asynchronous list with `/dev/null` before applying that redirection. Thus `<&0`
duplicated `/dev/null`, not the caller's original descriptor. The child still
inherited the output side of debconf but lost its input side.

The installer shell `debconf-set-selections` sources `confmodule`. Its `db_set`
uses `_db_cmd`, which writes a command on FD 3, reads a reply from stdin and
returns the first reply field as a status. On EOF in the conditional db_set
call, that status is empty. The return at confmodule line 88 consequently emits
the exact reported error and the shell exits with status 2. This is descriptor
loss, not an invalid preseed question or an incorrectly typed numeric answer.

The negative-control regression actually executes Debian's shell selector with
R2's old redirection and observes status 2 and the line-88 diagnostic. The same
selector and connection succeed with the corrected supervisor.

## Descriptor ownership and changes

The canonical `scripts/common/lifecycle.sh` snapshots stdin onto FD 9 in the
parent function redirection, before forking the asynchronous child. The child
uses `<&9 9<&-`. Function return restores the caller's previous FD 9. Both the
supervised and bounded runners use this rule. FDs 3-6 are reserved for d-i and
are never used as scratch descriptors. Nested calls and command substitutions
are exercised by tests, as are BusyBox and dash supervisors.

A raw inherited frontend is initialized through the installed shell confmodule
at lifecycle entry, before repository log redirection. Existing normalized
connections are retained. The implementation does not clear
`DEBIAN_HAS_FRONTEND` to open a second database writer.

New `scripts/common/debconf.sh` owns the shared selection/protocol operations.
The build embeds the same source in `common/lib.sh` and `runtime/common.sh`.
It distinguishes an inherited live frontend from an offline/target-style
invocation. Live requests use stdin and FD 3. Offline requests may use
`debconf-communicate`. EOF, malformed replies and out-of-range status fields
are rejected without returning unvalidated text as a shell status. Nonzero
protocol and subprocess statuses are retained.

The installer shell selector requires a filename and does not implement the
installed system's Perl `--checkonly` interface. Production installer calls now
supply private regular files. Failed selection application is not retried as a
supposed `-c` syntax check, and its original status propagates into the existing
terminal-failure lifecycle. Target-chroot calls to the installed Perl selector
retain its legitimate stdin interface; that is a different execution context.

Runtime answer iteration uses FD 7, leaving stdin available for protocol replies.
Password questions are registered without their values before values are sent
on the live connection, avoiding disclosure in the upstream selector's record
log. Literal trailing backslashes, metacharacters, empty password-hash values
and seen flags are retained. Failed helper diagnostics remain in private
`/tmp/installer-debconf.XXXXXX/stderr` files (0700 directory, 0600 file); their
contents are not printed into the normal installer log. Cleanup preserves an
earlier failure; cleanup failure after otherwise successful work is also fatal.
They remain available
in the installer environment, but are not automatically copied into the target.

The generated fatal-detail character translation uses one replacement space;
this is sufficient to replace CR and LF and survives both protocol backends'
whitespace handling. All four generated commands are compared byte-for-byte
after loading through the installer shell selector. Early, partman and late
commands execute through upstream preseed_command. The include command and
preseed/run execute through upstream preseed.sh in the full bootstrap tests.

## Tests that close the previous coverage gap

Run `make test-debconf` for the focused protocol suite. It is also discovered by
`make test` and `make validate`. Use a disposable Debian build environment with
root/chroot capability, Python 3, BusyBox, dash and the installed debconf tools
(`debconf-set-selections` and `debconf-communicate`). Missing required capabilities
fail the suite rather than silently skipping these regressions. Only a trusted
source tree should be executed. The backend database is explicitly private.

Tests cover:

- The exact old failure, the corrected runners, nested/captured calls, saved
  descriptors and raw main-menu descriptor initialization.
- Debian's actual shell selection parser and include/preseed-run control flow
  connected to a real private debconf database, including local and loopback
  HTTP bootstrap followed by the real apply phase, not only prepare-context.
- Btrfs, simulated arm64/F2FS and VM class/profile application, plus safe apply
  re-entry without a second mutation batch.
- Generated early, partman and late command read-back/execution with live
  protocol traffic. Their expensive/destructive child is replaced by a small
  selection-writing fixture; storage and hardware are never modified.
- A selector failure inside upstream preseed_command reaching the real terminal
  hold, preserving status 37, excluding a success marker and preventing re-entry.
- EOF, malformed/nonnumeric/out-of-range responses, nonzero status preservation,
  symlink rejection, no unsupported retry, private failure diagnostics and
  cleanup that cannot overwrite the first error.
- Literal credentials, trailing backslashes, clearing stale hashes, seen flags,
  absence of password values from the selector log, and canonical-copy equality.

The test harness uses source fixtures from Debian preseed 1.125 and confmodule
from debconf 1.5.91 in an isolated BusyBox chroot. A socket reproduces the
stdin/FD-3 protocol connection and saved FDs 4-6. The backend is the installed
Perl debconf File driver with an explicitly private database, **not a compiled
cdebconf frontend**. log-output and local-file preseed_fetch have narrow test
replacements; architecture and sysfs data are simulated. Fixture provenance,
checksums and licenses are included under `tests/fixtures/debian-preseed`.

Test process cleanup freezes each parent before enumerating descendants; the
old test-only snapshot-before-freeze race could leave a terminal-hold sleep
holding test pipes open. Transport tests now explicitly use private databases
rather than relying on the host's default debconf state.

## Release integration and limits

The repaired lifecycle/debconf helpers, embedded copies, preseed.cfg, payload
archive, manifest and SHA-256 pins are built together. `make check` rejects
stale products. Publish the complete release as one revision, rather than
mixing an updated script with an older preseed or payload. A failed running
installer must not be resumed by deleting its fatal markers.

This validates the reported defect and the exercised protocol/control-flow
contracts, not a complete physical installation. The exact deployment initrd,
cdebconf binary, firmware/Secure Boot, disk partitioning, live package sources,
first-boot services and graphical session still require image/hardware acceptance.

Primary source references:

1. https://sources.debian.org/src/preseed/1.125/debconf-set-selections/
2. https://sources.debian.org/src/preseed/1.125/preseed.sh/
3. https://sources.debian.org/src/preseed/1.125/preseed_command/
4. https://sources.debian.org/src/debconf/1.5.91/confmodule/
