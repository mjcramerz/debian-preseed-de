# GitOps and managed log review - 2026-10-07

## Scope and environment

All 48 regular files under `todo/` were read: 2,363,443 bytes and 15,341 lines,
including 23 empty files. The managed subset contains 45 files and 15,158 lines.
The inventory below includes the separate qBittorrent evidence files.

The working tree was initially clean on `mcr/main`. Validation used the ordinary
workspace account on Debian Forky, Python 3.14.8, Git 2.53.0, systemd 262-1,
AppArmor 4.1.8-2, util-linux 2.42.4-1 and the packaged dash/BusyBox interpreters.
The intended installed target remains Forky with systemd 261.2. No software was
compiled, hosted Git repository changed, policy loaded into the kernel, service
restarted, or system installed. Review agents were unavailable because the
runtime could not decrypt their contexts; the review and integration were
performed by the coordinating agent.

## Repairs and installer wiring

### GitOps reference transaction

`todo/gitops:121` records the local failure after successful GitLab and GitHub
publication: `symref-delete: cannot operate with deref mode`. HEAD was left
detached at its original commit. The stdin `option no-deref` in the local
transaction only applied to the next ref command. Later symbolic remote HEAD
deletions therefore failed. Tag clear had the corresponding `symref-verify`
failure. This behavior is specified in the
[Git update-ref reference](https://git-scm.com/docs/git-update-ref).

The canonical engine now invokes `update-ref --no-deref --stdin` for the complete
transaction. All expected object IDs and symbolic targets remain checked, and
publication retains the existing prepare/commit boundary. Branch clear removes
obsolete symbolic tracking HEAD refs directly; tag clear verifies and preserves
them. The recovery journal, candidate refs, private bundle, remote leases and
HEAD reattachment remain in the existing flow.

Two real local Git fixtures reproduced both errors before the fix and pass with
it. The existing interrupted-publication test now includes a symbolic origin
HEAD and verifies recovery from the detached state after remote success. The
clear suite also exercises retained tags, both provider roles, failed pushes,
concurrent writers, graph/tree preservation and final upstream configuration.
Git transport, transactions and garbage collection are real in disposable
local repositories; provider APIs are mocked.

`scripts/desktop/components/target-assets.sh` stages the engine as root-owned
0755 and the aliases/documentation as 0644. Its account skeleton includes
`/etc/gitops/aliases.gitconfig`; `components/user-config.sh` copies `.config/git`
and `.config/gitops` into the account. The desktop verifier and firstboot
validation check these files, ownership and private account modes. No new
installation route or compatibility copy is needed.

For an affected installed checkout that retains `.git/gitops-clear.json`, use
the corrected installed engine and rerun `git mcr-branch-clear --apply` in that
checkout. Its saved selection and remote plan are resumed, including a detached
HEAD. A changed local/remote state still causes refusal. This review did not
recover or rewrite the real checkout named in the supplied historical log.

### Initramfs diagnostic redaction

The seven stage logs show `iommu.passthrough=REDACTED`, although the intended
setting is a boolean security parameter. The health helper's broad credential
filter matched the word `pass` inside `passthrough`.

The canonical `scripts/firstboot/assets/etc/initramfs-tools/scripts/installer-health-common`
now preserves only the exact `iommu.passthrough=0` and `=1` tokens. All other
values retain the existing redaction. Password, wireless credential, token,
secret and API-key assignments remain redacted. The parameter's boolean
semantics are documented in the
[kernel parameter reference](https://www.kernel.org/doc/html/latest/admin-guide/kernel-parameters.html).
No kernel setting or boot policy was changed.

The shell regression executes the actual helper against a substituted private
cmdline file in dash and BusyBox ash. It checks both accepted booleans, adjacent
credentials, and unexpected/malformed values. The fixture invokes no boot stage
or service. `scripts/late/core.sh` already stages this common helper and all seven
stage hooks; firstboot imports their private `/run` spool. The existing
secondboot cleanup removes the temporary health hooks after collection.

## Managed evidence findings

| Evidence | Finding and disposition |
| --- | --- |
| `apps/apps.log:389`, `todo/qbittorrent` | The 5.2.4 crash stack reaches the Adwaita Qt focus painter. The existing launcher already sets Fusion in the managed application configuration and Bubblewrap environment. Tests confirm the repair in all launch modes and preservation of unrelated preferences. No duplicate source edit was made. |
| `security/apparmor/apparmor.log:425`, `todo/qbittorrent-apparmor` | All 365 DENIED records are qBittorrent file requests: one `/sys/block/` listing, 160 account-owned `cmdline` reads, 200 account-owned `stat` reads, and four account-owned terminal inherit requests. The existing shared `qbittorrent-runtime` abstraction covers the direct and Bubblewrap profiles. Native parser output verifies the effective grants and absence of foreign-account proc/terminal access, process environments and sysfs data access. |
| `security/audit/auditd.log` | Confirms the same AppArmor events and two qBittorrent SIGSEGV events. Other unsuccessful syscalls are missing-file removals and nonempty-directory removals; they do not establish another application access failure. Raw arguments and process titles were not copied into this report. |
| `apps/apps.log:382` | Ten Waybar GTK accelerator assertions coincide with the qBittorrent crash/tray activity. All five installer-owned native menu templates already have a real accelerator group on every menu. The focused template test passes. The supplied log does not identify the runtime menu causing these remaining assertions; reproducing tray behavior on the installed desktop remains necessary. |
| `apps/apps.log:205` | Waypaper reports no monitor enumerator and falls back to All. The log records successful managed wallpaper operation. No Xwayland or monitor-policy change is supported by this message. |
| `apps/apps.log:180,293` | Crystal Dock reports a LayerShellQt deprecated property and missing application metadata for the LXQt file chooser service. These are packaged component/service metadata findings. No replacement dock, source build or synthetic portal launcher was introduced. |
| `apps/apps.log:271,285` | Vivaldi cannot read optional search-engine files and its UI attempts to load a NoScript image that the extension does not expose. These are vendor/browser-extension findings; the repository's user-adjustable extension settings remain intact. |
| `apps/apps.log:341` | One 29 ms libinput delay is reported. It does not establish a persistent scheduling or hardware-tuning defect. |
| `apps/apps.log:54` | The global compositor cannot start `/usr/bin/Xwayland`. The source retains the required private Zoom/Discord compatibility model. All payload members outside the three repairs are byte-identical to the original snapshot. |
| `security/crowdsec/crowdsec.log:79,86` | Console synchronization runs before the enrollment request is accepted. `system/system.log:705-712` records the request as pending approval, with successful bootstrap. Central API registration succeeds, the bouncer authenticates, and the community blocklist supplies 15,000 decisions. Console approval remains an account action. Duplicate grok registration warnings remain packaged parser behavior. |
| `security/crowdsec/crowdsec_api.log` | All recorded local API responses are successful. No API secret is included in this report. |
| `security/fail2ban/fail2ban.log` | The SSH journal jail starts successfully with its persistent database and intended escalation settings. |
| `security/nftables/nftables.log` | All 57 supplied records are accepted output traffic. No NFS rejection is shown. |
| `security/auth/auth.log`, `security/apparmor/modes.log` | Authentication records show ordinary sessions/authorized operations. Mode handling skips absent optional programs as designed; the logs do not request installing them. |
| `system/initramfs/*` | Root-device resolution succeeds without a local-block retry. Local-bottom and init-bottom show the root mounted and target paths present. The IOMMU redaction error above is repaired. |
| `system/system.log` | NFS identity/server services and the server home bind start successfully. Tailscale's initial state warnings clear. The secondboot multiple-trigger message concerns omitted source-status propagation; cleanup checks its own completion markers and does not depend on the `MONITOR_*` environment. |
| `system/kernel.log:965,1114,1166` | ACPI firmware errors, the RMI descriptor warning and correctable PCIe link errors require hardware/firmware diagnosis. The PCIe device in the new errors is not the NVMe device targeted by the existing workaround. No global AER, IOMMU, mitigation or driver restriction was weakened. |
| `system/usb/usb.log`, `system/zram/zram.log`, `system/timeshift/timeshift.log` | USB enumeration, encrypted zram writeback setup and below-pressure maintenance, and GRUB snapshot refresh are recorded without a new failure. |
| Empty model, storage, firmware and scan logs | No event to repair is present. Empty files do not demonstrate that a model, scanner, timer or live service passed acceptance. |

## Validation

The following commands ran from the repository root and passed. The selections
contain 86 tests with zero skips; repeated runs of the new redaction tests are
counted once.

| Command | Result |
| --- | --- |
| `python3 -B -m unittest discover -s d-i/forky/tests -p test_gitops_clear.py -v` | 34 tests, including real local ref publication/recovery. |
| `python3 -B -m unittest discover -s d-i/forky/tests -p test_gitops_mirrors.py -v` | 16 tests; local Git transports with mocked provider APIs. |
| `python3 -B -m unittest discover -s d-i/forky/tests -p test_managed_git_debugsys.py -k RealGitTests -v` | 20 protected-sync/branch/policy tests. |
| `python3 -B -m unittest discover -s d-i/forky/tests -p test_compz_qbittorrent_followup.py -v` | 8 existing launch/configuration tests. |
| `python3 -B -m unittest discover -s d-i/forky/tests -p test_apparmor_incidents_20261004.py -k native_parser_permissions -v` | 1 effective-policy test; native offline parser, no kernel policy load. |
| `python3 -B -m unittest discover -s d-i/forky/tests -p test_native_multimonitor_20260924.py -k native_dropdown_menus -v` | 1 menu-template test; no live Waybar/tray execution. |
| `python3 -B -m unittest discover -s d-i/forky/tests -p test_native_logging_r4.py -k NativeWiringTests -v` | 4 logging integration checks. |
| `python3 -B -m unittest discover -s d-i/forky/tests -p test_native_logging_r4.py -k InitramfsCmdlineTests -v` | 2 tests, 12 shell fixture cases across dash/BusyBox. |
| `shellcheck --shell=sh d-i/forky/scripts/firstboot/assets/etc/initramfs-tools/scripts/installer-health-common` | No diagnostics. |
| `python3 -B tools/build.py` | Rebuilt 1,704 payload members; existing policy gates passed, no browser artifacts changed. |
| `python3 -B tools/build.py --check` | Snapshot, manifest, preseed pins and browser artifacts current. |
| `python3 -B tools/check_shells.py` | 350 shell files, 711 parser checks passed. |
| `python3 -B tools/check_preseeds.py` | 59 files passed; all four generated commands survived private debconf read-back unchanged. |
| `git diff --check` | No whitespace errors. |

A separate read-only tar/hash comparison verified all 1,704 members against
their canonical source bytes and manifest SHA-256 values. The member set and
all other member bytes are unchanged. Exactly three members differ: the GitOps
engine, its README template and the health common helper. Current payload and
manifest hashes are included in the generated preseed. Existing Python
EncodingWarnings in untouched utilities were visible and were not suppressed.

Broad regression suites were not rerun; their previously recorded failures in
`BUILD-STATUS.md` remain unresolved. There was no live Forky/systemd 261.2
installation, enforcing-policy/application acceptance, NFS mount/access test,
hardware boot or provider authentication/remote publication test. Publish the
complete checked snapshot with an atomic deployment-directory switch and use
the target environment for those acceptance checks.

## Complete evidence inventory

Paths are relative to `todo/`. Every empty file was included in the read pass.

| Path | Lines |
| --- | ---: |
| `gitops` | 134 |
| `managed/apps/apps.log` | 519 |
| `managed/models/openai/chatgpt/chatgpt.log` | 0 |
| `managed/models/openai/chatgpt/runtime/codex-login.log` | 0 |
| `managed/models/openai/chatgpt/runtime/codex-tui.log` | 0 |
| `managed/models/openai/codex/codex-login.log` | 0 |
| `managed/models/openai/codex/codex-tui.log` | 0 |
| `managed/models/whisper/whisper.log` | 0 |
| `managed/security/apparmor/apparmor.log` | 1304 |
| `managed/security/apparmor/modes.log` | 22 |
| `managed/security/audit/auditd.log` | 10434 |
| `managed/security/auth/auth.log` | 53 |
| `managed/security/chkrootkit/chkrootkit.log` | 0 |
| `managed/security/chkrootkit/daily.log` | 0 |
| `managed/security/chkrootkit/daily.log.raw` | 0 |
| `managed/security/chkrootkit/log.expected` | 0 |
| `managed/security/clamav/clamav.log` | 0 |
| `managed/security/clamav/freshclam.log` | 0 |
| `managed/security/clamscan/clamscan.log` | 0 |
| `managed/security/crowdsec/crowdsec-firewall-bouncer.log` | 18 |
| `managed/security/crowdsec/crowdsec.log` | 149 |
| `managed/security/crowdsec/crowdsec_api.log` | 127 |
| `managed/security/debsecan/debsecan.log` | 0 |
| `managed/security/debsums/debsums.log` | 0 |
| `managed/security/fail2ban/fail2ban.log` | 19 |
| `managed/security/lynis/lynis-report.dat` | 0 |
| `managed/security/lynis/lynis.log` | 0 |
| `managed/security/lynis/scan.log` | 0 |
| `managed/security/nftables/nftables.log` | 57 |
| `managed/security/rkhunter/rkhunter.log` | 0 |
| `managed/security/rkhunter/scan.log` | 0 |
| `managed/security/spectre-meltdown-checker/spectre-meltdown-checker.log` | 0 |
| `managed/system/fwupd/security-scan.log` | 0 |
| `managed/system/initramfs/01-init-top.log` | 48 |
| `managed/system/initramfs/02-init-premount.log` | 47 |
| `managed/system/initramfs/03-local-top.log` | 50 |
| `managed/system/initramfs/04-local-block.log` | 5 |
| `managed/system/initramfs/05-local-premount.log` | 25 |
| `managed/system/initramfs/06-local-bottom.log` | 33 |
| `managed/system/initramfs/07-init-bottom.log` | 94 |
| `managed/system/kernel.log` | 1176 |
| `managed/system/storage/storage.log` | 0 |
| `managed/system/system.log` | 854 |
| `managed/system/timeshift/timeshift.log` | 2 |
| `managed/system/usb/usb.log` | 117 |
| `managed/system/zram/zram.log` | 5 |
| `qbittorrent` | 48 |
| `qbittorrent-apparmor` | 1 |
