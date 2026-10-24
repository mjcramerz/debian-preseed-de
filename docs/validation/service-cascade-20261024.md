# October 24 failure capture: AppArmor, Podman bootstrap, Code and devices

## Evidence and scope

This incident uses the replacement `todo/failures/` capture from LPL-128,
booting at 23:14 on October 24. There are 43 supplied files, 12 nonempty.
The checkout was clean on `mcr/main` at
`9d21fdde8f53ff4a52a4fb59d53208d0bcf01457` before these changes.
The older hardware/failure report describes an earlier capture and is not
acceptance evidence for this incident.

Only supplied files and checkout sources were inspected. No host state,
service manager, devices, packages or policy were queried or changed. No tests,
native parsers, Perl imports/syntax commands, VMs or containers were executed.
The permanent static-only policy in `AGENTS.override.md` remains in force.

### Complete nonempty-file review

The review includes every nonempty file in this capture. Empty application
logs do not establish successful application startup.

| File under `todo/failures/` | Review outcome |
| --- | --- |
| `journalctl` | Calendar regex compilation failure, 19 failed/dependency-blocked units, bootstrap activation failures and secondary desktop diagnostics. |
| `installer-state/installer.log` | Traced the matching-mode early return that accepted the calendar policy without full compilation; reviewed package reload, icon, storage, MOK and metadata warnings. |
| `installer-state/target-validated` | Records `TARGET_VALIDATED` and `installation_success=not_yet`; this is not a successful-boot receipt. |
| `managed/security/apparmor/apparmor.log` | 9,053 AppArmor status records, no denial records. |
| `managed/security/audit/auditd.log` | Reviewed all record types, failed service starts and failed syscalls; details below. |
| `managed/security/auth/auth.log` | Greeter, login and cron sessions; no recorded authentication failure. |
| `managed/security/auth/unverified.log` | The user's sudo log collection is explicitly marked unverified; no verified origin or authentication failure is inferred. |
| `managed/security/fail2ban/fail2ban.log` | New database and SSH jail startup complete. |
| `managed/security/nftables/nftables.log` | Accepted traffic records, no recorded firewall operation failure. |
| `managed/system/kernel.log` | Wacom report errors and local-address ARP diagnostics; also traced PCI resource reassignment and subsequent driver enumeration. |
| `managed/system/system.log` | Twenty distinct normalized messages: the AppArmor cascade, socket limits, bootstrap failures and local DNS feature degradation. |
| `managed/system/usb/usb.log` | Two UCSI power-data query failures, plus successful USB device enumeration. |

| Supplied file | SHA-256 |
| --- | --- |
| `journalctl` | `fb19f18fb3d1f8e769136a98aa45b5f1d08a3891edecbd1a749a20585eb44eb8` |
| `installer-state/installer.log` | `c078431f1ea49de3e5d21c5c6f0bb6b3ab05d633890b43a26f50beeafd1ce14d` |
| `managed/security/apparmor/apparmor.log` | `ac9a0129a29b2155d4761e14e7c34a3b055b4f8fc4e5d2113388866a47e18b5f` |
| `managed/security/audit/auditd.log` | `9a961a50b1576baf8f6f8917e440aa6a71c3bc0fa745e7afead108515ccf0b2a` |
| `managed/system/usb/usb.log` | `cc19af884bebb3867c55000e5734b2363ab1e0c8e42bc288368a80f23c4b25d6` |

## Root cause and affected units

Journal line 191 reports `ERROR processing regexs for profile
labwc-waycal-control, failed to load`. At lines 205–232, `apparmor.service`
exits 1 and its security-dependent services fail their start jobs. There are
21 repetitions of that same regex failure. The socket activation attempts then
hit rate limits; the tuning client sees a reset connection and then a missing
socket at lines 1786–1804. The Podman bootstrap exits 125 after its engine's
activation fails at lines 1012–1019.

The two affected policy rules used `wayland-[A-Za-z0-9_-]*`. AppArmor's
[4.1.8 regex grammar](https://gitlab.com/apparmor/apparmor/-/blob/v4.1.8/parser/libapparmor_re/parse.y#L118)
accepts a bare literal hyphen as the first character of a class; subsequent
hyphens are range operators requiring an endpoint. A trailing bare hyphen
cannot complete that production. Its regex error callback intentionally emits
no detailed diagnostic, matching the generic failure in this capture.

The supplied AppArmor and audit copies each contain 9,053 AppArmor `STATUS`
records and no AppArmor denial records. This is a policy compilation failure,
with already loaded profiles repeatedly replaced/skipped during activation
attempts.

The journal identifies these **19 failed or dependency-blocked units**:

| Group | Units |
| --- | --- |
| Policy loader | `apparmor.service` |
| DNS and application networking | `stubby.service`, `dnsmasq-app-veth.service`, `app-veth.service` |
| Tailscale | `tailscaled.service`, `tailscale-bootstrap.service` |
| Container engine | `podman-devops.service`, `podman-devops.socket`, `podman-devops-bootstrap.service`, `podman-devops-restart.service` |
| Hardware tuning / Power Profiles | `hardware-tuning.service`, `hardware-tuning.socket`, `hardware-tuning-autostart.service`, `hardware-tuning-intel-balanced.service`, `intel-balanced.target`, `power-profiles-daemon.service` |
| Other policy-dependent startup | `apparmor-modes.service`, `mullvad-apparmor.service`, `firstboot.service` |

The security dependencies remain intact. The bootstrap prerequisite mismatch
is corrected separately below.

## Corrections

1. In `hooks/target/etc/apparmor.d/calendars`, both the control and popup rules
   now use `wayland-[-A-Za-z0-9_]*`. Moving the literal hyphen preserves the
   intended character set. The second rule had the same defect after the first
   failing profile. No Xwayland configuration or eligibility is changed.
2. In `AppArmor/ManagedModes/Transition.pm`, `--no-reload` now performs a full
   non-loading compilation of an active source whose mode already matches.
   Previously it returned after `apparmor_parser -N` name listing and mode
   inspection. The installer log explicitly records that early-return path for
   `calendars`; it could therefore publish a validated installation without ever
   compiling this profile's regex. The existing offline mode boundary now uses
   the same explicit config-free ABI/include inputs and `-Q -K -T` compilation
   as a changed candidate. It does not load policy, write a production cache,
   edit an unchanged source or start services.
3. The existing boot/runtime fixture now injects a compilation failure after
   successful name listing, verifies that failure propagates with unchanged
   source and no kernel mutation, and requires offline compilation even when
   the kernel-state fixture is absent. These fixture cases are unexecuted.
4. `podman-devops-bootstrap.service` now has both `Requires=app-veth.service`
   and `After=... app-veth.service`, matching the engine's existing prerequisite.
   Previously the bootstrap started a remote `podman info` query even when
   `app-veth` and its AppArmor/DNS prerequisites had failed. The queued socket
   repeatedly attempted an engine that could not start, exhausting activation
   limits and producing three opaque `/usr/bin/env exited 125` failures.
   Under the documented [systemd 262 Requires/After contract](https://www.freedesktop.org/software/systemd/man/latest/systemd.unit.html#Requires=),
   a failed ordered prerequisite prevents bootstrap's `ExecStart`. The engine,
   socket ownership, rootless identity, existing stores and process cleanup
   implementation are unchanged. The existing unit-contract fixture now checks
   this requirement and ordering; it remains unexecuted. Static inspection of
   the affected local dependency chain found no reverse ordering to bootstrap;
   the installed systemd graph has not been exercised.
5. The launcher synchronizer now recognizes
   `com.microsoft.VSCode.UrlHandler.desktop` alongside the existing
   `code-url-handler.desktop`. Microsoft's [VS Code 1.139 release notes](https://code.visualstudio.com/updates/v1_139#_linux-desktop-launcher-names)
   document this exact rename on September 23, 2026; its
   [package-generation source](https://github.com/microsoft/vscode/blob/main/build/gulpfile.vscode.linux.ts)
   generates the reverse-DNS URL-handler filename. The main Code entry already
   had the corresponding new alias, but the separate URL handler did not.
   Both URL-handler IDs now publish the existing managed `--open-url %U`
   command with `NoDisplay=true` and the `vscode` MIME scheme. Root ownership,
   directory precedence, rejection of untrusted overrides, the primary GPG
   gate and native Wayland dispatch are preserved. Two unexecuted fixture cases
   cover resolving the new vendor ID without the CLI fallback and rejecting
   an untrusted higher-priority entry without falling back to another alias.
   The installed Code version and exact CLI metadata were not captured, so
   the logged `missing=code` diagnostic is consistent with this defect without
   proving it was the sole cause on LPL-128.

The installation path remains `scripts/late/security.sh` ->
`apparmor-modes-run --no-reload` -> the managed Perl transition module. The
runtime loader still owns kernel activation. Disabling AppArmor or removing its
dependencies is not part of this repair.

## Audit record correlation

All 24 failed `SYSCALL` records are `execve` returning `ENOENT` while searching
`PATH`, across 16 PIDs. Each PID subsequently records a successful `execve` of
the expected `/usr/bin` program: `sh`/`dash`, `bwrap`, `systemctl` or
`dbus-update-activation-environment`. These are intermediate search misses,
not missing installed executables. Arguments, environments and raw proctitles
are omitted from this report.

The 24 failed `SERVICE_START` records are 21 AppArmor starts and three Podman
bootstrap starts. There are no `SECCOMP`, `ANOM_ABEND` or non-status AppArmor
AVC records in this capture. Enriched audit fields after record separators
were treated as continuations, not additional failed records. Audit event
serials are more reliable references than line counts from Unicode
`splitlines()`, which also splits those separators.

## Other diagnostics and remaining limits

| Diagnostic | Disposition |
| --- | --- |
| UCSI `unknown error 88` / `UCSI_GET_PDOS failed (-5)` | Genuine separate USB-C power-data query failures, twice in `managed/system/usb/usb.log`. The capture identifies Lenovo 82HS, BIOS FXCN49WW and kernel `7.2.12-x64v3-xanmod1`. The [kernel UCSI command/error path](https://github.com/torvalds/linux/blob/master/drivers/usb/typec/ucsi/ucsi.c) reports an unrecognized firmware error as `-EIO`. The supplied evidence does not establish a safe repository-level fix or whether the defect is in firmware, controller state or this kernel. Lenovo's [published BIOS page](https://support.lenovo.com/us/en/downloads/ds546876-bios-update-for-windows-10-64-bit-flex-5-14itl05-flex-5-15itl05) lists the same FXCN49WW; no newer corrective firmware was established. This remains unresolved. No controller was disabled or diagnostic hidden. |
| Wacom I2C HID `incorrect report (0 vs 11 expected)` | Five errors at `kernel.log` lines 816–820, before the Wacom Pen/Finger input devices register. A [matching report in the upstream Wacom project](https://github.com/linuxwacom/input-wacom/issues/516) describes a kernel regression with this exact diagnostic, but does not establish a verified fix for this machine. Registration does not prove input works. This remains unresolved; no device blacklist, speculative quirk or kernel replacement was introduced. |
| IPv4 local-source martians | Three Ethernet records at kernel lines 927–932 contain ARP broadcast headers with the Wi-Fi connection's own cloned source MAC and the same source/target IPv4 address. This is consistent with reflected local gratuitous ARP while both links share the LAN; it does not establish a second host using that address. The existing profiles already use loose `rp_filter=2`, `arp_ignore=1` and `arp_announce=2`, and the network templates retain Ethernet/Wi-Fi metrics 100/200. Source validation and logging were preserved. Exact installed routing and link failover are unverified. |
| PCI SPI BAR cannot initially be claimed | Kernel line 465 is followed by assignment of a new BAR at line 535 and later SPI NOR/BIOS partition registration. This is a recovered resource allocation diagnostic, not evidence that the SPI driver failed. |
| Bluetooth identity file initially absent | Journal lines 381–384 record `No IRK stored` followed by `Generated IRK successfully`; lines 570–575 show the controller already enabled and initializer completion. BlueZ 5.87 is recorded in this capture. No privacy key was pre-generated or replaced by the installer. |
| `System is tainted: unmerged-bin` | This describes separate `/usr/bin` and `/usr/sbin` directories. Debian's [release guidance](https://www.debian.org/releases/trixie/release-notes/issues.en.html#systemd-message-system-is-tainted-unmerged-bin) explicitly advises leaving that layout to package management; manual merging is unsupported. This is not a service start failure. |
| Duplicate Power Profiles D-Bus activation names | The managed files in `/usr/local/share/dbus-1/system-services` override the package copies in `/usr/share`; the broker ignores the lower-priority duplicates. Both managed activation files name the existing `power-profiles-daemon.service`. Its actual start is blocked by AppArmor in this capture. |
| Duplicate `/tmp/.X11-unix` tmpfiles entry | The duplicate is ignored; no tmpfiles service failure is recorded. Existing private Zoom/Discord Xwayland configuration is preserved. |
| Outer Labwc missing Xwayland | The compositor continues without it. The explicit private Zoom/Discord-only invariant is preserved. |
| XFS healer reports logging policy | These lines describe its configured autofsck reporting policy; no corrupt filesystem or failed repair is recorded. |
| Netavark DHCP proxy inactivity timeout | Journal lines 1087–1088 pair its 30-second inactivity exit with `netavark-dhcp-proxy.service: Deactivated successfully`. This records an idle shutdown; it is not another failed service activation in this capture. |
| Launcher synchronization `missing=code` | Fixed the missing current URL-handler alias described above. The main managed `code.desktop` was staged at installer line 4458, and the separate handler previously recognized only its old name. CLI fallback also checks ownership/modes. Exact installed Code file metadata and post-fix URL handling remain unverified; `skipped_invalid=0` is not evidence that every launcher exists. |
| Package post-install AppArmor reloads inside d-i | Mullvad's later non-loading profile check succeeds in the installer log. Zoom's post-install warning names the unavailable installer AppArmor filesystem. These are distinct from the first-boot calendar compilation defect; no package profile is disabled. |
| Glycin installer warning | It occurs during managed launcher icon verification, which completes. It does not establish an installed application sandbox failure. |
| Package metadata-only baselines | The log accurately says identical unversioned remote package bytes cannot be proven without a digest. No stronger artifact trust is asserted. |
| Fail2ban, nftables and authentication logs | Fail2ban's SSH jail starts, nftables lines are accepted traffic, and the authentication records describe the user's log collection. No independent service failure appears in these files. |

The source repair has not been installed on LPL-128. Service recovery and a
clean subsequent boot are unverified. The USB-C and Wacom diagnostics remain
open hardware/driver issues. Static evidence does not prove that every service
now starts or that either device diagnostic is fixed. The capture does not
contain an installed service recovery run or native device acceptance evidence.

The additional upstream device review found no established model-specific
repair. The inspected [UCSI ACPI quirk table](https://github.com/torvalds/linux/blob/master/drivers/usb/typec/ucsi/ucsi_acpi.c)
contains Acer Nitro and LG Gram cases, not this Lenovo 82HS. The UCSI core's
unrecognized-error path still returns `-EIO` to the failed PDO query; a quirk
for a different transport or product does not establish applicability here.
The upstream Wacom issue remains open and reports the matching diagnostic on
a newer kernel too. No verified replacement kernel/package or documented knob
that repairs this machine's responses was established. Device functional impact
remains unknown pending the user's description of symptoms already observed;
no new native check has been requested.

### Completion audit

| Requirement from the failure report | Current authoritative evidence | Acceptance state |
| --- | --- | --- |
| Inspect the complete supplied failure capture | All 43 paths inventoried, all 12 nonempty files reviewed; current capture hashes still match the evidence above. | Inspection complete for these supplied bytes. |
| Repair the policy defect blocking services | Both affected character classes corrected; grammar and installer call path reviewed. | Source correction complete; target compilation/loading unverified. |
| Reject invalid unchanged policy before installation is accepted | Matching-mode offline branch now compiles fully; failure propagation fixture authored. | Source correction complete; fixture/native behavior unexecuted. |
| Prevent bootstrap probes while required networking/policy failed | Bootstrap now requires and orders after the engine's existing `app-veth` prerequisite. | Source correction complete; installed systemd behavior unverified. |
| Resolve the Code launcher discrepancy | Current vendor URL-handler ID added, vendor rename confirmed, resolution/rejection fixtures authored. | Source correction complete; installed URL handling unverified. |
| Resolve USB-C/Wacom query errors | Supplied device errors and bounded upstream research; no verified applicable fix or observed functional-impact description. | Unresolved. |
| Establish that all reported services recover | The supplied capture predates these edits. No post-fix runtime evidence is available. | Unverified; static inspection cannot satisfy this requirement. |

The goal of resolving every failure is therefore not marked complete. The
permanent static-only execution boundary remains in force.

## Static inspection and generated products

- A subsequent bounded capture recheck found the same 43 files and the same
  hashes for all 12 nonempty files. Normalizing timestamps and PIDs across the
  complete journal yielded 51 distinct messages matching the explicit
  error/failure/unavailable/timeout search terms. Their dispositions remain
  the service cascade, launcher discrepancy, normal state transitions and
  successful idle exits described above; this adds no post-fix runtime evidence.
- `git diff --check`: exit 0.
- Standard-library `ast.parse` of the launcher synchronizer template,
  `test_boot_runtime_20260913.py`, `test_podman_incus_redesign.py` and
  `test_primary_gpg_launch_gate.py`: succeeds as source-data parsing only.
  Literal inspection confirms both URL-handler aliases retain the existing
  `--open-url %U` and `no_display` contract. No fixture import or execution.
- Source inspection against the AppArmor 4.1.8 grammar confirms the corrected
  character-class form. No native AppArmor compilation was performed here.
- `make build PYTHON=/usr/bin/python3`: exit 0, 1,838 payload members.
- Bounded archive/source/manifest comparison: all member bytes and hashes agree,
  canonical mode/uid/gid/mtime are 0644/0/0/0, expanded size 34,943,828 bytes.
  The preseed archive, manifest and bootstrap-source pins agree.
- `make inventory PYTHON=/usr/bin/python3`: exit 0 after the final Code-fix
  payload rebuild. Acquired 97 indexes, retained 21,359 package candidates and
  reported zero unavailable metadata requests. Both JSON payload hash/size
  pins agree with the archive, and the metadata cross-pin agrees with the
  current `inventory-apt.json` bytes. This collector does not verify APT Release
  OpenPGP signatures or perform an installation transaction.

| Product / changed source | SHA-256 |
| --- | --- |
| `d-i/forky/payload.tar.gz` | `440695273892e3d6e32521cfa7d54c8abcc1ffb937199a89c9f15d0fc7971d95` |
| `d-i/forky/payload.manifest` | `8135e98f7e1d349392f073c89d48d216d07c9f336b20abd073b9c0944a8c857c` |
| `d-i/forky/preseed.cfg` | `5234bd34f9a744a1e2212a34922d0ca3778775ab0981167f667c27d51b3085dc` |
| `inventory.json` | `a83e6c90f4b03bf5f4eaf61ddf1baee9ecabf5338d78816f9d2a22b0526aba56` |
| `inventory-apt.json` | `657c73f07fba6bb606fbf8c488766f0c51facef0ac8a0b45c814195ca9a9b686` |
| `hooks/target/etc/apparmor.d/calendars` | `05c67623276bedfa35006d5987556c2b886f466972e7d1aeda3bbf99f1a8b958` |
| `AppArmor/ManagedModes/Transition.pm` | `6ef843977b89deae06878d600f1e9c565d60068a36365c947267a8808aabb504` |
| `tests/test_boot_runtime_20260913.py` | `f2db20a33d435817ddbebb8a4c1f784052f28b7e394467baf2e7ba1743ff3a93` |
| `etc/systemd/system/podman-devops-bootstrap.service` | `365f35d04c8a842fcb224f6b86126b37df9bf41bab4a4395d3750140d66a7332` |
| `tests/test_podman_incus_redesign.py` | `9eeeaf3239d1439b81cba8018350b7845e266a3d74608ba8b0de4709c76a2e22` |
| `usr/local/bin/labwc-sync-application-launchers.tmpl` | `0dfaf981d981b469db8f94ca603a181d816cd5be522897b673d78b417f667a03` |
| `tests/test_primary_gpg_launch_gate.py` | `d77d70d8fb0d47a4189db4d1a840a507a01b88cd3480cb08a0e8123bae1c7ab5` |

The four changed runtime sources and three changed fixture sources have the
aggregate fingerprint
`54904d9dc7f0bf524f66ea9364e2c0d237d0773dece64d6ef149b3364ba65af5`.
It is SHA-256 over sorted UTF-8 lines `FILE_SHA256  REPOSITORY_PATH\n` for those
seven files. The archive is 26,629,914 bytes. No commit, push, installed-target
repair or deployment has been performed.
