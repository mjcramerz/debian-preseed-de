# Application exit before external-drive removal

## Requested contract

For Waybar poweroff/reboot, close GUI applications and Foot/Kitty terminal
workloads before syncing, unmounting and powering off external USB data drives.
Keep the user session and `/run/media/$USER` mount context alive through drive
preparation. Account, user-manager and greeter teardown follows that stage.
The gtkgreet power actions use the same authorized worker and drive backend.

The starting commit is `5c7b69ea6d9e934de82cd09a259e9a30508fd75f`, with the
earlier October 17 incident changes already present in the working tree. Their
four modified production/fixture files remain byte-identical to the earlier
recorded snapshot. The previous incident report describes that earlier payload;
the product hashes recorded below supersede its generated-product hashes.

## Entrypoints and authority

- Both Waybar bar definitions invoke `labwc-power-settings reboot|poweroff`,
  then `labwc-admin-action`, the existing Polkit-authorized root frontend and
  `labwc-admin-action@UID-ACTION.service`.
- The greeter's GTK confirmation controls invoke `greetd-power-action`, its
  fixed Polkit helper, and the same worker with a `greeter-` action instance.
- The worker remains a system-manager service, independent of the application
  cgroups it stops. User-manager calls drop to the authorized account using the
  existing validated runtime directory and bus address.
- The existing AppArmor worker profile already permits `systemctl`, `busctl`
  and system/user-manager IPC. No additional policy or authorization grant is
  needed. The drive service retains its existing confined root/UDisks boundary.

## Incorporated ordering

1. On the desktop path, retain the existing single native close request and
   ten-second save interval. This also creates the existing session-closing
   marker used by managed launchers. No second close request is introduced.
2. Stop `foot-server.socket`, `foot-server.service` and the authorized user's
   **`app.slice`** synchronously, with the existing bounded application cleanup.
   Managed GUI wrappers and standalone Foot/Kitty launchers already place their
   services and terminal descendants in this slice. Foot retains its existing
   TERM-first/mixed kill behavior; systemd owns final descendant cleanup.
3. Run the existing managed guest and network-sharing cleanup. The user manager,
   Labwc compositor, desktop target, user bus and GVfs mount context remain alive.
4. Ask PID 1's `GetUnitProcesses("user.slice")` for a bounded recursive process
   inventory. Reject remaining `app.slice` or `foot-server.service` processes,
   malformed/oversized records and unavailable inventory. The check also catches
   another account's remaining managed application cgroups. It does not require
   the whole user slice to be inactive. Live session/greeter infrastructure is
   permitted, and process command lines are never included in diagnostics.
5. Start the existing `labwc-external-drives-shutdown.service` and await its
   oneshot completion. It invokes the unchanged
   `labwc-external-drives --prepare-shutdown` backend from `/`, so neither the
   service nor its cleanup temporary directory holds a cwd on the data drive.
6. Only after drive preparation returns does the worker stop greetd, terminate
   the invoking account, stop its manager/slice, complete remaining ordinary
   cleanup and issue its existing exactly-once single-force PID-1 power request.

The desktop target and whole user slice are **not** stopped before drive
preparation. A Foot window whose shell or descendants still hold
`/run/media/$USER/...` keeps its application cgroup populated, preventing the
explicit drive-removal stage until those processes are gone.

The greeter path does not stop its own session before drive preparation. It
uses the same process-inventory gate: remaining managed desktop applications
cause explicit drive removal to be skipped, while the authorized final machine
power action retains its established behavior.

## Preserved mount/session context

`gvfs-daemon.service` and `gvfs-udisks2-volume-monitor.service` now explicitly
use `Slice=session.slice` in their existing staged session drop-ins. This
keeps the mount backends out of the application slice being stopped. The
custom `labwc-gvfs-volume-monitor.service` and compositor already use the
session slice. The upstream
[dbus-broker user unit](https://github.com/bus1/dbus-broker/blob/main/src/units/user/dbus-broker.service.in)
also assigns its broker to that slice; the effective target package/drop-ins
still require native acceptance.

The installer already stages both GVfs drop-ins at mode 0644. The existing
offline desktop verification boundary now requires those modes and the
session-slice assignment. The firstboot handoff gate also checks the new
application-exit barrier and the consistent drive-service wait limits.

The historical resource-policy fixture hashes were not regenerated. Its
existing exact-reversion mechanism now removes only these two reviewed
GVfs classification additions before comparing the historical bytes. Static
comparison confirmed that those exact reversions reproduce HEAD for both
files.

## Drive safety and deadlines

The existing backend retains ownership of inventory, device identity checks,
filesystem sync, normal UDisks unmount, confirmation that mounts disappeared,
and UDisks drive power-off. USB-connected NVMe enclosures use the existing USB
transport selection. The supported transport/device types were not broadened.
System-storage exclusions and active swap/mapping refusal remain intact.
UDisks busy-volume refusal remains authoritative for other holders of a drive.

Previously the worker allowed only ten seconds for the drive-service start
transport, although individual sync/UDisks operations can take 120 seconds and
the service has a 15-minute start timeout. The worker now waits up to **910
seconds** for that service job, including a margin beyond its existing
15-minute start/five-second stop limits. Dependency or transport stalls remain
bounded by this wait. It is separate from the ordinary 45-second cleanup budget.
The elapsed drive phase is excluded from that budget, preserving its previous
remaining amount for account teardown rather than silently skipping teardown
after a long successful sync.

A failed or timed-out drive start is not retried. The worker requests a bounded
stop of that service because terminating `systemctl` alone does not cancel its
PID-1 job. Unconfirmed cancellation is reported explicitly as an **unknown
outcome**. Neither service-stop completion nor a lost reply proves that a remote
UDisks operation was rolled back. The existing final machine handoff still
occurs after a failed/skipped preparation; the report does not claim every drive
was successfully removed on those paths. No forced unmount was added.

The process-inventory contract was checked against systemd 262's
[D-Bus API](https://github.com/systemd/systemd/blob/v262/man/org.freedesktop.systemd1.xml)
and [recursive process implementation](https://github.com/systemd/systemd/blob/v262/src/core/dbus-unit.c).
Its [cgroup retention code](https://github.com/systemd/systemd/blob/v262/src/core/cgroup.c#L2532-L2550)
retains tracking for processes left behind after unit failure. This is upstream
source evidence, not an executed target-manager check.

## Changed paths and prepared fixtures

Production changes are limited to:

- `hooks/target/usr/local/libexec/labwc-admin-action-worker`
- `hooks/target/etc/systemd/system/labwc-admin-action@.service.tmpl` (comments)
- `hooks/target/etc/systemd/system/labwc-external-drives-shutdown.service` (comments)
- `hooks/target/etc/systemd/user/gvfs-daemon.service.d/10-labwc-session.conf`
- `hooks/target/etc/systemd/user/gvfs-udisks2-volume-monitor.service.d/10-labwc-session.conf`
- `scripts/desktop/verify.sh.tmpl`
- `scripts/firstboot/04-validation.sh.tmpl`

The paths above are relative to `d-i/forky/`. Existing guarded fixtures in
`test_power_force_contract.py`, `test_shutdown_storage.py`,
`test_power_keyboard_20260913.py`, `test_power_quiescence_20260916.py`,
`refactor_fixture.py` and
`tools/tests/test_labwc_power_handoff.py` cover the new ordering, retained live
session/GVfs/greeter processes, Foot/Kitty leftovers, invalid inventory, manager
failure, service timeout/cancellation, unchanged final handoff and preservation
of the remaining cleanup budget. Fixtures were prepared but **not executed**.
The existing resource-policy suite consumes the shared exact-reversion helper;
its immutable historical hash data remains unchanged.

No source compilation, new dependency, installed host helper, running manager,
mount, block device or policy loader was used. Private Zoom/Discord Xwayland
implementation/configuration and the earlier incident source edits are retained.
Independent read-only sidecars failed to initialize with encrypted-content
hydration errors; no independent review result is credited.

## Static evidence and serialization

Completed checks are static inspection and permitted serialization:

- Parsed **423 Python files** as AST data without importing repository modules
  or executing fixtures; no parse errors. The classified source inventory is
  902 files / 263,576 physical lines: Python 144,746, shell 79,177, Perl 39,653.
- Inspected the worker's AST call order: application/Foot stop is separate from
  desktop-target teardown; external-drive preparation precedes greetd, account
  and user-manager teardown; the application-exit check precedes the drive job.
- Reconciled both exact GVfs reversions through every existing historical JSON
  hunk/hash layer and the original workload hashes as data. No repository
  fixture helper or test was executed for this comparison.
- `git diff --check` completed without whitespace errors. The unchanged drive
  backend, launch/profile modules and private-Xwayland source/lifecycle assets
  were compared with HEAD. The prior four incident source/fixture files retain
  their recorded combined fingerprint.
- All 52 `todo/` evidence paths and hashes still match the inventory.

An initial static mode assertion assumed checkout source files were mode 0644
and stopped when it encountered this checkout's mode 0600. The corrected check
uses the actual serialization contract: regular, nonexecutable source inputs;
publication/staging assigns archive and installed modes separately. No chmod
or source-mode repair was performed. This was an interrupted static check,
not an executed test suite or target failure.

Fingerprints below use SHA-256 over sorted records containing relative path,
NUL, file SHA-256 and LF:

| Source/fixture set | SHA-256 |
| --- | --- |
| All 902 classified source files | `05775e5533506bef9cfbec61bed9644b47bcfb85329756e447f302cdd68558da` |
| Seven power-flow production files | `f4a343c1b20ad0b715c3a85516ba0d92fd56acfbb26fc6b3efcde6db0af85a12` |
| Six power-flow fixture/helper files | `87f8a2a7c2c9d6f3ac5016a82832cf38c9f774960dae35da3ad086610ea3ee32` |
| Thirteen power-flow production/fixture files together | `e88bd20df086276ce4f95450220e90f6138646aee71c3812c12f5ae80a015f17` |

The reviewed Makefile, `tools/build.py` and `tools/publication.py` remain
unchanged. The permitted generation command was:

```text
/usr/bin/make --file Makefile --no-print-directory --no-builtin-rules --no-builtin-variables build 'PYTHON=/usr/bin/python3 -I -S'
PATH=/usr/bin:/bin HOME=/nonexistent LC_ALL=C.UTF-8
```

It exited **0**, reported `built 1795 payload files` and emitted no stderr.
The before/after content-and-mode snapshot found exactly the three allowed
products changed, with **2,417 other files unchanged during generation** and
no file additions/removals by the build.

An independent bounded standard-library archive reader confirmed **1,795
members / 34,426,085 uncompressed bytes**, equal source/manifest/archive file
sets, byte equality, SHA-256 agreement and canonical archive metadata. Nothing
was extracted or executed. The preseed pins agree with the archive, manifest
and bootstrap source. A final source-hash comparison confirmed all 1,795 inputs
still match after the last fixture updates; tests are excluded from the payload.

| Current generated product | SHA-256 |
| --- | --- |
| `d-i/forky/payload.tar.gz` | `ffaabee560b9b33380225ebf2ad72d44a412438434969057ab76eea0b9f704e0` |
| `d-i/forky/payload.manifest` | `311c5bbce7d69b64b4edccc2738950f1212a45a92b3accb8483764901afc8537` |
| `d-i/forky/preseed.cfg` | `08e48469745570cb2efb54d0fac0ec30575fc67060586d4ed8c6f2144c5269fb` |

The bootstrap-source pin remains
`6b3a40bb85942ed8f4b780852743140132414898b578af7c7597bb7c3872b246`.
These are current serialization results, not deployed acceptance results.

## Required native acceptance

`AGENTS.override.md` and `docs/test-isolation.md` prohibit host testing. No
prepared disposable Forky VM/image is supplied. All fixtures, policy parsing,
rendered-target execution and native integration remain unexecuted.

Before claiming deployed acceptance, use the approved disposable environment
with its own Python 3.14, systemd 262, user/system managers, UDisks, AppArmor,
procfs, mount tree, private virtual block devices and graphical session:

1. Run the changed guarded suites and installer/firstboot gates. Record the
   exact image/package versions and fixture/source fingerprints.
2. Open Foot and Kitty shells with cwd and open files under the fixture's
   `/run/media/USER/...`; leave descendants alive and ignore TERM. Verify native
   service cgroup cleanup and that drive removal begins only after they exit.
3. Confirm that the compositor, user manager/bus and GVfs backends remain alive
   until the drive service finishes; test both Waybar definitions and gtkgreet.
4. Exercise slow sync, busy unmount, absent/replaced devices, malformed/failed
   process inventory, another active desktop, a lost start reply and failed
   cancellation. Verify that busy drives are not force-unmounted/powered off,
   unknown outcomes remain explicit and no mutation or power handoff is retried.
5. Verify the native application and unchanged private Zoom/Discord launch/stop
   regression invariants, and independent logout/suspend behavior.

Actual NVMe/USB bridge power-off support additionally needs target hardware
evidence. Successful serialization does not establish any of these native results.
