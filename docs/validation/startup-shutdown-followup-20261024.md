# Reported startup and shutdown messages — 2026-10-24 follow-up

## Scope

Follow-up to the user's nine quoted journal lines: Tailscale IPv6 peerAPI
binding, hardware tuning dependency failures, masked Power Profiles activation,
PAM session release, and NetworkManager dispatcher shutdown notifications.
This supersedes the source dispositions for those rows in
`todo-failures-20261024.md`; its older artifact hashes describe that earlier
snapshot. All other uncommitted work was preserved. Xwayland and manual
CrowdSec Console enrollment were not changed.

Base revision: `5926f21a0ac7c8ef331cc4011c3e7fc06c01cffa`, branch `mcr/main`.
The five changed source/fixture files below have aggregate SHA-256
`4db2e044670f5be39a43170195fb7a30013c136524ed5257abf9804868640b75`,
calculated in sorted path order as `path + NUL + bytes + NUL`.

## Findings and changes

### Hardware tuning dependency failures: prior fix retained

`todo/journalctl:2306` records mode application losing
`/etc/apparmor.d/firstboot`; lines 2360–2367 record the resulting AppArmor
failure and both dependent hardware jobs failing. The existing
`Requires=apparmor-modes.service` is correct and remains mandatory.

The preceding source fix makes secondboot retire the fixed firstboot policy
through `apparmor-modes-run --retire-firstboot`, under the same
`Managed::PolicyLock` as the mode writer. A busy writer returns 75 and preserves
secondboot's retry infrastructure. This follow-up retains that fix in the
rebuilt payload. It does not treat missing enforced policy as success or add
an ordering cycle through firstboot/secondboot.

### Tailscale IPv6 bind: private namespace setup changed

The first boot serves an IPv6 listener (`todo/journalctl:1098`). The next
boot reports EADDRNOTAVAIL at line 2788 and immediately serves through
netstack at line 2789. These records do not prove a Tailscale connectivity
failure, nor do they record the address flags at the failed bind. Address
installation or DAD timing is an inference, not a captured native diagnosis.

The upstream [Tailscale 1.104.1 peerAPI implementation](https://github.com/tailscale/tailscale/blob/v1.104.1/ipn/ipnlocal/peerapi.go)
attempts the kernel listener and falls back to netstack on this error. Its
[Linux router implementation](https://github.com/tailscale/tailscale/blob/v1.104.1/wgengine/router/osrouter/router_linux.go)
installs interface addresses without an explicit NODAD flag. The exact
installed Tailscale package version is not present in the quoted capture;
the repository's policy comments identify 1.104.1 as its reviewed integration.

`d-i/forky/hooks/target/usr/local/libexec/tailscale-netkit` now sets
`net.ipv6.ip_nonlocal_bind=1` in the newly constructed private network namespace
before launching tailscaled. The existing `nsenter` call uses the pinned
namespace descriptor and passes that descriptor explicitly. This permits the
kernel bind while an IPv6 address is not yet usable, as defined by the
[kernel IP sysctl documentation](https://docs.kernel.org/networking/ip-sysctl.html).
It does not add an address, change forwarding routes or disable IPv6/DAD.

`d-i/forky/hooks/target/etc/apparmor.d/usr.sbin.tailscaled` permits access to
that exact sysctl only in the constructor profile. The daemon does not gain
sysctl write permission. Host and physical-interface sysctl settings are not
changed by this new operation. Existing peer authorization, packet policy,
namespace ownership checks and netstack fallback remain.

This is a source correction for the reported unavailable-address bind. It is
not native acceptance of the listener, Taildrop, Tailscale SSH or remote
connectivity. No new log suppression was added.

### PAM session release: manager close precedes terminate-user

The capture identifies session 3 as the user manager's own manager-class
session (`todo/journalctl:1192`). During shutdown it is removed at line 1737
before its PAM close reports NoSuchSession at line 1738. The previous worker
called `loginctl terminate-user` before stopping the user manager, allowing
logind to remove the manager session before sd-pam released it. The target's
[systemd 262 PAM close implementation](https://github.com/systemd/systemd/blob/v262/src/login/pam_systemd.c)
reports an error when ReleaseSession finds the session already absent.

`d-i/forky/hooks/target/usr/local/libexec/labwc-admin-action-worker` now first
requests a synchronous stop of the selected `user@UID.service`, then terminates
the user's remaining logind sessions and queues the final manager/slice stop.
This order applies to logout and machine power actions. The stop transport is
bounded at ten seconds; shutdown uses the existing shared 45-second cleanup
deadline. A failed/expired stop remains visible and cleanup continues.

The PAM stack, logind cleanup settings, selected account boundary and cgroup
termination authority remain intact. There is no claim that unrelated
external session termination can never race a PAM close.

### NetworkManager STOPPING notification: drain before forced handoff

`todo/journalctl:1767–1774` shows the explicit single-force reboot handoff,
PID 1 entering shutdown, then the dispatcher's STOPPING notification failing
with Connection refused. The [upstream dispatcher source](https://github.com/NetworkManager/NetworkManager/blob/main/src/nm-dispatcher/nm-dispatcher.c)
sends that notification while releasing its bus name. The persistent
dispatcher already has correct ordering relative to NetworkManager, but
single-force shutdown skips the ordinary unit stop transaction.

The same power worker now requests a bounded stop transaction for present
`tailscaled.service`, `NetworkManager.service` and
`NetworkManager-dispatcher.service` before the force request. Existing
After/Before edges drain Tailscale before NetworkManager, then NetworkManager
before the dispatcher. This occurs after application/external-drive and NFS
cleanup, while PID 1's notification receiver and system bus are still alive.
Absent optional units are skipped through the existing load-state checks.

The shared cleanup deadline, final sync and exactly one single-force handoff
remain. Failure cannot veto shutdown or trigger a second power mutation.
If cleanup times out or the manager is unavailable, forced shutdown can still
produce teardown diagnostics; no absolute absence claim is made.

### Masked Power Profiles activation: superseded by the custom API

The subsequent [Power Profiles integration](hardware-power-profiles-20261024.md)
replaces the masked public-service approach for newly staged custom Intel
installs. The paragraphs below record the earlier snapshot and are not the
current provider design.

`todo/journalctl:1323` records a client attempting PPD activation while custom
tuning owns CPU policy. The thermal interlock then refuses the custom profile
at line 1356; owned hardware is restored and PPD starts at lines 1366–1367.

`hardware_tuning/policy_owner.py` intentionally masks/stops PPD before custom
CPU writes, and only unmasks/starts it while holding the hardware ownership
locks after journals are empty. Removing the mask would allow competing CPU
policy writers. The mask and thermal protection are preserved.

GLib's [D-Bus power-profile monitor](https://github.com/GNOME/glib/blob/main/gio/gpowerprofilemonitordbus.c)
uses automatic service activation, which can encounter this intentional
exclusion; the capture does not identify which client made this request.
This particular activation refusal has **not** been eliminated. It does not
mean PPD is permanently broken; the successful handback is recorded. No
synthetic PPD provider, global monitor disablement or broad warning filter
was added to conceal it.

## Changed paths

- `d-i/forky/hooks/target/usr/local/libexec/labwc-admin-action-worker`
- `d-i/forky/hooks/target/usr/local/libexec/tailscale-netkit`
- `d-i/forky/hooks/target/etc/apparmor.d/usr.sbin.tailscaled`
- `d-i/forky/tests/test_power_force_contract.py`
- `d-i/forky/tests/test_tailscale_netkit_20261017.py`

Existing focused fixtures now describe manager-before-session ordering,
network cleanup before the final handoff, continued handoff after a stop
failure, and private-namespace-only IPv6 nonlocal binding. They were not run.
Both requested read-only sidecars failed at initialization with
`invalid_encrypted_content`; all findings and integration were performed by
the root agent, with no claim of independent review.

## Checks actually completed

- Source and caller inspection, exact saved-journal correlation and public
  upstream source review. No target or development-host service queried.
- Inline `/usr/bin/python3 -I -S -B -`, using standard-library `ast.parse`
  on the two Python helpers and two fixture files. Source was treated as data;
  no repository import, native syntax checker or runtime helper executed.
- Static contract inspection of manager/session order, common cleanup budget,
  one force request, namespace descriptor/argv wiring, constructor-only
  AppArmor grant, existing network stop edges and retained PPD exclusion.
- `git diff --check`: exit 0.
- Reviewed Makefile/build/publication path, then
  `make build PYTHON=/usr/bin/python3`: exit 0, 1,830 members.
- Bounded standard-library streaming tar comparison: all 1,830 members,
  34,867,373 expanded bytes match the current source and manifest; fixed archive
  metadata and private-input name exclusion hold. Preseed pins agree with the
  archive, manifest and bootstrap source hashes.

Generated SHA-256 values:

```text
payload.tar.gz   7be572aa4843c2e32c792824fafebd4532e56a405f022975445dd21853df1fc9
payload.manifest 442d00581537788aa7f72d7c7d2b0128474c5c36ff0dbf81c4a81aa5a58fc37f
preseed.cfg      4936d33bf952c8e9eb269e21631ddd005bcd21a51fab49a071f301a45d7799f7
```

No test suite, native AppArmor parser, systemd validator, service operation,
package installation, reboot, account or credential operation was performed.
Fresh-install/second-boot behavior and live shutdown/IPv6 listener acceptance
remain unverified. The root offline inventories were not regenerated and are
stale relative to this payload. Changes remain uncommitted and undeployed.
