# Desktop and private-network incidents — 2026-10-09

Target: Debian Forky with systemd 262. This record separates repository changes,
supplied installed-system evidence, and remaining runtime verification.

## 1. Thunar

Both Waybar Files entries now use the managed Wayland launcher. The launcher
owns the GL workaround, native volume-monitor environment, session binding and
transient-service collection. It no longer starts `thunar.service` as a launch
dependency. D-Bus activation uses `Thunar --gapplication-service`, matching the
package's D-Bus activation command, instead of the persistent `--daemon` mode.
The primary process can finish after its windows and file operations finish.
The existing `ExitType=main` and bounded cgroup cleanup remain in place.

Thunar's built-in volume management is disabled because the managed GVfs monitor
already owns removable-drive actions. This removes the duplicate thunar-volman
device-handler path that emits the supplied USB/UAS/disk warnings.

Successful collected transient units are unloaded; a later `systemctl status`
lookup by their old UUID can therefore report that the unit is absent. Native
window closure and USB sidebar behavior still need installed-desktop verification.

## 2. qBittorrent

The two capture pairs cover different time windows. They establish successful
peer connections, but contain no decoded piece requests or piece transfers:

- `qbittorrent.pcapng`, frames 28/30/32, 52/54/56 and 73/75/77: TCP BitTorrent
  handshakes and availability messages cross the private network. The local
  client advertises HaveAll; the remote endpoint subsequently closes.
- `host.pcapng` and `host.txt`: UDP/uTP connections exchange BitTorrent
  handshakes, including frames 169/177 and 347/349/356. Some sessions advertise
  HaveAll at both ends; frame 349 instead advertises HaveNone locally.
- Host frames 341–346 show an inbound TCP handshake on port 50309 followed by a
  remote close without application payload. This alone does not prove a peer
  transfer or distinguish a peer from a port check.
- `qbb` confirms host PID/namespace PID separation, `eth0` at 10.203.0.2/30,
  default routing via 10.203.0.1, and TCP plus UDP listeners on port 50309.
- The October 9 execution log reports both listeners and successful resume-data
  saves on exit. Its repeated configuration-write errors are dated August 1.
  Torrent names, hashes, tracker URLs and credentials are omitted here.

The production nftables broker already allows peer TCP/UDP egress over the
selected route, established replies, and exact TCP/UDP peer DNAT. Its source-port
mapping preserves the advertised listener for uTP. AppArmor permits stream and
datagram sockets. There is no BitTorrent payload filter in that path.

Production changes now require an online peer-port policy and an exactly matching
broker response before starting qBittorrent. The advertised tracker port uses the
same policy port. Existing managed Wayland qBittorrent cgroups are recognized, so
they do not create a second transient service. Direct launches use `UMask=0077`.

The persistent managed profile also enforces:

| Setting | Managed value |
| --- | --- |
| Peer protocol and encryption | TCP plus uTP; encryption allowed |
| Peer interface/address | The broker's private `eth0` and current lease address |
| Advertised/listening port | The broker's configured TCP/UDP peer port |
| Global/per-torrent connections | 500 / 100, the upstream defaults |
| Global/per-torrent upload slots | Unlimited |
| Global ratio, seeding-time and inactive-seeding limits | Disabled |
| Outgoing source-port range | Kernel-selected ports |
| Automatic additional tracker lists | Disabled |
| DHT, PeX, LSD, UPnP, WebUI | Disabled |
| HTTPS tracker validation and SSRF mitigation | Enabled |
| File log | `/home/user/.local/share/qBittorrent/logs` in the private persistent home |
| File-log rotation | 5 MiB, backups enabled, seven-day age cleanup at startup |

Configuration input is bounded to 1 MiB and must be a singly linked regular file
owned by the invoking user. Symlinks and special files are rejected. Parse errors
do not print configuration contents. Existing correct settings preserve the file
instead of replacing it; permissions are tightened to 0600. Changed settings
retain the existing atomic, fsynced replacement path and unrelated preferences.
Unused pre-veth route helpers and their tests were removed; route selection and
revocation remain owned and tested in the broker.

The user subsequently reports that upload now works on the installed system.
This is live seeding evidence from the user; it does not identify which repository
snapshot was deployed or establish a fresh-install result. Per-torrent stopped
states, file selection and share limits are not rewritten behind the GUI.

Settings were checked against the primary
[qBittorrent 5.2.4 session implementation](https://github.com/qbittorrent/qBittorrent/blob/release-5.2.4/src/base/bittorrent/sessionimpl.cpp)
and [file-logger configuration](https://github.com/qbittorrent/qBittorrent/blob/release-5.2.4/src/app/application.cpp).

## 3. Browser AppArmor and mounts

The generic browser profiles can read `/etc/opt/chrome/` and its files. Owner
directory writes allow Chrome/native-messaging directory probes in synthetic
`/etc`; policy files receive no write grant. Chromium, Edge and Vivaldi bind an
existing host Chrome directory read-only. No browser executable or broad recursive
write access was added. Kernel policy reload and a Vivaldi launch remain deployment
checks.

## 4. Waybar

The supplied UnknownObject and cancelled-layout messages coincide with
qBittorrent's orderly exit at 20:11:39. A disappearing tray object during an
asynchronous query is consistent with this timing. This is an inference, not a
proved root cause. No package-level tray-race fix was established under the
constraint against source builds; the tray and its useful diagnostics remain.

## 5. Foot and DRM

The 19:58:00 atomic EBUSY follows a Foot SIGHUP by milliseconds. Another atomic
failure occurs at 20:11:27 without a corresponding Foot exit. The evidence does
not establish SIGHUP as the cause. Profiles already disable direct scanout, and
output-watcher fixture checks cover idempotent transactions. They do not exercise
real DRM atomic commits. No speculative global legacy-KMS or GPU workaround was
introduced; this incident remains open for hardware reproduction.

## 6. External drives

The monitor uses `GLibUnix.signal_add` with the GLibUnix 2.0 namespace. A subprocess
test drives an actual GLib loop, sends SIGTERM and verifies orderly shutdown while
treating PyGI deprecation warnings as errors. Native USB operations are separate
from this signal test.

## 7. Bounded cleanup and validation

Waybar terminal, notes, disk-usage, CPU/memory, Tuta and Sleek callbacks now invoke
their existing managed entrypoints directly. Redundant outer launcher/services
were removed. No Xwayland configuration was changed and no software was compiled
from source. Installer payload generation uses the existing packaging tool.

The final combined run selected 237 tests: 230 passed, seven skipped, no failures.
Six native D-Bus fixtures were skipped because `dbus-daemon` is unavailable. The
isolated veth transfer fixture was skipped because this environment denies the
`net.ipv4.ip_forward` sysctl write even inside its private namespaces. Retrying
that fixture with escalation produced the same restriction. Other native kernel
fixtures and offline nftables/AppArmor parsing passed. The transfer fixture's
TCP/UDP payload assertions were not executed; packet evidence from the supplied
installed system remains distinct from those tests.

The initial combined run found an outdated assertion expecting btop properties in
Waybar's removed outer service. The corrected check follows the terminal launcher
and verifies the properties on its actual managed Foot/Kitty/fallback service.
The final combined run passed:

```sh
env PYTHONPATH=d-i/forky/tests python3 -B -m unittest -q \
  test_compz_qbittorrent_followup \
  test_kernel_veth_networking \
  test_apparmor_incidents_20261004 \
  test_thunar_native_drive_actions \
  test_managed_app_review_20260921 \
  test_atomic_output_r3_20260921 \
  test_attached_incidents_20260929.TorrentServiceTests \
  test_log_launchers_20260915_r3.AppArmorCoverageTests.test_gtk_apps_follow_appearance_mode_and_thunar_disables_gl \
  test_log_launchers_20260915_r3.AppArmorCoverageTests.test_thunar_hotkeys_and_files_menu_use_the_same_managed_entrypoint \
  test_desktop_integration_20260914.ServiceAndNotificationTests
```

Additional exact checks and outcomes:

| Command | Observed result |
| --- | --- |
| `python3 -B tools/build.py` | Built 1,728 payload files; updated zero browser artifacts |
| `python3 -B tools/build.py --check` | Snapshot, pins and preseed current |
| `python3 -B tools/check_shells.py` | 350 shell files; 711 parser checks; PASS |
| `git diff --check` | Passed |

`payload.tar.gz`, `payload.manifest` and `preseed.cfg` were regenerated together.
These checks do not imply deployment, a successful fresh installation, native USB
removal, private tracker piece transfer, or successful real DRM atomic commits.

## Follow-up: all supplied AppArmor paths and power ordering

The new denial set is represented in the existing anonymized fixture (38 raw
records, repeated equivalent requests deduplicated). Every supplied file request
is replayed against compiler-expanded permissions, including create/delete to
write mapping and executable-memory mapping. All 46 repository policy files,
including their nested profiles, pass the native offline parser; no kernel policy
was loaded by the tests.

Shared corrections:

- `desktop-runtime`: inherited `hostname`, `file` and `expr` execution through
  both `/bin` and `/usr/bin`; read-only file magic data; owner-only home-directory
  metadata writes; read-only USB interface-name leaves.
- `electron-runtime`: Chromium configuration reads and executable mapping of
  only the named browser-owned Widevine CDM library.
- `bwrap-desktop-runtime`: PulseAudio metadata writes on the application-owned
  directory. Mount construction binds the native socket into a private parent,
  rather than binding the host Pulse directory. The direct Postman profile's
  host Pulse directory remains read-only in the effective-policy check.
- `labwc-app//app-bwrap`: the already persistent Postman file tree receives
  matching owner-only access. Existing direct Postman rules already cover it.
- `session-controls` and its image-loader child: owner-only reads of scoped
  browser notification `icon.png` files. Other filenames, nested paths, other
  owners and unrelated application temp trees are excluded by the checks.

The qBittorrent reinstall audit traced the policy renderer, broker unit and
enablement, forwarding sysctl, resolved listener, desktop launcher staging and
startup gate. The policy port reaches application listening, tracker advertisement
and exact TCP/UDP NAT. The desktop role publishes the managed package once;
the early Podman subset is staged only for non-desktop targets. No additional
peer-forwarding change was needed in this follow-up.

For both Waybar and greeter reboot/poweroff, the shared worker uses this order:

1. Desktop save/close preparation where applicable, guest drain and sharing stop.
2. External-drive sync/unmount/power-off through the confined PID-1 oneshot.
3. Verify inactive completion, successful Result and `ExecMainStatus=0`.
4. Stop greetd, terminate the user session, then drain managed swap/storage.
5. Re-inventory external drives before the final single-force PID-1 handoff.

`terminate_user()` now independently rejects reboot/poweroff if successful
external-drive preparation is absent. A first drive-preparation failure leaves
greetd and user teardown unstarted. The second inventory covers drives arriving
during cleanup. These are command-intercepted ordering and failure tests; they
do not perform a real power operation or USB removal.

Final follow-up checks selected 287 tests: 286 passed, one skipped, no failures.
The skip remains the isolated veth transfer fixture's denied forwarding sysctl.
The native systemd verifier parsed the drive-service settings with an inert
executable and dependency stub. Exact follow-up test command:

```sh
env PYTHONPATH=d-i/forky/tests python3 -B -m unittest -q \
  test_compz_qbittorrent_followup \
  test_attached_incidents_20260929.TorrentServiceTests \
  test_kernel_veth_networking \
  test_managed_app_review_20260921 \
  test_apparmor_incidents_20261004 \
  test_power_force_contract \
  test_greeter_power_followup_20260922 \
  test_power_runtime_20260920 \
  test_desktop_integration_20260914.ExternalDriveFlowTests \
  test_installer_hardening.LifecycleTests.test_desktop_managed_app_validation_needs_no_stat_applet
```

The final follow-up rebuild again contains 1,728 payload files. Snapshot/pin checks,
350-file/711-parser shell checks and `git diff --check` all pass after the final
production edits. The validation commands did not reload the installed LPL-541
policy or perform a fresh unattended installation.
