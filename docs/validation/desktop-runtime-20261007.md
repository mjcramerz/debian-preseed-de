# Desktop runtime and qBittorrent integration — 2026-10-07

## Evidence and scope

All 48 files under `todo/` were read: 26 contain data, 22 are empty, and the
nonempty files contain 12,880 lines. The inventory below records every file.
Private conversation content and credentials are not reproduced here.

The requested target is Debian Forky with systemd 261.2. Local validation uses
Forky/sid, Python 3.14.8, systemd 262-1, AppArmor 4.1.8-2, Bubblewrap 0.13.0-1,
slirp4netns 1.3.3-1, qBittorrent 5.2.4-1 and Mako 1.11.0-1. No software was
compiled or installed, no host AppArmor policy was loaded, and no installed
desktop service, router or tracker was changed. Private Xwayland remains
exclusive to Zoom and Discord.

## qBittorrent and the peer port

The supplied Tailscale service starts successfully. Its public-destination
connection warnings do not establish a daemon startup failure. The reported
tracker endpoints include host loopback, link-local and Tailscale addresses
because qBittorrent shared the host network without an interface binding.
The launcher now binds qBittorrent to private `tap0` at `10.0.2.100` and starts
packaged slirp4netns before releasing the application.

`LABWC_QBITTORRENT_PORT` controls the installed application configuration,
TCP and UDP slirp forwards and rendered nftables overlay. The existing P15s
profile's `50308` and other profiles' `50309` are preserved. The previous
fixed-50309 checks contradicted the P15s profile; installer and runtime now
validate canonical decimal ports in `1024..65535`.

For a profile selecting `50309`, the path is:

```text
Internet peer → router public TCP/UDP 50309
              → host LAN address TCP/UDP 50309
              → slirp4netns
              → private 10.0.2.100 TCP/UDP 50309
              → qBittorrent
```

The user confirmed both router transports are forwarded and that router rules
will be updated by the user when a profile selects another port. The launcher
selects an IPv4 source with a local `ip -j -4 route get` query, which sends no
test packet. Loopback/Tailscale routes, malformed replies and invalid sources
are rejected. Both host listeners and outbound sockets use the selected source.
Both forwards must be accepted before payload release. The API socket and
diagnostics remain in a private runtime directory outside the payload mount plan.

A real failure fixture exposed Bubblewrap's release-on-EOF behavior: stopping
only its outer process can release a blocked child during cleanup. Peer mode
pins the namespace init with a pidfd and kills it before closing the startup
pipe on failed setup. A real inert payload marker verifies cancellation.
Failure before obtaining that pidfd also reproduced payload execution. A
second inherited pipe now gates the fixed interpreter's exec on an explicit
readiness byte; EOF exits. The gate closes its extra descriptor and replaces
itself with the application, adding no long-lived process. Real Bubblewrap
fixtures verify both failed namespace pinning and successful readiness with
literal argument preservation. Network readiness is simulated in the success
fixture because TUN is unavailable.
Existing compatibility callers do not select this new mode.
[Bubblewrap 0.13 startup and descriptor handling](https://github.com/containers/bubblewrap/blob/v0.13.0/bubblewrap.c).

Repeated launches forward staged torrent paths or URIs through qBittorrent's
bounded QtLocalPeer IPC. They do not compete for a second pair of host listeners.
A mode-0600, owned, single-link regular-file lock serializes concurrent first
starts. Waiting requests use the first instance's IPC as soon as it is ready,
with a 30-second startup deadline. Real flock and Unix-socket fixtures cover
that handoff and refusal of symlinked or unsafe lock files.
Private-tracker configuration retains certificate validation, disables
DHT/PeX/LSD and UPnP/Web UI, clears a saved announce-IP override and uses normal
tracker failover. Remote tracker minimum intervals and account policies apply.
[qBittorrent 5.2.4 session settings](https://github.com/qbittorrent/qBittorrent/blob/release-5.2.4/src/base/bittorrent/sessionimpl.cpp),
[QtLocalPeer transport](https://github.com/qbittorrent/qBittorrent/blob/release-5.2.0/src/app/qtlocalpeer/qtlocalpeer.cpp),
[slirp4netns forwarding API](https://github.com/rootless-containers/slirp4netns/blob/master/slirp4netns.1.md).

## AppArmor wiring

The supplied AppArmor log has 431 policy load/replace records and 16 application
records: 11 qBittorrent opens and 5 qBittorrent helper executions. Those
application records are logged as `ALLOWED` with denied masks in complain mode;
they describe requests that would be denied under enforcement.

The entries at `todo/managed/security/apparmor/apparmor.log:434` onward refer to
sysfs `dev` leaves. Libtorrent reads device numbers and rotational/DAX hints to
classify storage. Mounted file I/O does not require raw disk access. The policy
permits only those read-only metadata leaves, including canonical NVMe and USB
paths, and inherited execution of the observed `xdg-open`, `hostname` and
`printf` helpers. The inherited execution avoids the existing no-new-privileges
transition failure. The payload receives no raw disk, TUN or host display-control
device. [Libtorrent drive classification](https://github.com/arvidn/libtorrent/blob/v2.0.11/src/drive_info.cpp).

The new slirp helper has a named transition, private API file permissions, Unix
stream permissions for its API/server and internal socketpair, and reciprocal
namespace-read and cleanup-signal permissions. The existing read-only process
observers have matching permissions for its new label. Only the helper gets
the TUN access and namespace capabilities needed for TAP setup. The payload
drops all kernel capabilities.

ChatGPT's wrapper can perform the exact document-portal mount-point method;
the payload can save through the portal mount and the selected standard save
directories. The idle wrapper can make the existing validated user-manager
handoff. All named transitions resolve, project includes have staging references,
and native offline parsing checks all 45 managed top-level policy sources.
These checks do not prove live kernel enforcement or every desktop user flow.

## Mako

At 15:15:37, the supplied journal starts an unmanaged notification activation
service while managed Mako waits. At 15:15:40 the managed daemon cannot acquire
the already-owned notification name. Later attempts repeat the same failure.

`dbus-broker-maintain`, the canonical producer of activation aliases, now writes
a root-owned mode-0644 service selecting `SystemdService=mako.service` with a
failing fallback Exec. It no longer links notification activation to vendor
`Exec=mako`. Package refresh preserves the single activation owner. The drop-in
sets `Type=dbus` and `BusName=org.freedesktop.Notifications`, retaining the
five-second delay. Installer verification requires the canonical activation file.
[D-Bus activation specification](https://dbus.freedesktop.org/doc/dbus-specification.html),
[Mako systemd unit](https://github.com/emersion/mako/blob/master/contrib/systemd/mako.service).

## Ctrl+Win+L

The compositor's filesystem isolation implies a private user namespace, where
root ownership can appear as the overflow UID. The hotkey enters a session-bound
user-manager service with `PrivateUsers=no` before reading policy. Environment
and socket identities are checked, and a forged handoff marker outside the
managed cgroup is rejected. Existing strict root ownership, type, mode and
bounded policy/state checks remain. Session pause/restore, concurrent-press
serialization and rollback are covered by fixtures; manual and before-sleep
locking remain. The namespace explanation is inferred from the service policy
and reported error, not an observed hotkey execution on the supplied host.
[systemd execution namespaces](https://manpages.debian.org/unstable/systemd/systemd.exec.5.en.html).

## DRM atomic failures

The eDP-1 errors occur at 15:16:02 and 15:22:32 in `todo/journalctl`. The first
coincides with a repeated failed Mako launch; the second follows USB arrival.
No output-watch mutation transaction is logged at either timestamp. The last
four commits concern peer-port publication, greeter power and GitOps; Mako's
delay was introduced in the preceding `d2d3011` commit. Temporal proximity
does not establish a kernel/wlroots root cause.

The notification activation race is repaired. Atomic modesetting, GPU policy
and output-watch serialization remain intact. The hardware atomic EBUSY errors
are **not verified resolved**. Fresh login, notifications, DPMS cycles and
USB/display hotplug on the installed host must determine whether a separate
driver issue remains.

## ChatGPT downloads

The ChatGPT log comes from LPL-346; compositor logs come from LPL-724. No direct
failed-download event is present. The repeated durable-thread sign-in,
external-agent ledger and missing-environment-ID errors are separate findings.

Two concrete save boundaries were repaired. Existing standard save directories
are writable binds into the private home. The document portal is activated with
`GetMountPoint` before the mount snapshot and its exact owned runtime path must
be available. The parser uses systemd's JSON `ay` format, validates byte types,
length and path, and reports transport failures. Matching AppArmor permissions
permit portal export and standard-directory saves. The whole host home is not
added to the mount plan.
[Document portal API](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.Documents.html),
[systemd 261.2 JSON byte-array serialization](https://github.com/systemd/systemd/blob/v261.2/src/libsystemd/sd-bus/bus-dump-json.c).

## Validation

Commands run from the repository root with bounded timeouts. Unit-test commands
use `python3 -B -m unittest discover -s d-i/forky/tests -p <pattern> -v`.

| Pattern | Outcome | Execution scope |
| --- | --- | --- |
| `test_compz_qbittorrent_followup.py` | 22 run; 21 passed, 1 skipped | Actual Unix IPC/API and flock fixtures, actual dash/ash firewall publication, and Bubblewrap startup/cancellation; mocked route/process orchestration and successful network readiness. Packet fixture skipped because this workspace lacks `/dev/net/tun`. |
| `test_dbus_broker.py` | 17 run; 15 passed, 2 skipped | Actual temporary activation publication; vendor ownership/diversion mocked. Root ownership fixtures skipped. |
| `test_idle_lock_20261001.py` | 25 run; 24 passed, 1 skipped | State, serialization, rollback and manager handoff fixtures. Actual-root policy fixture skipped. |
| `test_managed_app_review_20260921.py` | 30 passed | Actual temporary directory bind plans; document-portal replies/transport mocked. |
| `test_apparmor_incidents_20261004.py` | 21 passed | Native offline parser/effective masks, reciprocal policy and actual scalar publication; no kernel load. |
| `test_menu_apparmor_integration_20260919.py -k AppArmorIntegrationTests` | 5 passed | All 45 managed top-level policies parsed offline; transition/include/staging consistency. |

The focused total is 120 tests: 116 passed and 4 skipped. The private-Xwayland
suite has a known baseline failure at line 424: it asserts that an unchanged
preparation abstraction excludes `sys_ptrace`, although HEAD contains the grant.
The same single test fails in an isolated archive of HEAD. Its policy and tests
were not changed to silence the assertion.

### Snapshot integrity

`python3 -B tools/build.py` rebuilt 1,704 payload files and updated zero browser
artifacts. `python3 -B tools/build.py --check` reports that the snapshot, pins
and preseed are current. `python3 -B tools/check_shells.py` passes all 711
parser checks for 350 shell files. `git diff --check` passes.

A separate read-only archive comparison against HEAD verifies identical member
names and mode/UID/GID/timestamp/name/type/link metadata. Every new archive entry
matches both its source and manifest digest. Exactly these 15 payload members
changed, under `d-i/forky/`:

```text
hooks/target/etc/apparmor.d/abstractions/qbittorrent-runtime
hooks/target/etc/apparmor.d/desktop-utilities
hooks/target/etc/apparmor.d/desktop-wrappers.tmpl
hooks/target/etc/nftables/README.md.tmpl
hooks/target/etc/nftables/services/qbittorrent.yml.tmpl
hooks/target/etc/systemd/user/mako.service.d/10-labwc-session.conf
hooks/target/usr/local/bin/labwc-idle-toggle
hooks/target/usr/local/bin/labwc-qbittorrent
hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/network_namespace.py
hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/profiles.py.tmpl
hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/sandbox.py
hooks/target/usr/local/libexec/dbus-broker-maintain
scripts/desktop/detect.sh.tmpl
scripts/desktop/verify.sh.tmpl
scripts/late/security.sh
```

All 14 archive members whose names contain `xwayland` or `compat` match HEAD
exactly. The shared supervisor's new peer mode is used only by qBittorrent;
its existing compatibility callers retain their default behavior. Other
uncommitted paths are the focused tests, README/build status, this validation
record and the generated payload, manifest and preseed pins.

## Installed-target acceptance

The installer snapshot and pins have been rebuilt and checked. Refreshing
repository products does not update an already-installed desktop.

Verify the selected port in `/etc/labwc/desktop.conf`, the generated qBittorrent
configuration, both host listeners and effective firewall rule. Test incoming
TCP and UDP from outside the router; a same-LAN test cannot prove external NAT.
Check a private-tracker torrent's observed public address/peer port. Relaunch
after route/VPN changes. A router forward cannot make a VPN provider's different
public address accept traffic; that endpoint needs its own forwarding arrangement.

The implementation provides IPv4 host forwards. IPv6 peer forwarding and an
IPv6-only Internet connection are outside this slirp API contract. The host must
provide `/dev/net/tun` to the helper. The full inert packet fixture is available
but skipped here; real router/Internet seeding and leeching were not exercised.

Install/refresh the Mako canonical alias through the existing maintenance flow
and start a fresh login, so an old unmanaged daemon cannot retain the bus name.
Verify one Mako owner, idle pause/restore/manual lock, an actual ChatGPT download
to Downloads/Documents and a portal-selected destination, and kernel AppArmor
enforcement for these flows. No deployment occurred during local validation.

## TODO inventory

Each path was read. Empty files provide no evidence of a successful scan.

| Path under `todo/` | Lines |
| --- | ---: |
| `chatgpt/chatgpt.log` | 3500 |
| `journalctl` | 1270 |
| `mako` | 12 |
| `managed/apps/apps.log` | 243 |
| `managed/models/openai/chatgpt/chatgpt.log` | 0 |
| `managed/models/openai/chatgpt/runtime/codex-login.log` | 0 |
| `managed/models/openai/chatgpt/runtime/codex-tui.log` | 0 |
| `managed/models/openai/codex/codex-login.log` | 0 |
| `managed/models/openai/codex/codex-tui.log` | 0 |
| `managed/models/whisper/whisper.log` | 1 |
| `managed/security/apparmor/apparmor.log` | 449 |
| `managed/security/apparmor/modes.log` | 81 |
| `managed/security/audit/auditd.log` | 4657 |
| `managed/security/auth/auth.log` | 49 |
| `managed/security/chkrootkit/chkrootkit.log` | 0 |
| `managed/security/chkrootkit/daily.log` | 0 |
| `managed/security/chkrootkit/daily.log.raw` | 0 |
| `managed/security/chkrootkit/log.expected` | 0 |
| `managed/security/clamav/clamav.log` | 0 |
| `managed/security/clamav/freshclam.log` | 0 |
| `managed/security/clamscan/clamscan.log` | 0 |
| `managed/security/crowdsec/crowdsec-firewall-bouncer.log` | 18 |
| `managed/security/crowdsec/crowdsec.log` | 150 |
| `managed/security/crowdsec/crowdsec_api.log` | 163 |
| `managed/security/debsecan/debsecan.log` | 0 |
| `managed/security/debsums/debsums.log` | 0 |
| `managed/security/fail2ban/fail2ban.log` | 19 |
| `managed/security/lynis/lynis-report.dat` | 0 |
| `managed/security/lynis/lynis.log` | 0 |
| `managed/security/lynis/scan.log` | 0 |
| `managed/security/nftables/nftables.log` | 83 |
| `managed/security/rkhunter/rkhunter.log` | 0 |
| `managed/security/rkhunter/scan.log` | 0 |
| `managed/security/spectre-meltdown-checker/spectre-meltdown-checker.log` | 0 |
| `managed/system/fwupd/security-scan.log` | 0 |
| `managed/system/initramfs/01-init-top.log` | 49 |
| `managed/system/initramfs/02-init-premount.log` | 53 |
| `managed/system/initramfs/03-local-top.log` | 55 |
| `managed/system/initramfs/04-local-block.log` | 5 |
| `managed/system/initramfs/05-local-premount.log` | 25 |
| `managed/system/initramfs/06-local-bottom.log` | 33 |
| `managed/system/initramfs/07-init-bottom.log` | 85 |
| `managed/system/kernel.log` | 941 |
| `managed/system/storage/storage.log` | 0 |
| `managed/system/system.log` | 838 |
| `managed/system/timeshift/timeshift.log` | 4 |
| `managed/system/usb/usb.log` | 92 |
| `managed/system/zram/zram.log` | 5 |
