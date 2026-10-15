# Managed logs, Chromium GPU initialization and service coverage

## Scope and evidence boundary

Target: unattended Forky desktops using systemd 262. The checkout was clean
before this work. All 49 files under `todo/managed/` were read as data:
7,294,249 bytes, 31,204 physical lines and 22 empty files. Supplied records
describe the installed machine; they are not results from running this patch.
No development-host configuration, services, package state, security policy,
networking or devices were used for tests or changed.

The prepared disposable VM required by `AGENTS.override.md` was not available
in this session. Tests, shell validators, native policy parsers, CrowdSec
validation and browser launches were not run. Static inspection and pure
installer serialization are reported separately below.

## 1. Chromium GPU initialization

`apps/apps.log:180` precedes the reported EGL errors with ANGLE's failure to
open native `libEGL.so.1`: `Permission denied`. Three GPU processes then exit
during initialization at lines 192, 205 and 220. Audit event 9121 records the
installed Vivaldi launch with a render-node bind and
`--gpu-sandbox-start-early`. The AppArmor capture contains 433 STATUS events
and no DENIED or ALLOWED events; it does not identify an AppArmor denial as
the cause of this library-open failure.

The launcher now removes that early-sandbox override from all three Vivaldi
modes. The correlated failure and
[Chromium's initialization order](https://raw.githubusercontent.com/chromium/chromium/ef1ce85f6dbc0471fbf7154a539bdbf53c0d73c7/gpu/ipc/service/gpu_init.cc)
support this correction: forcing early startup installs the sandbox before
GL initialization, while the normal Linux path initializes GL first. The
native GPU sandbox remains enabled. ANGLE/OpenGL, the existing acceleration
feature selection, render-node isolation and driver workarounds are retained.

The existing browser regression now covers Chromium, Edge and Vivaldi in
`launch`, `intel` and `nvidia` modes, requiring one OpenGLES WebGPU selection,
the managed ANGLE backend and no forced early GPU sandbox. These fixtures
were edited but not executed. Hardware compositing, WebGL/video decoding,
GPU process stability and player behavior still require target acceptance.

## 2. Managed-log findings

| Evidence | Finding and disposition |
| --- | --- |
| `network/veth.log`, all five records | Pool ready; both Vivaldi and Tor receive successful route/readiness events. No supplied veth failure. |
| `security/apparmor/apparmor.log`, all 433 records | STATUS events only. No new permission grant is justified by this capture. |
| `security/audit/auditd.log*` | Ten failed `execve` attempts return ENOENT during executable search. They concern `btop`, `xdg-settings`, `bwrap` and `vdirsyncer`; no EACCES syscall appears. Do not replace PATH search misses with permissions changes. Calendar synchronization later finishes successfully. |
| `security/crowdsec/crowdsec.log:6-10`, `:293-298`, `:382-383` | Initial CAPI-disabled state is followed by successful CAPI setup and 15,000 community decisions. This is recovery, not persistent offline operation. |
| `security/crowdsec/crowdsec_api.log` | All 257 captured responses are successful: 251 HTTP 200 and six HTTP 201. |
| `security/crowdsec/crowdsec-firewall-bouncer.log` | Native nftables backend starts and loads 15,000 decisions. The earlier shutdown follows its configuration check. |
| `security/crowdsec/crowdsec.log:276`, `:296` | Console synchronization reports no enrollment. CAPI and local enforcement still work. Console approval/remote enrollment is separate and cannot be repaired from this capture without remote state. |
| `security/crowdsec/crowdsec.log:25-26` and later starts | Upstream SSH parsers register overlapping Grok aliases. Engine starts and loads all parsers; no parser execution error is present. Preserve maintained upstream parser files. |
| `security/crowdsec/crowdsec.log:377`, `:384` | qBittorrent log absent at boot; exact-path discovery polling is enabled. The repository acquisition already rescans every 30 seconds for external-volume/log creation. No extra polling or rotated-log ingestion added. |
| `security/crowdsec/crowdsec.log:388-422` | Audit log moves/truncations are followed by successful reopening. No auditd ParseKV failure appears. |
| `apps/apps.log:229-243` | Vivaldi internal UI references an absent Proton extension, a NoScript resource not exposed by its manifest, unknown extension acknowledgements and an illegal profile URL. These are vendor/extension UI errors; the managed policy already removes the Proton extension. No force-install or extension sandbox weakening is justified. |
| `apps/apps.log:244` | Vivaldi reports missing Fontconfig configuration. The captured Bubblewrap command already binds `/etc/fonts` read-only. A child-process sandbox or vendor path issue remains possible; this evidence does not justify broad host filesystem access. Recheck after GPU correction. |
| `apps/apps.log:265-291` | Tor's graphics probe cannot find DRM, followed by successful Tor bootstrap to 100%. The existing privacy sandbox deliberately hides identifying device metadata. No anonymity or accelerated-rendering acceptance is established by successful circuit bootstrap. |
| `system/usb/usb.log:51-54` | UCSI firmware interface reports error 88 and GET_PDOS EIO twice. No repository cause is established. Kernel/firmware diagnosis remains separate; no module blacklist or speculative kernel tuning added. |
| `security/auth/auth.log:31` | One sudo PAM conversation fails. The capture does not establish a sudo policy or permission defect. |
| `security/fail2ban/fail2ban.log` | New-database warning is followed by a running SSH jail. |
| `system/zram/zram.log` | Setup succeeds; maintenance correctly skips below pressure thresholds. No performance measurements were supplied. |
| `system/initramfs/*` | Root becomes mounted and required target paths are present. `local-block` was not needed because the root device resolved without a retry. |
| `system/system.log:1092-1097` | Source NFS mount and subsequent home bind both succeed. |
| `apps/apps.log:90-173` | Waybar, Crystal Dock, portal services and calendar synchronization start/finish. Foot HUP messages follow terminal closure. Dock deprecation is upstream API usage, not a supplied dock startup failure. |
| `system/timeshift/timeshift.log` | Three successful GRUB Btrfs menu refreshes. This is not proof that a new snapshot was created. |
| Empty scanner/model/storage files | No scan or application outcome can be inferred from zero bytes. Preserve this absence of evidence rather than report a successful scan. |

The compositor's missing global Xwayland messages were recorded and left
within the explicitly excluded Xwayland scope. Private Zoom/Discord sources
were not changed. Informational kernel lines mentioning split-lock policy,
PCI error-containment capability and DRM panic planes are not kernel crashes.

### Complete supplied-file inventory

Paths below are relative to `todo/managed/`; byte counts are the reviewed
snapshot. No private log contents were copied into this report.

| Path | Bytes |
| --- | ---: |
| `apps/apps.log` | 47853 |
| `models/openai/chatgpt/chatgpt.log` | 0 |
| `models/openai/chatgpt/runtime/codex-login.log` | 0 |
| `models/openai/chatgpt/runtime/codex-tui.log` | 0 |
| `models/openai/codex/codex-login.log` | 0 |
| `models/openai/codex/codex-tui.log` | 0 |
| `models/whisper/whisper.log` | 150 |
| `network/veth.log` | 1005 |
| `security/apparmor/apparmor.log` | 75453 |
| `security/apparmor/modes.log` | 7192 |
| `security/audit/auditd.log` | 396379 |
| `security/audit/auditd.log.1` | 2097316 |
| `security/audit/auditd.log.2` | 2097277 |
| `security/audit/auditd.log.3` | 2097374 |
| `security/auth/auth.log` | 4841 |
| `security/chkrootkit/chkrootkit.log` | 0 |
| `security/chkrootkit/daily.log` | 0 |
| `security/chkrootkit/daily.log.raw` | 0 |
| `security/chkrootkit/log.expected` | 0 |
| `security/clamav/clamav.log` | 0 |
| `security/clamav/freshclam.log` | 0 |
| `security/clamscan/clamscan.log` | 0 |
| `security/crowdsec/crowdsec-firewall-bouncer.log` | 1742 |
| `security/crowdsec/crowdsec.log` | 50866 |
| `security/crowdsec/crowdsec_api.log` | 74598 |
| `security/debsecan/debsecan.log` | 0 |
| `security/debsums/debsums.log` | 0 |
| `security/fail2ban/fail2ban.log` | 1828 |
| `security/lynis/lynis-report.dat` | 0 |
| `security/lynis/lynis.log` | 0 |
| `security/lynis/scan.log` | 0 |
| `security/nftables/nftables.log` | 13672 |
| `security/rkhunter/rkhunter.log` | 0 |
| `security/rkhunter/scan.log` | 0 |
| `security/spectre-meltdown-checker/spectre-meltdown-checker.log` | 0 |
| `system/fwupd/security-scan.log` | 0 |
| `system/initramfs/01-init-top.log` | 1901 |
| `system/initramfs/02-init-premount.log` | 4909 |
| `system/initramfs/03-local-top.log` | 3856 |
| `system/initramfs/04-local-block.log` | 126 |
| `system/initramfs/05-local-premount.log` | 2009 |
| `system/initramfs/06-local-bottom.log` | 2232 |
| `system/initramfs/07-init-bottom.log` | 4836 |
| `system/kernel.log` | 102703 |
| `system/storage/storage.log` | 0 |
| `system/system.log` | 192641 |
| `system/timeshift/timeshift.log` | 532 |
| `system/usb/usb.log` | 9276 |
| `system/zram/zram.log` | 1682 |

## 3. CrowdSec review for the actual services

The user clarified that the system serves NFS, with a qBittorrent Web UI only
potentially needed later, and requested a check for useful improvements. This
section records that narrower review. The final patch makes no CrowdSec,
NFS, firewall or qBittorrent runtime changes.

### Current protection and limits

- The explicit Linux/SSH/auditd/iptables/whitelist-good-actors/Linux LPE and
  qBittorrent collections are already installed by firstboot. The capture
  confirms SSH CVE-2024-6387, audit/LPE, firewall and qBittorrent scenarios
  load, with working LAPI/nftables remediation. This confirms the supplied
  installation's pipeline state, not detection of a live exploit.
- NFS is configured for TCP NFSv4.1/4.2, with v2/v3, UDP and v4.0 disabled.
  The NFS firewall overlay enforces exact peer/interface constraints before
  broad established/local accepts. The identity guard checks effective nfsd
  settings and export drift. These existing controls remain the primary
  protection for this service.
- The NFS allowlist guard's final rule is an unlogged `counter drop`. Rejected
  traffic terminates there, before the generic terminal drop-log rules.
  Consequently, the existing CrowdSec closed-port scan scenarios do not see
  those specific NFS guard drops. Their counters still account for packets;
  detection must not be claimed from the generic log acquisition alone.
  If NFS rejection alerts are needed, the useful follow-up is explicitly
  rate-limited logging at that guard, with an aggregate log budget and an
  alert policy suitable for trusted LAN peers. No automatic ban or logging
  change was made during this requested check.
- The audit stream supplies post-exploitation and AppArmor-denial signals.
  It does not expose NFS RPC request bodies or prove detection of a
  particular kernel/NFS CVE. The reviewed Hub revision
  `6116cef94c78dc4023124199fcec717ae064f6a2` contains 576 parser/scenario/
  collection YAML paths and no NFS-named asset. HTTP CVE signatures researched
  earlier require HTTP request data from unrelated applications and have
  no demonstrated NFS signal here.

### Future qBittorrent Web UI

The current native template has `WebUI\Enabled=false`; peer ingress is an
app-veth DNAT/FORWARD path and the qBittorrent host service overlay is empty.
Enabling a Web UI would require a separate listener/address/ingress design.
It should not reuse the torrent peer port or implicitly expose the host.

The existing [qBittorrent collection](https://raw.githubusercontent.com/crowdsecurity/hub/master/collections/gilbsgilbs/qbittorrent.yaml)
already installs the maintained
[login-failure parser](https://raw.githubusercontent.com/crowdsecurity/hub/master/parsers/s01-parse/gilbsgilbs/qbittorrent-logs.yaml)
and [brute-force scenario](https://raw.githubusercontent.com/crowdsecurity/hub/master/scenarios/gilbsgilbs/qbittorrent-bf.yaml).
The parser accepts IPv4/IPv6 WebAPI authentication-failure records and the
scenario groups them by source IP. This is authentication monitoring, not a
general qBittorrent CVE detector.

Its acquisition points to the correct persistent log: the launcher binds the
external `.qbittorrent-profile` as `/home/user`, and the native template writes
`/home/user/.local/share/qBittorrent/logs/qbittorrent.log`. The acquisition
rescans that exact external file every 30 seconds, covering delayed mount/log
creation without rereading rotations. The Linux collection's non-syslog raw
parser maps `type: qbittorrent` to the program/message fields expected by the
qBittorrent parser. No extra acquisition or parser is needed for this format.

One relevant future limitation is the loaded upstream
[private-address whitelist](https://raw.githubusercontent.com/crowdsecurity/hub/master/parsers/s02-enrich/crowdsecurity/whitelists.yaml).
Its default private IPv4/loopback ranges can discard LAN authentication events
before the brute-force scenario. A LAN-only Web UI must therefore have an
explicit decision about trusted clients and authentication monitoring, with
fixture coverage for that policy. Do not silently remove global good-actor or
private-address exceptions. If a reverse proxy is later introduced, preserve
the authenticated original client address rather than banning the proxy.

Before enabling the Web UI, review its native authentication protections,
listener scope and ingress policy together, then verify real failure/benign
records and bouncer behavior in the disposable environment. No host exposure,
new listener, unrelated HTTP collection or arbitrary set of CVE names was
added as a result of this review.

## Static checks and generation

- Python 3.14.8 `ast.parse` read the changed browser module and browser
  regression module as data; no repository module was imported or executed.
- `git diff --no-ext-diff --no-textconv --check` reported no whitespace errors.
- The updated browser fixture covers nine browser/mode combinations, managed
  ANGLE/OpenGLES selection and absence of forced early GPU sandbox startup.
  **Zero fixtures were run.**
- Shell validators, `cscli`, `crowdsec -t`, AppArmor parsing, native integration,
  live browser/GPU testing and performance benchmarks were not run.
- Pure generation completed with
  `env -i PATH=/usr/bin:/bin LANG=C.UTF-8 make build 'PYTHON=python3 -I'`.
  The reviewed build/publication code executes no test, validator, shell
  snippet, policy parser or installed management helper.
- A separate standard-library archive/hash inspection read all 1,784 regular
  members without extraction: 34,312,595 content bytes. Every archived file
  matches its current source bytes and manifest SHA-256. All three bootstrap
  hashes are present in `preseed.cfg`. The manifest changes only the browser
  module entry; generated products are current.
- Archive/source parity does not establish live deployment or enforcement.

### Generated SHA-256 values

| Product | SHA-256 |
| --- | --- |
| `d-i/forky/payload.tar.gz` | `995883df6c24f44cdb3d1f7ec0593af2ff7ed5ad535bece90e061d73464d41bf` |
| `d-i/forky/payload.manifest` | `a4d06b717471bc03b41ef34d1d19805c817a4be1078b6dd6f286579bc8828c6e` |
| `d-i/forky/preseed.cfg` | `30a4d404b1e2c9adfc4ed59101d0b66489d4700a35dee078fe1b9cb608e8a3ec` |
