# Installed system log review and static Wi-Fi repair — 2026-10-13

## Scope and evidence

Reviewed every regular file in the current `todo/` snapshot as data: **94 files,
9,364,013 bytes, 47,490 physical lines, including 22 empty files**. The companion
`todo-20261013-inventory.json` records every path, size, physical line count and
SHA-256. No command contained in a log was executed. This snapshot supersedes
the different snapshots described by earlier reports dated October 13.

The supplied version record reports systemd 262 (262-1); the kernel record
reports 7.2.10-x64v3-xanmod1. Firstboot's `status.env` reports status 0 at
15:55:14 UTC. Early failed-unit snapshots contain zero failed units, but later
application and Tailscale errors are present. Those early snapshots do not
establish a healthy later system.

Changes address failures with a demonstrated repository cause. External
approval, hardware/filesystem faults and upstream UI defects remain explicit
below; there is no claim that every recorded error has disappeared on the
installed machine. The checkout was initially clean. No source compilation,
host repair, package operation, service operation or deployment was performed.
The existing private Xwayland policy remains unchanged.

## 1. Failure findings and changes

| Finding and supplied evidence | Disposition |
| --- | --- |
| Removed `CPUAccounting=` option in `system-xfs_healer.slice`, `managed/system/system.log:432,1139,1441,1448,1453,1457,1553` | Extended the existing target-unit sanitizer to `xfs_healer@.service`, `xfs_healer_start.service` and `system-xfs_healer.slice`, alongside the existing scrub units. Matching directives are removed from the effective target unit; the replacement is installed in `/etc/systemd/system`. Both filesystem-family installation flows call this after package repair. No authored unit or transient service sets the removed option. Matching strings in the sanitizer and negative regression assertions are retained to prevent vendor units reintroducing it during installation. |
| Vivaldi rejects two search-engine configurations with invalid signatures, `managed/apps/apps.log:181–182` | Removed the two unsigned seeded JSON cache files, their staging calls and their required-file checks. Vivaldi owns regeneration of its native caches. The source/log correlation supports this repair; a native browser launch was not performed. Existing installed user caches are not modified by this fresh-install change. |
| Tailscale startup times out; status is `NeedsMachineAuth` with an existing node key, `managed/system/system.log:995–996,1287` | Bootstrap now records `pending-machine-approval` explicitly and checks this state before retrying `tailscale up`, avoiding auth-key reuse while approval is pending. Retains the existing bounded systemd restart policy and nonzero pending result. Diagnostic JSON now contains only backend state, node-key presence and health count. **A tailnet administrator must approve the device.** |
| qBittorrent's required data volume is absent, `managed/apps/apps.log:213,222` | Its fail-closed requirement is correct. The supplied sequence later shows the XFS volume mounted and the qBittorrent network lease ready at 18:00:06. No fallback data directory or speculative automount was added. The required volume must be mounted before launch. |
| DRM atomic commit on eDP-1 returns `EBUSY`, `managed/apps/apps.log:141,195` | No deterministic repository cause is established. Requires target GPU/compositor reproduction and a packaged upstream correction if indicated. No modesetting/security workaround or source build was introduced. |
| Waybar emits ten `GTK_IS_ACCEL_GROUP` assertions, `managed/apps/apps.log:248–257` | Existing repository menu XML already defines accelerator groups. Upstream tray menu code now explicitly creates one; the installed package and runtime behavior need verification in the disposable/target environment. No tray removal or source build was introduced. |
| Vivaldi cannot find an extension, `managed/apps/apps.log:193–194` | The referenced ID is absent from repository policy. Cache/profile/vendor provenance remains unestablished; no unrelated extension policy was changed. |
| Vivaldi internal UI is denied access to NoScript's extension resource, `managed/apps/apps.log:196,198` | This is an extension manifest/web-access boundary. No AppArmor denial is present for it. No extension resource restriction was weakened. |
| CrowdSec console not enrolled/pending acceptance, `managed/system/system.log:821,845,1150–1152` | Console enrollment needs external acceptance. Acquisition/parser/bouncer source ownership is retained. CAPI-disabled warnings match configured policy; duplicate grok-pattern warnings come from upstream parsers. No acquisition fatal error was identified in the supplied snapshot. |
| qBittorrent acquisition file temporarily absent | Consistent with the missing-volume and deferred-launch sequence. No broad alternate acquisition path was added. |
| IPv6 NTP endpoints time out, `managed/system/system.log:1129,1157–1165` | Subsequent IPv4 synchronization succeeds at lines 1166–1167. No time-service policy change is supported by this sequence. |
| Ethernet disappears after a USB dock detach; ifdown cannot find eth0 | The detach is explicit in the journal. The existing veth broker switches Vivaldi to Wi-Fi and later switches both Vivaldi and qBittorrent back to Ethernet. No broker or lifecycle change was needed for this snapshot. |
| Labwc cannot start a global Xwayland executable | Expected under the requested existing policy. Private Xwayland remains restricted to Zoom/Discord. |
| Crystal Dock LayerShellQt deprecation and ksecretd UI/property warnings | Upstream compatibility diagnostics without a demonstrated repository startup failure. No component rebuild or feature removal. |
| EFI FAT volume was not cleanly unmounted, firstboot `data/dmesg-warnings.txt:16` | Requires offline filesystem inspection/repair on the target. No filesystem repair was executed or silently scheduled by the installer. |
| UCSI error 88/-5, I2C speed fallback, HID/TDX/Bluetooth/HPET/aux/uncore/ASoC probe warnings, dummy SPI regulator | Retained as hardware/kernel/firmware findings. The supplied data does not establish a correct installer workaround. |
| kauditd reports 151 suppressed callbacks, firstboot `data/dmesg-warnings.txt:22` | Limits completeness of retained kernel audit evidence; absence of a retained denial is not proof that none ever occurred. |
| Installer partition alignment/formatting, absent installer EFI MOK-sync source, installer Glycin sandbox warning | Alignment deficit is within the logged tolerance; formatting is the configured installation operation; absent installer EFI skips that synchronization. No fatal installer failure was identified in these records. |
| Empty scanner logs | No successful scan result can be inferred from an empty file. |

Primary references used for version-sensitive conclusions:
[systemd 262 directive table](https://github.com/systemd/systemd/blob/v262/src/core/load-fragment-gperf.gperf.in),
[Waybar tray item implementation](https://github.com/Alexays/Waybar/blob/master/src/modules/sni/item.cpp),
[CrowdSec console enrollment](https://docs.crowdsec.net/u/getting_started/post_installation/console/),
[Tailscale backend states](https://github.com/tailscale/tailscale/blob/main/ipn/backend.go),
[Debian wpa_supplicant configuration parser](https://sources.debian.org/src/wpa/2:2.10-24/wpa_supplicant/config.c/).

## 2. Static Wi-Fi addressing and authentication

The supplied firstboot network defaults selected only `ethernet`: Wi-Fi MAC,
CIDR and ESSID were empty. The old handoff depended on having installer Wi-Fi
credentials. Consequently NetworkManager managed the detected Wi-Fi adapter
with DHCP, and later diagnostics reported `192.168.50.162` while Ethernet was
`192.168.50.88/24`.

For the selected static network class, detected Wi-Fi is now included even
without installer credentials. Address allocation is deterministic:

| Property | Ethernet | Wi-Fi |
| --- | --- | --- |
| IPv4 in the supplied example | `192.168.50.88/24` | `192.168.50.89/24` |
| Gateway | Shared static gateway, `192.168.50.1` in the supplied example | Same gateway |
| DNS | Existing selected resolver policy | Same policy and nameservers |
| Route metric | 100 | 200 |
| Address owner | ifupdown static configuration | ifupdown static configuration |

Both names and MACs are placed in the existing NetworkManager unmanaged policy,
preventing a DHCP profile from taking ownership. Address +1 overflow, leaving
the Ethernet subnet, gateway collision, network/broadcast addresses and duplicate
generated addresses are rejected; no alternate address is silently selected.
The existing IPv6 +1 allocation also rejects leaving its configured prefix.
Link DNS mode renders the same nameservers on both adapters; global DNS mode
uses the existing common resolver and omits per-link DNS on both.

Boot/staging validation checks the Ethernet/Wi-Fi +1 relationship, exact static
IPv4 address/netmask/gateway/metric, shared link DNS and the fixed authentication
reference. These checks apply even when an adapter is detached. Generated host
CIDR state includes both addresses for the existing firewall consumers.

Wi-Fi authentication lives separately in the root-owned mode-0600
`/etc/wpa_supplicant/wifi.conf`. It disables configuration writes and P2P.
With installer credentials, the generator emits the native WPA/SAE/open/WEP
network block; otherwise it emits an empty network list ready for later entry.
No credential is included in runtime host defaults.

The desktop action is **right-click Waybar's network indicator → Connection
Profiles → Connect WiFi Network**. The installed
`labwc-network-control-action configure-wifi wifi0` entry also opens its terminal
workflow. Existing Polkit authorization and physical-interface validation precede
the fixed root helper. It prompts for SSID/security/passphrase, validates the
static policy and private files, atomically updates authentication and the two
SSID/security metadata fields, and reactivates that adapter. It does not change
addresses, routes or resolver configuration. Password input is hidden; WPA
passphrases become derived PSKs and SAE strings are encoded as parser-safe byte
strings. AppArmor grants only its fixed files, private temporary names, lock and
the required package-command transitions.

The supplied veth log already records Vivaldi `eth0 → wifi0 → eth0`, and
qBittorrent `wifi0 → eth0`. The common broker source is preserved. This evidence
supports existing uplink switching, but does not establish uninterrupted active
connections for every application or prove the new static policy on hardware.
The static LAN must have the +1 address available and valid Wi-Fi credentials.

## 3. Security evidence and validation boundary

The four supplied audit files contain 29,674 physical records. The 96 failed
syscalls comprise 53 ENOENT executable PATH probes, 40 ENOENT cleanup unlinks and
three ENOTEMPTY attempts to prune populated unit directories. Correlated records
do not establish an application sandbox denial. The supplied AppArmor log has
426 STATUS records and zero DENIED records. No AppArmor or firewall protection
was weakened to suppress those messages.

The repository's `AGENTS.override.md` and `docs/test-isolation.md` prohibit host
test execution and native validation. No prepared compliant disposable
environment was available. Therefore:

- Python AST parsing treated the new helper and three changed test modules as
  data; it imported or executed no repository code.
- Caller, staging, template, file-mode, AppArmor and generated-state contracts
  were inspected as source data.
- `git diff --check` completed without findings.
- Guarded regression cases were authored/updated for static Wi-Fi without
  installer credentials, shared DNS/metrics, rejected address drift, WPA's
  reference vector, credential encoding, P2P policy, Vivaldi cache ownership
  and vendor XFS unit coverage. **They were not executed.**
- No shell/Perl syntax runner, AppArmor parser, systemd validator, unit test,
  native integration test or live acceptance check ran.
- Independent sidecar reviews were attempted, including fresh agents without
  inherited conversation, but all failed initialization with encrypted-content
  hydration errors. No child findings or successful independent review are claimed.

## Generation and artifact comparison

This section records the generation snapshot before the subsequent power-flow
follow-up. The current rebuilt product hashes are recorded in
[the poweroff/reboot report](poweroff-reboot-close-20261013.md).

The only repository program executed was the expressly permitted pure
serialization command:

```sh
/usr/bin/env -i PATH=/usr/bin:/bin LC_ALL=C.UTF-8 /usr/bin/make build PYTHON='/usr/bin/python3 -I' SHELL=/bin/sh
```

It completed with exit 0 and `built 1757 payload files`. A before/after metadata
inventory of 2,373 checkout files confirmed that generation changed exactly
`d-i/forky/payload.tar.gz`, `d-i/forky/payload.manifest` and
`d-i/forky/preseed.cfg`.

Streaming archive inspection, without extraction or execution, compared all
1,757 regular members and 33,962,415 source bytes with canonical source and
manifest SHA-256. Member mode is 0644; uid/gid/mtime are zero. Tests, private
input names and generated products are excluded. The deleted Vivaldi cache
files are absent. There are **zero `CPUAccounting` directive assignments** in
all published member contents. Archive, manifest and bootstrap-source hashes
match the three checksum pins in preseed. This is an artifact comparison,
not execution of a generated configuration or proof of target behavior.

| Product | SHA-256 |
| --- | --- |
| `payload.tar.gz` | `a6d9a7f6d917f73f9a1e72be65c58ad79313e6d32992a6976498dadd6ece3d63` |
| `payload.manifest` | `8de9caa016bd7c7b885786a459b4fabc372ddfca40a12e805a46d6d591b9e3e6` |
| `preseed.cfg` | `053b59c60feea75df0f9554fb85293a4427ed930d7e8cb90a07c6df97288fa42` |

The private Xwayland helper, installer wiring, dedicated regression module,
Zoom/Discord AppArmor policy and gitbuild AppArmor source match HEAD byte for
byte. Xwayland reference contexts in the changed desktop wrapper policy also
match HEAD. No fresh-install or native GUI/network acceptance was performed.

## Changed paths

Canonical source changes are limited to the network handoff/generator and Wi-Fi
templates, managed network validator, Wi-Fi credential helper and its desktop
menu/client/root/staging/AppArmor consumers, XFS vendor unit sanitizer, resource
accounting comments, Tailscale bootstrap, Vivaldi cache staging/verification and
the three guarded regression modules. The two unsigned Vivaldi cache source
files were removed. This report and the complete snapshot inventory document
the evidence. The three generated installer products were rebuilt and compared
as recorded above. They have not been published or installed on the target.

### Exact path inventory

- `d-i/forky/hooks/target/etc/apparmor.d/desktop-wrappers.tmpl`
- `d-i/forky/hooks/target/etc/apparmor.d/system-wrappers.tmpl`
- `d-i/forky/hooks/target/etc/skel-desktop/.config/vivaldi/search_engines.json`
- `d-i/forky/hooks/target/etc/skel-desktop/.config/vivaldi/search_engines_prompt.json`
- `d-i/forky/hooks/target/etc/systemd/system.conf.d/60-resource-accounting.conf.tmpl`
- `d-i/forky/hooks/target/etc/systemd/user.conf.d/60-resource-accounting.conf.tmpl`
- `d-i/forky/hooks/target/etc/wpa_supplicant/wifi.conf.tmpl`
- `d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu`
- `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/labwc-network-control-action/LabwcNetworkControlAction/Client.pm.tmpl`
- `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/labwc-network-control-action/LabwcNetworkControlAction/Root.pm`
- `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/network/ManagedNetwork/Validator.pm`
- `d-i/forky/hooks/target/usr/local/libexec/network-wifi-configure`
- `d-i/forky/payload.manifest`
- `d-i/forky/payload.tar.gz`
- `d-i/forky/preseed.cfg`
- `d-i/forky/scripts/desktop/components/target-assets.sh`
- `d-i/forky/scripts/desktop/verify.sh.tmpl`
- `d-i/forky/scripts/firstboot/assets/var/lib/firstboot/bin/tailscale-up`
- `d-i/forky/scripts/late/network-generate.pl`
- `d-i/forky/scripts/late/network.sh`
- `d-i/forky/scripts/late/storage-maintenance.sh`
- `d-i/forky/scripts/late/templates/network-assets.list`
- `d-i/forky/scripts/late/templates/network/wifi-conf.tmpl`
- `d-i/forky/scripts/late/templates/network/wifi-open.tmpl`
- `d-i/forky/scripts/late/templates/network/wifi-sae.tmpl`
- `d-i/forky/scripts/late/templates/network/wifi-wep.tmpl`
- `d-i/forky/scripts/late/templates/network/wifi-wpa.tmpl`
- `d-i/forky/tests/test_boot_runtime_20260913.py`
- `d-i/forky/tests/test_browser_repository.py`
- `d-i/forky/tests/test_desktop_sandbox.py`
- `docs/validation/todo-20261013-inventory.json`
- `docs/validation/todo-20261013-review.md`
