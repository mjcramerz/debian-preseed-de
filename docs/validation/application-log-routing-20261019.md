# File-only ChatGPT, Codex and application output, 2026-10-19

## Requested behavior

Managed application payloads written to `apps.log`, and the dedicated ChatGPT
capture, must not be copied into journald at any priority. Collector failure
must not restore a journal fallback. Native Codex login/TUI files retain their
existing paths, ownership and rotation.

This changes installation sources and generated products. It does not deploy
to the development host, purge existing journal records, or suppress systemd's
own unit lifecycle messages, kernel records or security audit events. Programs
that independently address journald outside these managed capture paths remain
outside this file-output contract. Journal-origin messages are no longer
duplicated into `apps.log`.

## Source trace and changes

- `etc/rsyslog.conf.tmpl`: remove the `omjournal` module and the application
  journal template. Other native system/security inputs retain their existing
  routing and storage policy.
- `etc/rsyslog.d/21-apps.conf.tmpl`: retain authenticated desktop-UID admission,
  the single protected file, bounded disk-assisted queue and size rotation.
  Remove warning/error reflection and the journal-to-application-file copy.
  Legacy user journal input stops before unrelated component classifiers.
- `etc/rsyslog.d/38-openai-chatgpt.conf.tmpl`: keep the dedicated private socket
  and protected file; remove warning/error reflection.
- `usr/local/libexec/rsyslog-app-run.tmpl`: capture every child severity in the
  private application socket. Remove all inherited-stderr fallback payloads.
  Capture failures attempt only a bounded, error-class-only private diagnostic.
  Command-line diagnostics have null inherited output. Preserve child exit and
  signal status, pidfd observation, cgroup ownership and bounded cleanup.
- `usr/local/bin/labwc-fuzzel-log.tmpl`: remove `/dev/log` fallback. Remove the
  corresponding two unused allow rules from its AppArmor profile.
- Managed native, generic, Bitwarden, compatibility, qBittorrent and recording
  services use null inherited output while the capture supervisor owns the
  child's pipes. Compatibility and recording entrypoints now use the existing
  capture helper. ChatGPT retains its dedicated pipes and profile transitions.
- Codex backend output and readiness diagnostics use capture; its inherited
  output is null. Proxy output is null. The proxy retains its original direct
  `systemd-socket-proxyd` executable, socket activation descriptors, notification
  and idle-exit behavior. It is not placed behind a subprocess supervisor.
- The Codex staging validator requires the new readiness command and null
  service outputs. The guarded logging checker rejects `omjournal` output.
- Existing guarded fixtures have been updated for file-only delivery, missing
  collector behavior, redacted private failures, stream settings and the two
  native size-rotation fixture inputs. These guarded suites are not run on the
  development host or by bypassing their rootless-image guard.

The source controls are deliberate: systemd 262 documents
[`LogFilterPatterns=` as unavailable for per-user services](https://www.freedesktop.org/software/systemd/man/262/systemd.exec.html#LogFilterPatterns=).
No unsupported per-user filter or global journal shutdown is introduced.

## Collector outage behavior

If the private socket is missing or full, affected records are dropped. The
application keeps running and retains its real status. Capture waits at most
50 ms on one failed send and retries subsequent delivery after one second;
Fuzzel and the existing ChatGPT capture remain nonblocking. There is no new
user-writable file, unbounded userspace queue or alternate journal transport.
The existing collector's bounded file-output queues and rotation are retained.

## Validation and provenance

Base revision: `8881d6beaf7f11a400bff9436df265d70e630021`. The working tree
was clean before this task. Two independent read-only sidecars failed during
encrypted-context initialization; no independent findings are credited.

The disposable fixture is retained at
`/tmp/preseed-app-logs-20261019-t4x57aay/`. Its QEMU argument array specifies TCG,
`-nic none`, no host shares or forwarded sockets/devices, a read-only fixture
ISO and a snapshot of an owned regular-file root image. The guest owns its
kernel, managers, package tree, sockets and files. The outer environment is
minimal and contains only owned fixture HOME/TMPDIR values.

The reused prepared Forky image derives from Debian's daily
`20261018-2635/debian-14-generic-amd64-daily-20261018-2635.qcow2`, whose retained
verified vendor-image SHA-512 is
`4c076e27b5da2d90dc64ec3ac398cc7703c6cc2bcd07e068c291b832153bb260f4712abb4a440b5d62b545db9be4e4a1de7289726d493643b87800f1ce431687`.
The fixture's five Debian package downloads are bounded, do not follow
redirects, and match the SHA-256 values in the retained Forky package index;
`packages.json` records the index digest, versions, paths and package hashes.
They are installed only inside the disposable guest, with its own
`policy-rc.d` blocking automatic daemon starts during package setup.

The source-copy SHA-256 list covers 2,103 files and 41,395,825 bytes. Its
fingerprint is
`1a60ceea6ee5c665c165160b7c31bebddfe1714602248713272009b61aafea02`.
The fixture uses real rsyslog/journald and a guest systemd service with
`User=2000`, with synthetic payloads and a fake ChatGPT child. It does not
authenticate with OpenAI, launch the GUI, or exercise a real Codex backend.
The attempted user-manager gate is recorded separately below.

### Earlier attempts

1. `qemu-console.log`: target parsing failed because the deliberately minimal
   image lacked the installer's `logreader` group. QEMU exited cleanly, but
   `LOG_GUEST_STATUS=1`; this is not successful acceptance. The next fixture
   creates the three managed logging groups before parsing. Production sources
   were not changed to accommodate the incomplete fixture.
2. `qemu2-console.log`: complete target rsyslog parsing, shell/Perl parsing,
   all eight priority probes in each sink, captured output, private redacted
   failure reporting, Fuzzel and the fake ChatGPT child succeeded. Starting
   `user@2000.service` failed because of a dependency job in the minimal boot.
   `LOG_GUEST_STATUS=1`; the aggregate run is not a pass. The final fixture uses
   the real guest system manager with `User=2000` for the process-I/O check.
   It does not claim a working desktop user-manager session.
3. `qemu3-console.log`: the same parsing/delivery phases succeeded. The
   `systemd-run` service probe could not connect because this minimal boot had
   no system bus. `LOG_GUEST_STATUS=1`; it is not an aggregate pass. The next
   fixture writes its own guest-only oneshot unit and uses the already working
   private system-manager control channel through `systemctl`.
4. `qemu4-console.log`: native file delivery and the real guest per-UID
   systemd service succeeded. Journal queries returned only the positive
   system control marker. The outage child returned status 9 with empty
   stdout/stderr, but an added three-second wall-clock assertion failed under
   TCG emulation. The next fixture removes that performance assertion and
   retains a 15-second outer process timeout. Production code is unchanged.
5. The first generation command completed both serializers, then its broad
   before/after hash check caught this task report being created concurrently.
   The check failed visibly. With edits paused, both serializers ran again;
   generation changed no bytes, all 1,818 archive members matched current
   source/manifest bytes and preseed pins, and no source input changed.
6. The source-mode inspection detected mode 0600 on the 18 edited tracked
   inputs. Their Git index mode is 100644. Validated, single-link, owned file
   descriptors restored mode 0644 on exactly those paths. Content bytes and
   generated archive metadata were unchanged. No recursive mode change ran.

The updated guarded suites remain unexecuted. A full rootless suite image,
fresh desktop/user-manager boot, real ChatGPT/Codex GUI/backend lifecycle and
private Zoom/Discord GUI regression checks remain separate acceptance gates.


### Final native result

`qemu5-console.log` completed with `LOG_FINAL=success`,
`LOG_GUEST_STATUS=0`, and QEMU exit 0. All five VMs powered off and were reaped;
no native fixture process remains running.

Target packages: systemd **262-1**, rsyslog **8.2608.0-4**, Python
**3.14.7-3**, Perl **5.42.3-1**. The guest kernel is
`7.2.11+deb14-amd64`.

- Complete rendered rsyslog configuration accepted by target `rsyslogd -N1`.
  This uses catalog substitution in the fixture; it is not a complete installer
  renderer/activation test.
- Target `sh -n` accepted the recording and Codex staging source scripts;
  `perl -c` accepted the rendered Fuzzel logger.
- Sixteen synthetic priority probes covered all eight severities in each of
  the two real file sinks. Real capture, a missing executable's private
  redacted failure, Fuzzel delivery and the fake ChatGPT child were observed.
  Child status 7 was preserved, with empty inherited stdout/stderr.
- A real guest oneshot service with `User=2000`, null standard output/error
  and the actual capture helper delivered its error payload to `apps.log`.
- A positive system control marker was visible through the real guest journal.
  Queries for the common marker found only that control record; none of the
  application payload markers appeared in `journalctl`.
- With the collector absent and with its datagram queue full, the real helper
  returned child status 9 with empty stdout/stderr. Both cases completed under
  the 15-second fixture timeout (3.604 and 3.442 seconds including emulated
  interpreter startup). Fuzzel also returned without fallback output. A final
  journal query still found only the system control marker. These elapsed
  times are fixture observations, not a desktop performance benchmark.

There was no live-host service, package, firewall, policy or logging change.
No real OpenAI account or session data was used. No full guarded suite, native
application GUI, full desktop user manager, or real Codex backend/proxy
activation acceptance is claimed.

### Static and serialization evidence

Nine changed Python inputs accepted standard-library AST parsing as data,
without imports or executing repository code. Active rsyslog configuration has
zero `omjournal` outputs. All 2,103 copied native source inputs match the final
checkout bytes. The private Xwayland implementation and eligibility policy
were not changed; only the common compatibility service output capture changed.

Reviewed commands:

```text
/usr/bin/make --no-print-directory build 'PYTHON=/usr/bin/python3 -I -S'
/usr/bin/make --no-print-directory inventory 'PYTHON=/usr/bin/python3 -S'
```

The payload has 1,818 unique regular members and 34,703,753 expanded bytes.
Each member matches its current source and manifest SHA-256. Member ownership,
mode and time are normalized to UID/GID 0, 0644 and time 0. Preseed's payload and
manifest pins match. The second serialization pass changed no bytes; no source
input changed. `inventory-apt.json` was not refreshed or modified.

| Product | SHA-256 |
| --- | --- |
| `d-i/forky/payload.manifest` | `69ce2885d62245a496121ad08217f08a53542c869a2bea2c5d2172b214c11c35` |
| `d-i/forky/payload.tar.gz` | `ea55e1a368545e2e33325f1f7e66dda2a8e0dbf24c88aa1f5948465ce72f3fa9` |
| `d-i/forky/preseed.cfg` | `fcde575cb46b50b037c43594e53d1867e48fc691c60fc59d65969c6205dc4f2d` |
| `inventory-apt.json` | `96314d9227e24e04aaf8577258cbc7c8bc575fe36cb855b49dda89c9ffc83318` |
| `inventory.json` | `d8818f7b7fcc32e3aa3236d1e8028ae82389cf1d2cce763d2651ee9b74ccbd94` |

### Native fixture identities

| Input/evidence | SHA-256 |
| --- | --- |
| `rootfs_sha256` | `5a5d0eebaf4be1f03f8335c53064f53781a088f90daf9bc996a01b5480a51036` |
| `final_fixture_sha256` | `e637eef6969f1be077b3d85bd6e58fe24b83d69102946c9caf2abd3b543959ed` |
| `final_iso_sha256` | `5b0ef4863d7e400fdc686ae6943e4d9e9515499b950d49d245d570794ca9fa38` |
| `final_console_sha256` | `56b03629b73471778fbbf5f8ecd75d81228e4bc78f73d80ead89853e12b1fda8` |

Exact package download and all failed/final fixture file hashes are retained
in `packages.json` and `fixture-evidence.json` in the private fixture tree.

## Exact changed paths

- `d-i/forky/hooks/target/etc/apparmor.d/desktop-wrappers.tmpl`
- `d-i/forky/hooks/target/etc/rsyslog.conf.tmpl`
- `d-i/forky/hooks/target/etc/rsyslog.d/21-apps.conf.tmpl`
- `d-i/forky/hooks/target/etc/rsyslog.d/38-openai-chatgpt.conf.tmpl`
- `d-i/forky/hooks/target/etc/skel-desktop/.config/systemd/user/codex-app-server-proxy.service`
- `d-i/forky/hooks/target/etc/skel-desktop/.config/systemd/user/codex-app-server.service`
- `d-i/forky/hooks/target/usr/local/bin/labwc-capture.tmpl`
- `d-i/forky/hooks/target/usr/local/bin/labwc-fuzzel-log.tmpl`
- `d-i/forky/hooks/target/usr/local/bin/labwc-qbittorrent`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/generic.py`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/session.py`
- `d-i/forky/hooks/target/usr/local/libexec/rsyslog-app-run.tmpl`
- `d-i/forky/payload.manifest`
- `d-i/forky/payload.tar.gz`
- `d-i/forky/preseed.cfg`
- `d-i/forky/scripts/late/devops/codex-appserver.sh`
- `d-i/forky/tests/test_desktop_sandbox.py`
- `d-i/forky/tests/test_installed_failures_20260911.py`
- `d-i/forky/tests/test_logging_size_20260924.py`
- `d-i/forky/tests/test_managed_logging_r3.py`
- `docs/validation/application-log-routing-20261019.md`
- `inventory.json`
- `tools/check_logging.py`
