# Desktop power lifecycle and pinned resctl-bench installation

Date: 16 September 2026. This is the complete unattended-install publishing
repository, not a script that upgrades an already-running desktop.

This document supersedes **only the power-dispatch design** in
`POWER-AND-IO-POLICY-R6.md`. The independent I/O-accounting/weight switches,
resource classes, broker stop-timeout policy, existing package selections and
unrelated desktop configuration remain unchanged. Older reports/manifests and
validation directories are retained as historical records, not current
instructions or current test results.

## Power actions

The existing Waybar/menu -> authorized root frontend -> PID-1-owned
`labwc-admin-action@UID-ACTION.service` route is retained. The worker is outside
the desktop user's cgroups, has a root-only global action lock, and acknowledges
readiness before the frontend exits. Authorization, account validation,
AppArmor confinement and the existing other-account checks are retained.

The reboot/poweroff sequence is now:

1. The user-owned preparation helper establishes the launch-closing marker,
   records approved application restart descriptors and requests graceful
   window closure. An unresolved save dialog or failed window probe cancels
   before destructive teardown. Application-native save behavior is retained;
   this is not a universal checkpoint of application memory or terminal jobs.
2. The worker rechecks for another interactive account, reads the session
   target's inverse `PartOf` membership (`ConsistsOf`), and marks the request
   committed before submitting any stop jobs.
3. A synchronous user-manager `stop` covers the session target, compositor and
   observed session members. Existing `After=labwc-session.target` client
   ordering and the target's `After=labwc-compositor.service` relationship put
   clients before the compositor on stop. The worker rereads membership and
   requires every observed member to be inactive/failed, with no pending job or
   main/control PID, before proceeding. A collected transient can be represented
   by the manager's inactive/not-found unit properties. Historical failures are
   not reset or hidden merely to make the journal look clean.
4. The two fixed, optional guest shutdown hooks
   `podman-devops-restart.service` and `incus-startup.service` are stopped only
   when installed and running. Their stop operation and final results must
   succeed. These are not arbitrary unit names supplied by the caller. Engines,
   logind, the user manager and both D-Bus brokers remain available to consumers.
5. Only then does the worker issue exactly one of:

   ```text
   /usr/bin/systemctl --force --no-ask-password reboot
   /usr/bin/systemctl --force --no-ask-password poweroff
   ```

No intermediate `shutdown.target`, `umount.target`, `final.target`,
`reboot.target` or `poweroff.target` is started. There is no double-force,
`reboot -f`, slice-wide emergency kill, target finalizer or automatic retry of
an uncertain power handoff. The four obsolete `labwc-power-{reboot,poweroff}`
service/target files are removed from the payload; installer staging also
removes stale copies at their exact target paths. Normal passive shutdown
ordering in vendor/user units is deliberately retained: it is not an instruction
to enqueue those targets.

A failed or ambiguous stop prevents the force call. Once teardown has started,
an error does not clear the launch gate, pretend that saving was cancelled, or
restart the desktop behind the user. Inspect the worker journal and recover
from a console/greeter as appropriate. After a successfully submitted power
request, a lost reply is reported as uncertain and is not retried.

### Launch and transport race fixes

Managed native, Electron, compatibility and qBittorrent transient launchers now
have a second, manager-side `ConditionPathExists=!/run/user/UID/labwc-session-closing`
check, in addition to their existing early launch guard. The condition uses an
absolute path: transient D-Bus conditions do **not** expand `%t` like unit files.
These application units use `Requisite`, not `Requires`, for the desktop and
session-owned Secret Service provider, so a late launch cannot pull the desktop
back up. The independent Codex backend activation dependencies are retained.

The recorder transient is now session-bound and ordered after the target, with
`ExitType=cgroup` and `KillMode=control-group`. Its existing `SIGINT` and
20-second stop timeout are preserved so recordings get a normal finalization
opportunity before the compositor exits.

Canonical host-administration terminal/GUI launchers explicitly retain host PID
and UID semantics (`PrivatePIDs=no`, `PrivateUsers=no`). Other application
isolation remains unchanged. The existing `SuccessExitStatus=1` allowance stays
restricted to the exact default `/usr/bin/foot` shell invocation. It is **not**
expanded to `foot -e`, arbitrary application failures or Foot's internal error
status.

The worker no longer unconditionally SIGKILLs a successfully drained local
transport process group. Timeout/cancellation still kills and reaps the transport
group, including descendants holding pipes open. This removes an avoidable
peer-teardown race; it is not a claim that every logind peer-PID message from
any source has been reproduced or eliminated.

The worker's outer runtime bound is 600 seconds; individual save, desktop-stop,
guest-stop and transport operations are separately bounded. There are no sleeps
used as shutdown barriers and no process-name polling. Suspend and account-local
logout keep their separate existing paths.

## resctl-bench in every profile

All 13 `d-i/forky/hosts/profiles/*.env` files carry the same explicit values:

```sh
RESCTL_BENCH_VERSION="2.2.6"
RESCTL_BENCH_TAG="resctl-bench-v0.0.1-P15s"
RESCTL_BENCH_ARCHITECTURE="amd64"
RESCTL_BENCH_URL="https://github.com/mjcramerz/resctl-bench/releases/download/resctl-bench-v0.0.1-P15s/resctl-bench-2.2.6-x86_64-unknown-linux-gnu-native.tar.gz"
RESCTL_BENCH_SHA256="466f9d0fbdea9b9c5755bb03cd1e5905e3b3fe3fc311c564b3c3619781e2786c"
RESCTL_BENCH_MAXIMUM_BYTES="536870912"
RESCTL_BENCH_MAXIMUM_EXTRACTED_BYTES="2147483648"
RESCTL_BENCH_MAXIMUM_MEMBERS="8192"
```

The desktop late-command fetches the new `resctl-bench.sh` module and invokes its
installer for every desktop profile, independently of addon selection. A
repository-owned Python helper is temporarily staged inside the target and run
with `python3 -I` and a cleared environment. The temporary helper is removed on
normal completion and shell-handled failure/signal paths. No installer or tuning
script from the downloaded archive is executed.

The target installation:

- Checks target architecture and strict URL/tag/version/hash/bound policy.
  HTTPS-only curl transfers and redirects have size, retry and time limits;
  `.curlrc` and ambient proxy/loader/Python configuration are not inherited.
- Verifies the supplied SHA-256 **before** parsing or executing archive content.
  It bounds the complete decompressed stream and member count, rejects traversal,
  duplicate/ambiguous paths, links, sparse files, special nodes, file/directory
  collisions, unexpected roots and unknown executable payloads. Extraction is
  explicit regular-file copying, not `extractall()`.
- Requires `resctl-bench`, `rd-agent` and `rd-hashd`, and accepts `resctl-demo`
  when present. The tagged packaging source identifies these binaries. All
  regular release files must match the bundled `SHA256SUMS` inventory, and
  binaries must have x86-64 ELF headers.
- Runs **only `--version`**, as `nobody` with supplementary groups removed and
  bounded execution. Loader/version/native-instruction failures abort before
  publication. The `native` build is not a portable generic-amd64 guarantee:
  passing `--version` cannot prove that every later workload avoids unsupported
  instructions on another CPU. Use suitable P15s-compatible hardware and
  validate workloads separately on a disposable scratch device.
- Publishes binaries as root-owned mode 0755 files under `/usr/local/bin/`.
  Documentation, licenses, build provenance, root README/checksum files, debug
  material and bundled scripts-as-data are retained under
  `/data/docs/resctl-bench/release/`, preserving their relative layout. Files
  there are mode 0644. The original main docs are consequently under
  `release/share/doc/resctl-bench/`.
- Commits `/data/docs/resctl-bench/INSTALLATION.json` last, recording the pin and
  installed-file hashes/modes. Publication uses same-filesystem temporary files,
  fsync and no-clobber linking. Caught publication errors roll back newly created
  files. This is per-file atomic publication, not a claim of an atomic multi-file
  transaction across `/usr` and `/data` during sudden power loss.

An identical repeat install is accepted. A different, locally modified,
symlinked, hardlinked, wrongly owned or wrongly permissioned existing destination
is rejected rather than silently overwritten. Installation parents must be
root-owned real directories without group/other write permission. Future pin
upgrades therefore require explicit reconciliation of the previously installed
files; do not change only the URL and assume an unmanaged overwrite is allowed.

No benchmark, persistent agent, oomd service, CPU/storage tuning, or kernel-build
workload is started or enabled by this integration. Workload-specific optional
packages and scratch-device preparation remain maintenance tasks described by
the retained release documentation. Installer verification and first-boot path
checks cover the installed executables and provenance; first boot does not run
benchmarks.

## Validation and deployment

Current machine-readable results and full logs are in
`validation/power-resctl-20260916/`. The root `POWER-RESCTL-VALIDATION.md` records
the commands, outcomes and limitations. New regression suites are
`test_power_quiescence_20260916.py` and `test_resctl_bench_20260916.py`; existing
power tests were updated for the new contract rather than retaining assertions
that require the removed shutdown barriers.

The release archive itself was **not downloadable into the validation container**.
Its exact supplied pin is enforced by installation, but this delivery does not
claim an independent download/hash match or execution of that actual release.
Archive tests use explicitly synthetic packages matching the tagged packaging
layout. A harmless compiled fixture separately exercises the real unprivileged
`--version` execution path. No reboot/poweroff command was executed in validation.

The supplied host's systemd version is 261.2. Source behavior was reviewed at
that tag; local offline systemd checks use the container's 257.9, not a booted
261.2 manager. AppArmor parser acceptance is not live enforcement acceptance.

Before production rollout, use a disposable target with systemd 261.2 and the
same hardware/driver/storage configuration. Confirm that an unsaved editor
window cancels power without closing the desktop, that a competing interactive
account blocks machine power, and that reboot/poweroff after saving completes
with the worker's verified-quiescence message before the single-force handoff.
Inspect the previous boot's worker, user-manager, Foot and logind journals, and
check recording finalization and guest shutdown on hosts that use those features.
Confirm the actual release hash, target `--version` checks and installed
`INSTALLATION.json`; do not start resource-control benchmarks on production data.

Publish the whole tree atomically. `payload.tar.gz`, `payload.manifest` and
`preseed.cfg` have been regenerated together; serving only selected changed files
will invalidate the pinned installer snapshot. Replacing the served repository
does not by itself update hosts that are already installed.

## Primary implementation references

- systemd 261.2 systemctl manual, single-force semantics:
  <https://github.com/systemd/systemd/blob/v261.2/man/systemctl.xml>
- systemd 261.2 force dispatch implementation:
  <https://github.com/systemd/systemd/blob/v261.2/src/systemctl/systemctl-start-special.c>
- systemd 261.2 transient condition path handling:
  <https://github.com/systemd/systemd/blob/v261.2/src/core/dbus-unit.c>
- Reported shutdown transaction issue (not a reproduced diagnosis of this host):
  <https://github.com/systemd/systemd/issues/38987>
- Exact tagged resctl-bench packaging implementation:
  <https://github.com/mjcramerz/resctl-bench/blob/resctl-bench-v0.0.1-P15s/scripts/build.py>
- Release runtime guidance and opt-in workload packages:
  <https://github.com/mjcramerz/resctl-bench/blob/resctl-bench-v0.0.1-P15s/docs/RUNTIME.md>
  and <https://github.com/mjcramerz/resctl-bench/blob/resctl-bench-v0.0.1-P15s/packages/runtime.txt>
- Incus startup/shutdown hook responsibilities:
  <https://github.com/lxc/incus/blob/main/doc/packaging.md>
