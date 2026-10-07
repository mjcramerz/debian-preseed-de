# gtkgreet Reboot and Shutdown repair — 2026-10-07

## Observed blocker

The supplied LPL-697 button-press log records the greeter as `_greetd`, UID 989,
with an active `user-light` Wayland session. At 14:18:13 and 14:18:17 the reboot
requests fail in pkexec; the poweroff request fails there at 14:21:26. Each
reports that the inherited SHELL value is absent from `/etc/shells`. These are
pre-authorization environment failures, before the fixed root helper or
system-manager worker can run.

The [upstream Polkit 127 source](https://github.com/polkit-org/polkit/blob/127/src/programs/pkexec.c)
validates a present SHELL against `/etc/shells` and skips absent environment
entries. The greeter's fixed-function power request does not need that variable.

## Implemented repair

`hooks/target/usr/local/sbin/greetd-power-action` unsets SHELL after validating
the action and before executing the fixed pkexec command. This changes only
the request environment. The package account retains its nologin shell;
the configured active/local greeter authorization and PKEXEC_UID/NSS identity
checks still apply.

The action path is:

1. Confirm Reboot or Shutdown on the greeter power buttons.
2. Run `greetd-power-action` with the fixed `reboot` or `poweroff` argument.
3. Authorize the exact `greetd-power-action-root` helper through Polkit.
4. Start and wait for `labwc-admin-action@989-greeter-ACTION.service` through the
   existing root frontend; the numeric UID comes from pkexec, not a UI argument.
5. Run the shared package-aware worker, verify required cleanup, and submit
   exactly `systemctl --force reboot` or `systemctl --force poweroff` once.

The worker already implemented the requested single force. Its production
code and service confinement are preserved. Cleanup includes applicable guest
hooks, network shares, greeter/session teardown and swap/storage services.
Known inhibitors, other interactive users, identity changes, busy mounts or
failed cleanup continue to prevent the final submission. A lost final
acknowledgement is not retried or escalated. The
[systemd v261 systemctl documentation](https://github.com/systemd/systemd/blob/v261/man/systemctl.xml)
distinguishes this PID-1 handoff from a double-force direct reboot.

`hooks/target/usr/local/bin/labwc-greeter-power` now retains a visible
**Reboot failed** or **Shutdown failed** label if process creation or the waited
helper fails, restores button sensitivity, and emits a bounded structured
journal event containing action, stage and numeric errno/exit status. It
continues inheriting helper stderr into greetd's journal. A new attempt requires
confirmation again. Confirmation timers are removed when replaced or submitted,
so an old timer cannot clear a later failure message.

`scripts/firstboot/04-validation.sh.tmpl` now requires the exact `unset SHELL`
line in the installed frontend, in addition to the existing fixed helper,
waited unit, identity, capability, seccomp and single-force checks.

## Validation evidence

All verification was offline or used isolated adapters. No host reboot,
poweroff, service start/stop, privileged pkexec call, account change or policy
load was performed.

| Command/check | Result |
| --- | --- |
| New button/environment regressions against the original source | Six methods ran; five methods failed across 12 subcases, reproducing the retained SHELL and silent/timer-reset failure behavior. |
| `python3 -B -m unittest discover -s d-i/forky/tests -p test_greeter_power_followup_20260922.py -q` | 35 passed, no skips. |
| `python3 -B -m unittest discover -s d-i/forky/tests -p test_power_force_contract.py -v` | 11 passed, no skips. |
| `python3 -B -m unittest discover -s d-i/forky/tests -p test_shutdown_storage.py -v` | 14 passed, no skips. |
| `shellcheck --shell=sh d-i/forky/hooks/target/usr/local/sbin/greetd-power-action` | Passed with no diagnostics. |
| AST parsing of the changed Python controller and two test files | Passed, without bytecode writes. |
| `python3 -B tools/build.py` | Built 1,704 payload members; regenerated manifest and preseed pins. |
| `python3 -B tools/build.py --check` | Snapshot, pins and preseed current. |
| `python3 -B tools/check_shells.py` | 350 shell files, 711 parser checks passed. |
| `python3 -B tools/check_preseeds.py` | 59 files passed; all four generated command values survived private debconf read-back unchanged. |
| Payload comparison against a private pre-task member inventory | Exactly the three intended production members changed; every other member and all modes/link targets were preserved. |
| `git diff --check` | Passed. |

The button tests execute the production controller with GTK/GLib endpoints
replaced before use. The integrated button test spawns private copies of the
real shell helper chain with inherited `/usr/sbin/nologin`, `_greetd` and UID
989; pkexec and systemctl are isolated adapters. Both confirmed actions reach
the exact waited greeter worker instance. This proves argument/environment
dispatch, not live authentication or shutdown.

Worker tests intercept every host transport, then verify ordered cleanup and
the literal single-force commands for both greeter and desktop actions. The
Polkit rule executes under a Node fixture with synthetic active/local subjects;
no real authorization grant is requested. The first-boot gate is executed only
as read-only checks of private fixture files and rejects removal of the shell
correction, missing/double/replaced force, or weakened confinement.

The older greeter-flow fixture was corrected to model the current shutdown
coordinator and isolate its network-sharing configuration input. Before that
fixture correction, four existing methods failed by reading host configuration
or omitting required teardown state; those failures were not treated as a new
production root cause.

Verification host packages: greetd 0.10.3-7, gtkgreet 0.8-2, pkexec/polkitd
127-3 and systemd 262-1. The requested deployed system remains Forky/systemd
261.2. Existing EncodingWarning messages did not fail these checks. The broad
repository suite was not rerun or declared passing.

Payload SHA-256:
`df35c4c6ef01ad41bd17a1aa9f8377d7ed8f330a9eea14883f3144ef361acd84`.

## Applying the repair to LPL-697

The rebuilt installer serves the correction to future installations. It does
not replace the helpers already installed on LPL-697. From the updated
repository root **on that intended target**, an administrator can install the
two helpers:

```sh
sudo /usr/bin/install -o root -g root -m 0755 -- d-i/forky/hooks/target/usr/local/sbin/greetd-power-action /usr/local/sbin/greetd-power-action
sudo /usr/bin/install -o root -g root -m 0755 -- d-i/forky/hooks/target/usr/local/bin/labwc-greeter-power /usr/local/bin/labwc-greeter-power
```

Retain private backups of the existing helpers before replacing them. The
backend environment fix takes effect on the next button request because the
frontend is executed for each request. Updated UI feedback appears when the
next greeter session starts. No unit or AppArmor policy changed, so this helper
update requires neither a daemon reload nor a policy reload. Allow the normal
login/logout lifecycle to start the next greeter session; restarting greetd
from a running desktop can terminate that login.

For target acceptance, save work and return to the greeter, confirm each action
on separate boots, and check that it reaches the expected system worker and
single-force handoff. A request deliberately blocked by a known inhibitor or
another interactive login must show a failure while keeping that login safe.
An administrator can inspect bounded logs with:

```sh
sudo /usr/bin/journalctl --boot --no-pager --lines=100 --unit=greetd.service --unit=labwc-admin-action@989-greeter-reboot.service --unit=labwc-admin-action@989-greeter-poweroff.service
```

Use the actual numeric greeter UID if it differs from LPL-697's logged 989.
The deployment commands and real power acceptance were not executed in this
workspace.
