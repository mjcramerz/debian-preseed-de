# Poweroff/reboot: close applications, ten-second save opportunity — 2026-10-13

## Accepted behavior

The latest user instructions define the behavior:

1. The power flow requests application closure itself, allowing applications to
   show their native save dialogs.
2. Terminals can close regardless of their child jobs; no terminal save
   acknowledgement is required.
3. If application save dialogs are unresolved after ten seconds, teardown
   proceeds regardless.

This supersedes the earlier 15-second warning described in
`vivaldi-power-save-20261013.md`. It does not introduce session capture/replay,
keyboard-based saving, source compilation or changes to private Xwayland.

## Source cause and correction

The preceding user helper waited before sending a close request, so applications
could not open their normal save dialogs during that window. The worker then
sent the close request and immediately began guest/filesystem/account cleanup.

`labwc-session-state` now sends its existing `wlrctl toplevel close` request once
at the beginning of the poweroff/reboot phase. It creates the existing private
session-closing marker, blocking new managed launches during shutdown. The
applications own their Save/Discard decisions. Terminals are not exempted from
the close request and have no added confirmation step.

One monotonic ten-second deadline covers the native close command, window
inventory, notification and polling. There is no per-application timeout and no
deadline extension after another query. If every window closes, the phase can
finish early. Unknown/inaccessible window state permits only the remaining
bounded wait. The helper does not inspect or log document titles, send simulated
Save key presses, or repeat the close request against newly created dialogs.

The packaged Forky `wlrctl` 0.2.2-2 source implements both `toplevel close` and
`toplevel list`. Its close action sends the native foreign-toplevel close
request, processes each handle once and completes after its initial Wayland
sync. This was checked against the [Debian package source](https://sources.debian.org/src/wlrctl/0.2.2-2/toplevel.c/)
as data; no package was compiled or executed.

The worker no longer sends a second `@close.service` request after this phase.
It first asks the invoking user's manager to stop `labwc-session.target` with a
30-second transport bound. Existing `PartOf`, stop ordering, cgroup ownership
and application stop timeouts handle applications, terminals and their child
jobs before filesystem cleanup. This is the beginning of the existing shared
45-second cleanup budget, not an additional independent budget.

The remaining guest, sharing, external-drive, greeter/account, swap and sync
cleanup keeps its existing bounded best-effort behavior. The final machine
request remains exactly one authorized `systemctl --force poweroff` or
`systemctl --force reboot` from the worker's `finally` path. A failed close
helper, remaining save dialog, terminal or cleanup command does not veto that
handoff. Failed/uncertain final acknowledgement is not automatically retried or
escalated to double force.

The root fallback also uses ten seconds and subtracts time already spent in a
failed helper transport. The user-manager transport retains its existing
25-second bound for service startup/IPC overhead. **Ten seconds is the save
opportunity after the native close phase starts, not a guaranteed total time to
power off hardware.** PID 1 and the subsequent bounded cleanup add their own
execution time. Remaining unsaved state receives no further application veto
after the accepted ten-second deadline.

## Complete installation/security route

- Waybar/menu/keyboard entry points route through `labwc-power-settings` and the
  existing authorized `labwc-admin-action` frontend.
- Polkit and the fixed root helper select the PID-1-owned worker by invoking UID
  and allowed action; the worker survives user-session shutdown.
- Its user-manager request starts `labwc-session-state@poweroff.service` or
  `@reboot.service`, using that manager's compositor environment and user UID.
- Existing target staging installs both helpers at mode 0755, the worker unit
  at 0644 and the state unit in the desktop skeleton. Existing installed-file
  checks and account copying retain these consumers.
- Existing AppArmor profiles already permit the exact `wlrctl`, `notify-send`
  and user-manager `systemctl` operations and private closing marker. No new
  execution, signal, D-Bus, capability or filesystem grant was added.
- Greeter requests retain their existing path without a desktop save helper.
  Logout retains its native close/dialog cancellation behavior; suspend retains
  its lock behavior. Private Xwayland sources/policy are preserved.

## Guarded regressions and execution boundary

Updated the existing guarded fixtures for:

- One native close request before the ten-second wait for both actions.
- Empty windows finishing early and remaining Save dialogs reaching the deadline.
- Native close/probe/notification delays consuming the same deadline.
- Failed close/inventory/helper transport still permitting the final handoff,
  with no second close request or extra full grace period.
- Source-level worker/helper integration: unresolved GUI dialogs and terminals
  reach managed application teardown and exactly one power request at the
  fixture clock's ten-second boundary.
- Managed application stop preceding guest/filesystem/account cleanup.
- Failure of the application-stop stage still permitting the single final request.
- Explicitly mocked user-manager commands in fixtures affected by the new stop.

These fixtures were authored and inspected as data; **none was executed**.
`AGENTS.override.md` requires a prepared disposable environment without access
to host configuration, services, managers, package state or user data. Such an
environment was not available. No test/discovery/import hook, shell/Perl syntax
runner, AppArmor parser, systemd validator or live power action was executed.

Independent sidecar reviews were attempted but failed initialization with
encrypted-content hydration errors. No child findings or successful independent
review are claimed. Root review traced source, caller, staging and policy data.

## Static inspection and generation evidence

- Parsed the two changed Python helpers and five changed fixture modules with
  the standard-library AST parser, as source data without imports or execution.
- Checked the one-close request, shared ten-second deadline and worker teardown
  order against the callers, user units, target dependencies and AppArmor rules.
- Compared four private Xwayland implementation/policy/fixture paths with HEAD;
  all were byte-identical. Existing checkout file modes were preserved.
- `git diff --check` exited 0.
- Ran the expressly permitted generation-only command:

  ```sh
  /usr/bin/env -i PATH=/usr/bin:/bin LC_ALL=C.UTF-8 /usr/bin/make build PYTHON='/usr/bin/python3 -I' SHELL=/bin/sh
  ```

  It exited 0 and reported `built 1757 payload files`. Before/after checkout
  metadata comparison showed changes only to `d-i/forky/payload.tar.gz`,
  `d-i/forky/payload.manifest` and `d-i/forky/preseed.cfg`.
- Inspected the archive as data without extracting or executing it: all 1,757
  regular members (33,963,225 source bytes) matched the canonical source bytes
  and manifest hashes. Archive paths and normalized metadata were checked; test
  modules and private input names were absent. The two removed unsigned Vivaldi
  search-engine caches were absent. No active `CPUAccounting=` directive was
  present. All three bootstrap/preseed checksum pins matched their inputs.

| Generated product | SHA-256 |
| --- | --- |
| `payload.tar.gz` | `9510baaa62eae9437773e45ccace8872ecd03bc3e991d9c745af1a70cf2a60c2` |
| `payload.manifest` | `370e53ea79fad2189031758001e2f32ded63042776ddc05b463c96e24b92bff4` |
| `preseed.cfg` | `889e11a65a376a452cc7fcbd91d8a9316ec8ec9d9679c1b509146877087f038c` |

The pinned `scripts/common/source.sh` SHA-256 remains
`6b3a40bb85942ed8f4b780852743140132414898b578af7c7597bb7c3872b246`.
These results establish source and serialization consistency. Native GUI save
dialogs, systemd stop behavior, filesystem teardown and machine poweroff/reboot
still require execution in the mandated disposable environment.

## Changed paths for this follow-up

- `d-i/forky/hooks/target/usr/local/libexec/labwc-session-state.tmpl`
- `d-i/forky/hooks/target/usr/local/libexec/labwc-admin-action-worker`
- `d-i/forky/hooks/target/etc/systemd/system/labwc-admin-action@.service.tmpl`
- `d-i/forky/tests/test_power_force_contract.py`
- `d-i/forky/tests/test_power_io_policy_r6.py`
- `d-i/forky/tests/test_power_keyboard_20260913.py`
- `d-i/forky/tests/test_power_quiescence_20260916.py`
- `tools/tests/test_labwc_power_handoff.py`
- `docs/validation/vivaldi-power-save-20261013.md`
- `docs/validation/todo-20261013-review.md` (links its earlier artifact snapshot
  to the current generation evidence).
- This report and `d-i/forky/{payload.tar.gz,payload.manifest,preseed.cfg}`.

Earlier Wi-Fi, CPUAccounting, Vivaldi and Tailscale changes remain preserved.
