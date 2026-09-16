# Computer Management review and targeted corrections

Date: 16 September 2026. Input: `debian-preseed-de(1).zip`.
Requested target: Debian unattended installation, systemd 261.2, labwc/wlroots desktop.

## Delivery and assurance boundary

This is the complete supplied repository with targeted launcher, policy, process-lifetime, installer-integration and failure-path changes. It is not a replacement project or a patch-only delivery. Existing source assets and configuration outside the listed changes are preserved. The generated preseed, payload archive and payload manifest have been rebuilt together. `CHANGES.patch` and `integrity.json` identify the changes; generated binary payload changes are represented by hashes, not reproduced in the textual patch.

The review follows all eleven Computer Management categories into their action helpers, privileged entry points, child executables and relevant AppArmor definitions. `ACTION_LEDGER.md` and `action-inventory.json` contain source-indexed action IDs, parameter selectors and dispatch branches. They deliberately distinguish source coverage from execution coverage: a selector, alias or literal ID is not an independently executed integration test.

This environment does not run the installed desktop, systemd 261.2, a loaded target AppArmor policy, the target GRUB/firmware/device layout, or the user's key stores. Missing Moo/MooX dependencies also prevent a number of complete Perl-application tests. Consequently, this delivery is a tested source revision with explicit target acceptance gates, **not a claim that every GUI action has been exercised successfully on the installed host**. See `TEST_RESULTS.md` and the included raw logs for the exact results and unresolved tests.

## Principal incident finding

The original global AppArmor disable action could request unloading the same managed profile sources used by the desktop, session, system helpers and application launch paths. These are not ordinary optional application profiles: named execution transitions and system-service `AppArmorProfile=` settings depend on their presence. This is a concrete unsafe dependency in the old disable implementation and is consistent with launch/service failures. It does not, by itself, establish the exact cause of the reported machine crash or the subsequent GPG/SSL symptoms.

The revision does not delete, replace, reinitialize, reimport or repair GPG keys, certificate stores, browser profiles, login credentials or home directories. No evidence was supplied that distinguishes actual key deletion from the wrong account/home, an inaccessible mount, an agent failure, a confinement denial, disk corruption or another incident. Those possibilities remain an investigation, not a concluded diagnosis.

### Changed AppArmor user interface and semantics

Global live "Disable All" has been replaced by **Disable AppArmor After Reboot**, with explicit confirmation that all AppArmor protection will be disabled after reboot. **Enable AppArmor After Reboot** provides the reverse operation. Neither action reboots the machine. Existing live policy remains loaded while the boot change is staged. The legacy global helper `disable` request is redirected to this staged path; it no longer unloads the live profile set.

Application mode choices are **Enforce** and **Complain**. Application-level unloading is rejected rather than silently translating "disable" into complain mode. Six core source files cannot be marked `disable` through the managed-mode configuration. Other existing configuration rows retain their original format. An already modified installation containing forbidden legacy core-disable rows needs administrator reconciliation; this change is not an automatic migration of arbitrary damaged installations.

Complain mode is a diagnostic mode, not equivalent to AppArmor being disabled: explicit deny rules may still apply. Audit mode controls additional logging and is distinct from enforcement mode. Global enforce/complain operates on the configured managed set rather than merely six wrapper sources. Per-application mode/audit changes are constrained to the existing application/profile mapping.

### Process ownership, serialization and recovery

The authorized root frontend starts a fixed template instance of `labwc-apparmor-policy@.service`. Valid instances are narrowly restricted to global/application enforce/complain, application audit enable/disable, boot enable/disable and managed-mode reload. The service owns the worker and children independently of the desktop terminal. It has finite start/stop limits, control-group cleanup, journal output and a private root-owned state directory. It is not attached to the graphical-session lifetime.

The service retains real host users, PIDs and block devices where necessary for legitimate GRUB/policy operations. It hides homes, has a private network and temporary directory, and makes the filesystem read-only except for explicit policy, backup, cache, state and GRUB locations. The audit backup directory is allowed by **both** the service mount policy and AppArmor. Exact package-owned parser/GRUB executables may use declared `PUx` fallback; this is an explicit compatibility boundary, not a claim that every command below them is confined by the wrapper's AppArmor policy. System-service mount/network restrictions remain applicable.

A shared root-owned, no-follow lock serializes cooperating policy workers and interactive profile tools. Root-owned regular-file and single-link checks protect the lock and relevant state. This does not coordinate arbitrary external root writers or promise kernel-wide atomicity across all profiles.

Mode configuration changes use same-directory atomic publication, synchronization, retained original data and checked reconciliation. On error the old source is restored and reconciled; rollback errors are reported and backups retained. A concurrently changed configuration is not blindly overwritten. Successful multi-profile kernel changes are still sequential; they are not a kernel transaction.

Audit changes preserve the actual original sources, run `aa-audit --no-reload` against validated absolute profile paths, validate modified policy, then reload it. Failure restores original bytes rather than trying to guess an inverse flag operation; failed recovery is reported and snapshots retained. Interactive draft activation likewise reports failed source/kernel rollback, preserves recovery files, and no longer loses workspace cleanup through a `return` inside a Perl `eval` block. Audit/draft snapshots are not represented as power-loss-atomic transactions.

### Boot transaction

`labwc-apparmor-boot-state` accepts only `enable`, `disable` or `recover`; it has no user-supplied path or environment-based path override. It edits the repository's specific `/etc/default/grub.d/35-security-core.cfg` fragment and generated `/boot/grub/grub.cfg`. The managed flag must have the expected simple format. Existing LSM ordering and other security arguments are preserved. Ambiguous, conflicting or non-managed layouts are rejected instead of guessed.

The helper validates trusted root-owned ancestry, file type, ownership, permissions, link count and bounded sizes; creates protected same-directory temporary files; bounds subprocess time and output; validates the generated GRUB syntax and every supported Linux boot entry; synchronizes files/directories; and records a durable recovery journal. It refuses to silently overwrite unrelated external changes. This stricter validation may deliberately reject custom/multi-OS GRUB layouts. That is a safe failure, not silent support for untested configurations.

`labwc-apparmor-boot-recover.service` is ordered before managed-mode reconciliation and consumes an interrupted boot transaction at the next start. Managed-mode boot reconciliation uses `ConditionSecurity=apparmor` so it is skipped when the kernel was intentionally booted without AppArmor. The journal only addresses this helper's two-file boot update, not arbitrary package-manager or firmware transactions.

## Category-by-category review

| Category | Action coverage and targeted result |
| --- | --- |
| Container Management | Reviewed ten per-container operations, inspect/remove for images, volumes and networks, and nine root-menu operations (pull/run/build/compose/create volume/create network/info/disk usage/events). Existing rootless devops engine and validated identifiers are retained. Query capture now has a combined 16 MiB limit and a deadline that also covers descendants holding pipes open. Timeout escalation retains ownership of the unreaped leader PID; there is no signaling a reused PID after reap. Interactive jobs keep the existing managed terminal path. |
| Remote Desktop | All nine top-level routes: direct/shared temporary connection, saved connection, direct/shared save, edit, delete, profile-folder opening and help. Sessions and profile-folder launch now use the managed application path. The session log is checked before truncation, rejecting symlinks, hardlinks and non-regular/non-owned files; writing handles short writes and bounds retained output to 1 MiB. Child cleanup is explicit. Existing server/certificate validation remains; no certificate-ignore shortcut or saved-password feature was added. |
| Endpoint Security | Security auditing; service inspection; firmware/CPU checks; rootkit and ClamAV operations; vulnerability/package integrity and hashing; all AppArmor status/generation/draft/mode/audit/reload actions; firewall status and validated rule changes. The principal changes are the staged boot operation, mandatory-profile retention, service ownership, serialization and checked rollback described above. Existing polkit/root action validation is retained. The new audit backup service permission is explicitly tested. |
| Digital Assets | All 47 catalog IDs match the action-dispatch IDs. Reviewed DOCX/PDF/Markdown/HTML/text/EPUB/image conversions, metadata and optimization routes, including user selections and output handling. `typst` and `pdfcpu` are now accepted through the exact root-owned release symlinks that the installer actually creates; arbitrary symlinked commands remain rejected. PNG optimization can overwrite its own reserved output using `-clobber`. Required PDF/document workspaces, fonts and conversion resources are granted in the relevant child profiles. FocusWriter receives only the launcher workspace addition, not a blanket new filesystem grant. |
| Users & Groups | All six existing operations: users, non-sudo users, groups, sudo administrators, passwordless accounts and sudo-access audit. Privileged reads remain authorized; no account-creation, password-reset or user-deletion feature was invented. The menu waits behind the independently managed action terminal. |
| Network Management | Reviewed connection profile activation/deactivation/deletion, VPN/WireGuard import and lifecycle, DNS settings, interface diagnostics, private/public scan selection, capture/replay and advanced adapter operations. Existing argument/UUID/address validation and authorized root boundaries are preserved. Resolved sysfs network paths and the capture parent directory have necessary policy access. MAC randomization attempts to restore an originally-up link even if the change fails, reporting both failures. No claim is made that disrupting the active network is connection-preserving. |
| System Configuration | Reviewed the 41 literal maintenance/diagnostic IDs, external-drive delegation and direct display/refresh/power-profile/keyboard/audio/dock actions. Audio control uses the managed application path. System overview no longer waits indefinitely for manager startup. Authorized root disk usage transitions to the exact `du` executable rather than inheriting an unsuitable home-only policy. Existing finite root-command limits, argument allowlists and confirmations remain. |
| Phone Management | Reviewed all 52 literal ADB/fastboot menu IDs against the runtime dispatch, including server/device diagnostics, shell/apps, transfer/capture, logs, reboot modes, wireless and fastboot routes. Added missing owned Android output-parent/sysfs reads and child-cleanup signal permission. Device/serial/remote-path checks and destructive-operation confirmations remain; no unrestricted new root or flash pathway was added. |
| Backup & Recovery | Reviewed all 21 troubleshooting IDs and shared backup-drive management. Session restarts, root service restarts, package repair, initramfs/GRUB, Timeshift, cache/zram/journal and Btrfs operations retain exact authorized commands and confirmations. The external-drive fix prevents a failed inventory command from being mistaken for "nothing mounted." Existing package/firmware/recovery jobs are not newly claimed to be immune to termination or power loss. |
| Hardware & Peripherals | Reviewed shared external-drive mount/unmount/power-off branches, Bluetooth controller/device operations and brightness selections. A failed disk snapshot aborts both pre/post-unmount decisions; no forced unmount or broad device-access rule was added. Bluetooth and brightness runtime sources did not need a speculative rewrite. Actual USB, Bluetooth, DDC/backlight and firmware behavior remains a physical-device acceptance gate. |
| AI & Copilots | Reviewed the complete 47-action backend argument contract and its Codex/Llama/Whisper menu parameter variants. Captured diagnostics use the existing bounded managed-process implementation (30 s / 4 MiB), not unbounded pipe reads. A typed Codex prompt is separated from options with `--`. Whisper audio control uses managed Pavucontrol. Existing model-selection/download validation is retained; no trust-policy bypass or new model provider was introduced. |

Several frontends now export `LABWC_MENU_ACTION_WAIT=1`, so they wait behind their already-managed action windows. The shared transient-terminal lifecycle was reviewed rather than rewritten unnecessarily. GUI D-Bus activation may hand work to an already-running application; this is not falsely described as owning every existing GUI process. No drive-by rewrite of Waybar, crystal-dock, labwc/wlroots session policy, allocator settings or resource-class tuning was made.

## Target acceptance gates before broad rollout

Use a disposable VM installed from this complete publication, plus a physical pilot host for device-specific actions. Keep a snapshot/recovery route and administrative console access. Do not first exercise global disable on the only machine holding the user's sole private keys. Existing incident evidence and encrypted/offline key backups should be preserved before any remediation; do not regenerate keys merely because a launcher cannot see them.

Verify the installed version and actual kernel policy, not only the source syntax:

```sh
systemd --version
systemctl --failed
systemctl --user --failed
sudo aa-status
sudo systemd-analyze verify \
  /etc/systemd/system/labwc-apparmor-policy@.service \
  /etc/systemd/system/labwc-apparmor-boot-recover.service \
  /etc/systemd/system/apparmor-managed-modes.service
```

Run every ledger route with representative valid input, cancelled selection, unavailable dependency/device and rejected input. For mutating actions use disposable containers, VM connections, accounts' read-only fixtures, removable test media and test phone data. Check both user and system journals for unexpected denials, service failures and cgroups left behind. Confirm terminal close behavior for commands expected to be cancelled versus the independently owned policy worker. Test document output creation in home and allowed mounted locations, server certificate rejection/acceptance, scan target restrictions, failed privilege prompts and Bluetooth/backlight hardware behavior.

For AppArmor, exercise application enforce/complain, audit enable/disable and global enforce/complain first. Confirm mandatory profiles remain loaded and Waybar, the dock, terminals, GPG-agent operations and TLS still work. In the disposable VM, stage disable and close the terminal while the worker runs; inspect its system journal and verify that live confinement is unchanged. Reboot normally; inspect `/proc/cmdline` and `/sys/module/apparmor/parameters/enabled`, then stage enable, reboot and confirm the managed policy is restored. Do not replace this sequence with `aa-teardown`, a blanket unload, or stopping the loader service.

Test failed/malformed GRUB generation, read-only/full filesystems, interrupted transactions and recovery from the administrative console. The supplied tests simulate these boundaries; they do not execute the real target GRUB hooks. Confirm the service sandbox permits the target's real block-device probes and boot layout. If a custom layout is refused, investigate and adapt its explicit contract; do not suppress the guard.

Useful read-only journal queries:

```sh
sudo journalctl -b -u 'labwc-apparmor-policy@*' --no-pager
sudo journalctl -b -u labwc-apparmor-boot-recover.service --no-pager
sudo journalctl -b -k --grep='apparmor|DENIED' --no-pager
journalctl --user -b --no-pager
```

For the prior key/certificate incident, compare the actual desktop account, `HOME`, `GNUPGHOME`, mounted home, key fingerprints, key-file existence/ownership, agent status and prior-boot logs with a known-good backup. Do not publish private key material in logs. The code revision neither establishes nor repairs lost secret-key bytes.

## Publication

Run repository build checks on the complete extracted tree and publish it as one atomic directory/release. Do not serve a new preseed with an old payload or copy only the edited launcher scripts. This is an unattended-install source release, not an automatic hot migration of an existing installation's root configuration.

```sh
python3 -B tools/build.py --check
```

Install exactly through the repository's existing staging mechanism; the new helpers and system units are explicitly staged and included in the verification list. Do not copy the source-tree file modes directly onto `/usr/local`: the installer intentionally applies runtime executable/configuration modes.

## Primary documentation consulted

- systemd, `systemd.exec(5)`: https://manpages.debian.org/unstable/systemd/systemd.exec.5.en.html (named profile requirements, protection and namespace semantics). This moving documentation is not a substitute for execution on systemd 261.2.
- systemd, `systemd.service(5)` and `systemd-run(1)`: https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html and https://www.freedesktop.org/software/systemd/man/latest/systemd-run.html (service ownership, completion and transient services).
- Linux kernel AppArmor documentation: https://docs.kernel.org/admin-guide/LSM/apparmor.html (boot selection and loaded policy).
- AppArmor 4.1.7, `aa-audit(8)`: https://manpages.debian.org/testing/apparmor-utils/aa-audit.8.en.html and upstream `utils/apparmor/tools.py`: https://gitlab.com/apparmor/apparmor/-/raw/v4.1.7/utils/apparmor/tools.py (absolute profile paths, audit flags and no-reload behavior).
- OptiPNG, `optipng(1)`: https://manpages.debian.org/testing/optipng/optipng.1.en.html (`-clobber` output behavior).

No downstream blog claim was used as a substitute for a primary command contract.
