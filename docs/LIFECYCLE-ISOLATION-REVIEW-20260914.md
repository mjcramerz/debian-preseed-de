# Lifecycle and isolation review - 14 September 2026

This pass starts from `debian-preseed-de-updated.tar.gz`, not the original ZIP.
The pre-implementation hash baseline has 1,685 regular files. The review record
was written before source edits and inventories 99 service definitions,
templates and drop-ins. See `validation-lifecycle-20260914/` for that record,
the per-unit decision inventory, source changes and the new validation results.
Earlier dated validation directories remain historical; their results do not
certify this revision. No application, library, kernel or systemd was compiled.

## 1. Review scope and decisions

The review traced private-initrd SSH inputs, temporary-agent supervision,
pipe/memfd passphrase transport, GPG sealing, askpass and pinentry transitions;
Labwc ownership and desktop shutdown ordering; normal/devops identity access;
Codex home cloning and the existing Bubblewrap boundary; GitOps policy parsing,
locks, publication and recovery; debugsys collection and initramfs transactions;
pkexec/system-manager power authorization and the separate save/lock/commit
phases; transient application lifetime and AppArmor signal peers.

Changes are limited to demonstrated inconsistencies and four PID-namespace
candidates. The installer storage choices, hardware tuning policy, application
launch architecture, authorization policy, Codex sandbox design and unrelated
vendor-service hardening are not redesigned.

## 2. PrivatePIDs allowlist

`PrivatePIDs=yes` is enabled only in these system-manager services:

| Service | Why PID isolation is feasible | Boundary deliberately preserved |
| --- | --- | --- |
| `bluetooth-controller-init.service` | Foreground, bounded controller initialization; no host-process inspection or PID-file protocol. | Host Bluetooth controller access and existing `CAP_NET_ADMIN CAP_NET_RAW`; `PrivateUsers=no`. |
| `managed-nvidia-char-links.service` | Foreground character-device link reconciliation; no external PID consumers or daemon fork. | Existing host `/dev` view, empty capability bounding set and filesystem policy; `PrivateUsers=no`. |
| `zram-writeback.service` | Foreground maintenance uses sysfs, aggregate memory/pressure data and filesystem locks, not host PIDs. | `ProcSubset=all`, existing backing-device/I/O policy and host sysfs permissions; `PrivateUsers=no`. |
| `zram-writebackd.service` | Foreground PSI loop; preflight and daemon do not exchange PID state. | The same aggregate proc/sysfs contract, existing restart/stop bounds and control-group cleanup; `PrivateUsers=no`. |

Each has `KillMode=control-group` and a bounded stop timeout. The scripts now
explicitly handle termination as namespace init. Perl's existing daemon-local
graceful stop handlers still override the wrapper defaults while running.
The one-shot jobs and daemon use their existing activation paths; no new service
is enabled and no hardware action is triggered merely by installing this code.

systemd introduced `PrivatePIDs` in version 257. It gives each Exec process a
separate PID namespace and remounts proc for that view. When namespace init exits,
the kernel terminates the remaining processes in that namespace; this is why
`Type=forking` is excluded. The feature is not an independent security boundary
when the kernel/service manager cannot provide it. A parsed property alone is
not proof that the kernel created a namespace. [S1]

### PrivateUsers is not applied as a blanket hardening option

No new `PrivateUsers=yes`, `self`, `identity` or `full` setting is introduced.
An identity UID/GID map can still remove all capabilities in the host user
namespace; appearing as root inside it is not equivalent to host root. In v257,
`identity` maps the first 65,536 IDs; newer modes are version-dependent. Keep the
explicit `PrivateUsers=no` on the selected hardware workers and host handoff
paths. Existing unit-specific capability bounding sets remain in force. [S1,S2]

### Explicit exclusions

The power worker, forking screen-lock transient, debugsys boot collector, tmpfs
pre-clean, SSH agent and key loader explicitly retain host PID/user semantics.
The pre-clean helper reads `/proc/1/mountinfo`; a private PID 1 would change its
meaning. The lock uses `Type=forking` and must survive its readiness parent.
Diagnostics need host process visibility, while power authorization/handoff
needs genuine host credentials. The loader shares the user GPG/desktop context.

The compositor, terminals, launcher/broker families, vendor daemons, firstboot,
package/update jobs and container managers are not changed speculatively.
Terminal privilege transitions, PID ownership guards, delegated cgroups,
subordinate IDs, nested Bubblewrap/slirp and package-specific hooks must not be
broken for a better-looking hardening score. Per-unit exclusions/deferments
are listed in the machine-readable pre-implementation inventory.

## 3. SSH, GPG and AppArmor corrections

Agent socket and service drop-ins now require an already active, ordered Labwc
session and bind their lifetime to the compositor. `PartOf` continues to propagate
session stop/restart; stale user-manager environment alone cannot reactivate the
agent outside the session. Vendor `ExecStart`, socket activation and socket modes
are not replaced. The agent has explicit group cleanup and no core dumps.

`git-ssh unlock` now verifies an actual `ssh-add -T` signing operation after the
loader start. A successful systemctl transaction can mean an ExecCondition was
skipped; that is no longer reported as an unlocked identity. Devops already calls
this same command and inherits the correction. Status validates the managed
identity/socket. Lock does not depend on intact key files and can stop the agent
and loader even after key deletion or corruption. Root invocation is rejected.

Private credential directories require mode 0700. Public-key rereads accept
0600 or 0644, while encrypted private-key/ciphertext reads still require 0600.
Atomic pair-update rollback preserves existing contents and modes. Installer
command pipes are explicitly closed after child-group cleanup. The encrypted
OpenSSH key, GPG ciphertext and private-initrd-only secret handling are retained.

The AppArmor loader and transitioned pinentry profiles now have complementary,
exact-peer TERM/KILL/INT/HUP and CHLD permissions. This fixes a lifecycle gap
without a blanket signal, home-tree or Internet permission. Policy source parsing
is separate from live enforce-mode acceptance.

The GitHub/GitLab host keys are unchanged. The GitLab public key matches its
official published entry; the GitHub key matches its published fingerprint.
The stale provenance comment now points to the actual operations guide. [S3,S4]

Codex retains `mcr/main`, the approved GitLab SSH URL and the main repository
HEAD. Its normal sandbox still creates a private `/run`, hides the user's home
and strips the SSH-agent variables; the stronger mount boundary matters, not
only removing an environment variable. The existing explicit `--no-bwrap`
escape remains an intentional loss of that sandbox boundary and is not changed.

## 4. GitOps, power and diagnostics

GitOps installs TERM/HUP handlers so cancellation unwinds the supervised Git
process-group cleanup and repository lock. Interruptions do not trigger a hard
reset or a force-push. Recovery references remain available, and after an
interruption the user should inspect status before retrying. This does not make
SIGKILL or power loss transactionally recoverable.

Noncanonical protected paths (`./`, doubled separators or dot components) now
fail instead of silently missing the user's intended files. Rooted trailing-slash
directory globs protect every matching subtree, including a source blob replacing
a protected directory and locally absent protected paths. Both policy lists are
still data-only and independent, and preview remains the default. Synchronization
is still explicit source-tree replacement outside protected paths, not a generic
three-way merge preserving every unlisted local customization.

Power transport cleanup now runs on success, timeout, cancellation and unexpected
communication/decoding errors, reaping the entire local bridge process group and
closing pipes. Authorization, protection of other users, save/cancel preflight,
lock-readiness checks, teardown ownership and the existing single-force final
power-request logic are unchanged. No polkit grant or sudo bypass is added.

Debugsys now records PID/user namespace settings, main PID, cgroup, stop policy
and source/drop-in metadata for the selected units, plus managed-agent lifecycle
properties and bounded UID/GID maps. It does not collect manager Environment
properties or private-key content. These results are included in the overview.
The dynamic root-filesystem probe now uses the report's remaining-time budget.
The interactive collector still enters through `sudo -i`; initramfs enable/remove
transactions, confirmation, rollback and the default unarmed state are retained.

## 5. Target acceptance and operational checks

Use a disposable target before deployment. This build requires systemd 257 or
newer for PrivatePIDs. First check unit loading and the effective settings:

```sh
systemd --version
systemctl show bluetooth-controller-init.service managed-nvidia-char-links.service \
  zram-writeback.service zram-writebackd.service \
  -p LoadState -p PrivatePIDs -p PrivateUsers -p ProcSubset -p KillMode -p Result
```

While the zram daemon is actually running, verify namespace inodes and kernel PID
mapping, not only systemd configuration. A skipped condition is not a runtime pass.

```sh
pid=$(systemctl show -p MainPID --value zram-writebackd.service)
case "$pid" in ''|0|*[!0-9]*) echo 'daemon is not running';; *)
  sudo grep '^NSpid:' "/proc/$pid/status"
  sudo readlink "/proc/$pid/ns/pid" /proc/1/ns/pid
  sudo readlink "/proc/$pid/ns/user" /proc/1/ns/user
  ;;
esac
```

The last namespace PID should be 1; PID namespace inodes should differ, while the
user namespace should remain the host's. Inspect service journals and AppArmor
denials; confirm zram PSI/meminfo reads, lock behavior and sysfs writes, controller
initialization, device links and bounded service stop/restart. Exercise oneshots
only when their real hardware prerequisites are present; do not fabricate devices.

In a real desktop, test cold/warm/cancelled GPG pinentry, retry through both
`git-ssh unlock` and devops, `git-ssh lock` with incomplete key metadata, shared
agent access, real GitHub/GitLab authorization and agent disappearance at logout.
Confirm the Codex sandbox cannot see the host agent socket. Test power denial and
save cancellation before committed logout, then suspend with a working lock and
finally authorized reboot/shutdown. Verify other interactive users block power
operations. Do not test real power actions on a production host during review.

```sh
debugsys report --categories security credentials
debugsys status
```

The first command is read-only and uses the root login collector; reports can
still contain sensitive journals, addresses and names. Inspect before sharing.
Complete the guide's arm/rebuild/boot/remove/rebuild/boot sequence for initramfs
capture on a disposable target. No offline test certifies bootability.

If a target-specific namespace restriction prevents a selected service starting,
use a narrowly scoped unit drop-in containing `[Service]` and `PrivatePIDs=no`,
reload the manager, and repeat that service's acceptance checks. Do not compensate
by enabling PrivateUsers, weakening AppArmor globally or relaxing capabilities.
Keep a known-good boot path and deploy matching rendered assets/payload hashes.

## 6. Evidence and limits

The accompanying validation report provides exact commands, counts, failures,
skips and packaging hashes. Test stubs prove control flow, not a real desktop or
hardware. The systemd parser fixture preserves reviewed directives/order but uses
stub executables and dependencies; it is not vendor-unit or kernel activation.
The validation container is not booted with systemd as PID 1 and denies creation
of PID namespaces (`unshare: Operation not permitted`). AppArmor source parsing
does not load policy into the kernel. Real provider login, graphical pinentry,
service activation, hardware behavior, initramfs rebuilding and reboot remain
explicit target acceptance gates.

## Primary references

[S1] systemd v257 systemd.exec (PrivatePIDs, PrivateUsers, proc and mount semantics):
https://raw.githubusercontent.com/systemd/systemd/v257/man/systemd.exec.xml

[S2] systemd v258 systemd.exec (versioned mapping-mode comparison):
https://raw.githubusercontent.com/systemd/systemd/v258/man/systemd.exec.xml

[S3] GitLab.com settings and published SSH host keys:
https://docs.gitlab.com/user/gitlab_com/#ssh-host-keys-fingerprints

[S4] GitHub SSH host-key fingerprints:
https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints
