# Audit remediation record — 17 October 2026

## Current status and accepted requirements

This records the current working tree, not acceptance of the complete audit.
Source repairs and authored fixtures do not establish successful installation,
loaded policy, recovery, hardware behavior or native application operation.
Several source findings and the native acceptance gates below remain open.
Do not use this record as release approval.

The user's corrections supersede the corresponding audit recommendations:

- **Legacy CUDA remains available with its explicit insecure archive policy.**
  The `addon/nvidia-legacy` class is independently selectable; the separate
  `addon/cuda-legacy` class requires it plus amd64. Selecting only the legacy
  NVIDIA driver does not stage the CUDA archive.
  Selection of `addon/cuda-legacy` authorizes the fixed Debian 12 amd64 HTTPS
  archive, with `trusted=yes`, `allow-insecure=yes`, `allow-weak=yes`,
  `allow-downgrade-to-insecure=yes`, `check-valid-until=no` and
  `check-date=no`. Refresh selects only `cuda-legacy-temp.list`. There is no
  required key download, authenticated-snapshot gate or global cryptographic
  policy change. Other repositories keep their existing authentication.
- **The exact UDisks order is `ntfs_drivers=ntfs,ntfs3`.** Native mounting was
  not exercised. This is the intended configuration order.
- Private Xwayland remains restricted to the existing Zoom/Discord route.
  Its implementation and configuration were not changed.

The CUDA class, selection module, shared source/refresh module and original
CUDA fixtures were restored byte-for-byte to `HEAD`. Their absence from the
final diff is intentional. The generated payload was rebuilt after restoration.
The supplied comprehensive audit remains unchanged.

## Evidence for this working tree

Base commit: `16282bfcfc771fbb0fed81135f4b276886766d9c`.

| Evidence | Result |
|---|---|
| Reviewed pure serialization | The reviewed command `/usr/bin/make build 'PYTHON=/usr/bin/python3 -I' SHELL=/bin/sh`, with environment restricted to `PATH=/usr/bin:/bin` and `LC_ALL=C.UTF-8`, completed after the publication, module-verification and ChatGPT candidate-validation changes; 1,797 payload files. |
| Build write inventory | Before/after metadata and SHA-256 comparison observed changes only to `d-i/forky/payload.tar.gz`, `payload.manifest`, and `preseed.cfg`. |
| Archive/source consistency | All 1,797 regular archive members match both current source bytes and manifest hashes; total source bytes: 34,511,077. Duplicate/traversal paths, modes `0644`, archive UID/GID zero and manifest membership were inspected as data. |
| Bootstrap pins | The generated preseed contains the current payload, manifest and bootstrap-source hashes. |
| Configuration invariants | Archived NTFS order and scoped insecure CUDA options were inspected as data. Four restored CUDA files have no diff from `HEAD`. |
| Static parsing | Python standard-library AST parsing of 33 changed Python sources (including the extensionless OBS and Aptly Python entrypoints) completed; XML parsing covers two changed documents. No repository module was imported. Perl was inspected as source data; no Perl compiler or BEGIN blocks were executed. |
| Whitespace | `git diff --check` completed with no findings. |
| Runtime tests and native validation | **Not run.** No approved disposable target/image identity was supplied. No host tests, test discovery, Perl imports/BEGIN blocks, shell syntax runners, policy parsers, service operations or package probes were executed. |
| Independent agent review | Unavailable: delegated read-only sidecars failed during encrypted-context hydration before reading files. No independent review result is claimed. |

Generated product SHA-256 values:

```text
payload.tar.gz  89d288bf32d1a29b900240a445b7cd94bfcc4fefe6ac55a5f83f6dfc9c829d2a
payload.manifest  0c3d413d9c11b354b7d534105b56768737999b3564bbd60d3530c8fa5458c5b7
preseed.cfg  9e7cc4f1d03e816f2a640251087a91f7045d2dd854ab3dcb328f93297c6c741f
```

The source fingerprint is SHA-256 over sorted records of
`four-digit-mode SHA256  relative-path\n` for the 2,299 unique direct regular files
listed by `git ls-files --cached --others --exclude-standard`. It excludes
the three generated products, this report and private input basenames
`preseed.env`, `git_ed25519`, `git_ed25519.pub` and `id_git_ed25519`.
The fixture fingerprint applies the same record format to the 256 included
paths containing `/tests/`.

```text
source:   315e45920753e72c45ef28f197e0069e0b413898c5804210bd5bdff6d0677978
fixtures: 013367d5b5c096e3e0b4ba048c91a6741c64fab2c04e8660dc1fcce00118b6b7
```

Target release requirement: Debian Forky, systemd 262. Disposable image,
systemd package build, interpreter/module and native-tool package versions:
**not measured; native acceptance remains unexecuted**.

## Corrections from the continuing implementation review

- A changed signed `InRelease` digest was insufficient to identify this
  operation. The publisher now sets Aptly 1.6.3's signed `Version` field to its
  unique snapshot name. Verification requires that exact signed identity,
  distribution/component fields and matching local Aptly snapshot metadata.
  A private synchronized receipt precedes the remote command. Native command
  success, pending propagation and an unknown command outcome remain distinct;
  pending/unknown operations block another managed mutation. The explicit
  `aptly-publish-local --reconcile DISTRIBUTION` route only reads and verifies
  the expected operation. It does not republish or discard an unresolved receipt.
  If local and remote state disagree, retain the receipt and staging for manual
  publisher recovery; a successful remote read alone cannot repair that state.
- Per-socket HTTPS timeouts did not bound DNS or repeated reads. Public Aptly
  fetching now uses packaged curl with configuration-file loading disabled,
  no redirects or proxy, a whole-transfer timeout, a native byte limit and the
  shared bounded capture runner. Clear-signed release parsing reads identity
  only inside one unambiguous signed envelope and avoids accumulating checksum
  continuation fields. Capture normalizes text line endings before verification
  and hashing; the recorded digest identifies those verified normalized bytes.
- Comparing kmod's `sig_key` with X.509 Subject Key Identifier was incorrect:
  its PKCS#7 implementation reports the issuer certificate serial number.
  That comparison has been removed. A bounded descriptor-based snapshot of a
  raw module and the managed public certificate is verified with packaged
  OpenSSL CMS. Embedded signer certificates are disabled. Skipping CA-chain
  discovery for the explicitly configured MOK does not skip content/signature
  verification. Same-name replacement keys and modified content must fail the
  authored cryptographic fixtures. A verifier error is distinct from an invalid
  signature; unproved verifier termination retains its private workspace.
  Module replacement is staged beside the original, synchronized and renamed;
  its containing directory is synchronized after replacement. The helper is
  staged before use with an explicit Python dependency and AppArmor grants.
- Native Aptly commands share the remaining 3,000-second operation budget
  rather than restarting a one-hour timeout at each step. Remote mutation has
  a separate finite five-second direct-child reap budget. The foreground
  process group is preserved for deliberate native GPG/pinentry interaction.
  Synchronous Secret Service calls and filesystem traversal are not yet covered
  by a separately cancellable worker; no full end-to-end deadline is claimed.
- ChatGPT preparation and finalization now validate the owned canonical policy
  candidate with explicit offline parser flags before touching defaults,
  diversions, the installed policy, compatibility links or package guards.
  Finalization rejects an unsupported execution context before any mutation.
  This closes the invalid-candidate ordering defect only. It does not supply
  the missing pre-preparation recovery snapshot or shared-writer serialization.

Relevant primary contracts: [Aptly 1.6.3 snapshot switch](https://github.com/aptly-dev/aptly/blob/v1.6.3/cmd/publish_switch.go),
[Aptly 1.6.3 publication metadata](https://github.com/aptly-dev/aptly/blob/v1.6.3/deb/publish.go),
[kmod PKCS#7 issuer and serial parsing](https://github.com/kmod-project/kmod/blob/master/libkmod/libkmod-signature-openssl.c),
[Linux 7.0 module signature writer](https://github.com/torvalds/linux/blob/v7.0/scripts/sign-file.c),
[OpenSSL CMS verification](https://docs.openssl.org/3.5/man1/openssl-cms/) and
[curl transfer limits](https://curl.se/docs/manpage.html).

These are source changes and fixture specifications. No native curl, OpenSSL,
kernel module, Aptly, AppArmor or failure-injection acceptance has been executed.

## Coverage against the comprehensive audit

“Source repair” below describes code present in this working tree. It does not
close the corresponding native or failure-injection gate. “Open” includes
implementation work as well as required operational decisions.

| Audit package | Source work present | Remaining work/gate |
|---|---|---|
| 1. Unattended verification | Helper is defined in the invoking account shell; package-format and embedded XML-query quoting boundaries repaired. | Execute the fully rendered route with outer values absent/present and exact arguments captured in the disposable target. |
| 2. Partition/EFI state | F2FS slots persisted and validated before finish mutations; reused FAT EFI is preserved irrespective of preferred label; custom handler registered for fresh encryption and dual boot. Recorded disk identity includes kernel `diskseq`; destructive early/finish calls recheck identity and partition/single-backed mapper membership. Sanitization enumerates actual sysfs partition children, avoiding `/dev/sda*` matching `/dev/sdaa`. Existing LUKS reuse checks the expected bootstrap key and home label. | Complete installer-native matrix, partition UUID/geometry handoff and replacement cases. Rechecking pathname identity does not pin the native tool's subsequent device open; do not claim atomic binding across that interval. |
| 3. Secure Boot | Installer removable-media copy contains public MOK files only. Enrollment deletion targets the current DER certificate. Existing managed-MOK raw modules and newly signed candidates undergo detached CMS verification against a private certificate snapshot. Bounded verifier cleanup preserves uncertain workspaces. Module replacement is staged and synchronized before rename. | Execute real kernel/sign-file and compressed-module fixtures. The separate distribution-module signer-name shortcut still needs cryptographic provenance/chain handling. Verify all boot/distribution artifacts; distinguish failed enrollment probes from confirmed absence; deliberate encrypted private backup, rotation and any previously exposed key recovery. |
| 4. Acquisition trust | User-required scoped insecure legacy CUDA behavior restored completely. | Moving initial vendor releases still need approved pins/signatures or an explicit maintained moving-release contract. Do not reintroduce an authentication requirement for legacy CUDA. |
| 5. Firewall | Private durable recovery receipt and owned live tables retained; manager timeout has a distinct outcome-unknown path; reload/restore verification; resolved-address exposure checks; unsupported multiple forwarding groups rejected. | Native nftables/systemd failure injection, semantic loaded-policy verification, interrupted recovery and reconciliation procedure. Keep standalone recovery separate. |
| 6. Notifications | ntfy defaults off with blank topic/token and explicit reader acknowledgement; current policy checked before send; queued disabled deliveries cancelled under the existing lock; Telegram remains independent. | Fixture execution, authenticated reader/publisher policy, restart/retry and concurrent policy edits. Already in-flight requests cannot be retracted. Publish policy edits atomically. |
| 7. Process lifecycle | Selected Python transport reaps bounded; Git streaming bounded; validator holds its leader through signals; ADB file-output runner has an outer monotonic deadline and finite reap, while interactive shells remain interactive; greeter discovery/monitor cleanup bounded; OBS status uses the shared bounded capture/deadline path. Aptly publication operations are serialized; native Aptly commands inherit the lock, and uncertain remote operations retain a durable receipt for read-only reconciliation. Shared Perl raw-status API preserved. | Remaining hardware/Whisper/Codex/SSH/vendor/diagnostic runners and language bridges; Aptly's complete operation deadline including native commands, interactive signing, keyring access and final cleanup; uncertain boot writer recovery; cgroup ownership and identity replacement failure injection. |
| 8. Resource limits | Bounded firewall/Git/OBS capture (OBS stdout and stderr combined, capped at 8 MiB); Aptly public InRelease has a 4 MiB body cap, bounded total capture and a native whole-transfer deadline; secondboot limits each initramfs listing to 16 MiB; Git-name counting is iterative. CMS verification snapshots raw modules up to 512 MiB, with signature/certificate caps of 1 MiB each and fixed-size copy buffers. Platform-Tools validates central-directory counts before ZIP object allocation, paths/types/duplicate names/implicit nodes and declared aggregate bytes before writes, with actual copy-byte and deadline limits. | Module decompression before the verifier, other archive/header/directory/provider limits and concurrent disk demand. A watchdog does not provide a filesystem quota. |
| 9. Persistent transactions | Key-bundle attempts recorded before possible commit; rollback removes only the published inode and synchronizes directories. ChatGPT canonical policy candidates are parsed offline before prepare/finalize mutations, and invalid finalization contexts fail before mutation. | Shared AppArmor writer lock and nested handoff; ChatGPT true previous-state snapshot before preparation/diversion, candidate identity binding and complete policy recovery/loaded-state verification after later failure. |
| 10. Package convergence | Discord recovery retains its validated previous receipt even when current content is invalid. Optional D-Bus cleanup requires authoritative package absence and exact owned alias/diversion identity. | Removal/reinstall native fixtures; complete source-set transactions; unchanged-release reconciliation; signing-key overlap and reader/pruner ownership. |
| 11. Download boundary | Existing stronger download paths retained. | Installer/affected vendor redirects must be checked before contact, using actual available installer tools; total retry/transfer deadlines; stable upload snapshots; authenticated initial deployment and immutable served generations. |
| 12. Boot/package completion | Three signing hooks propagate real failure; APT continuation repaired; durable secondboot initramfs pending marker survives failure and is cleared after each rebuilt image's bounded listing omits the temporary hooks and required TPM policy marking completes. | Bounded decompression/runtime and staged boot-artifact publication; failure/reboot matrix and proof that prior writers stop before recovery. |
| 13. Application/power lifetime | Graceful native supervision enabled consistently; direct application menu routes use managed launchers; independent root terminal-power reservation retained through handoff. | Native save/flush, duplicate/two-user requests and handoff failure gates. Existing save intervals and authorized force behavior are preserved. |
| 14. Output preservation | Recorder status and finalized-video checks; ADB keeps remote/partial recording on failed validation; ExifTool uses absent output; DOCX mutation unavailable; PDF limitation stated; OCR output uses a unique private directory and accepts legitimate empty text. | Native image/PDF/media/OCR failure, collision, cancellation and data-preservation cases. |
| 15. Security logging | Authentication-facility input requires trusted local producer identity; rejected input remains labelled application diagnostics; dropped TCP scan scenario is alert-only. | Native rsyslog producer/privilege-separation/parser/bouncer/rotation chain; CAPI/update ownership, selected audit coverage and bounded early diagnostics. |
| 16. zram/device cleanup | Incomplete scan cannot admit automatic targeted writeback; start/reset lock contention returns busy rather than successful skip. | Pressure/telemetry freshness, backing identity, mounted-descendant cleanup, hardware restoration ownership and endurance-budget scope. |
| 17. Effective authority | Unsupported forwarding group composition rejected; existing veth/rootless container/Incus/NFS boundaries retained. | Installed network, DNS, IPv6/VPN/DHCP, cgroup, sysctl, account and authorization gates. Source policy is not evidence of the final active system. |
| 18. Publication/credentials | OBS stored API-origin validation and metadata identity checks added; status capture is bounded and distinguishes output overflow, command failure and timeout before commit. Aptly checks the configured signing fingerprint, exact unique signed snapshot Version and local snapshot metadata. Publication uses a synchronized receipt and account-private lock retained by native commands. Read-only reconciliation precedes another mutation after uncertain completion. Pending propagation and unknown outcomes have distinct return statuses (75/76). Private input reads reject blocking special files, hardlinks and observed changes. | Execute stale-cache, delayed-propagation, commit-timeout and concurrent-writer fixtures; manual reconciliation of partial local/remote disagreement; whole-operation deadline; shared ancestry trust, multi-secret generation/unlink identity and Codex execution delivery. |
| 19. Runtime/dependency ownership | Existing pins/staging and private Xwayland components retained. | Retained dependency closure, private runtime update ownership, target interpreter/module versions, supported upgrade generations and accurate backup/forced-repair scope. |
| 20. Desktop results | Greeter probes bounded; actual options distinguished from harmless operands; affected shortcuts use automatic renderer selection; Bluetooth outcomes separated; exact requested NTFS order retained. | Native login/hotplug, renderer argument fixtures, portal/debugging/qBittorrent bus/appearance acceptance and effective NTFS driver. |
| 21. Workflow state/privacy | Git deadline/capture and unknown-cleanup evidence improved; Recoll excludes the actual credential-bearing vdirsyncer configuration and managed private SSH state; existing conservative firmware unavailability retained. | Native fake-secret indexing and custom private-export locations; Git index/recovery and multi-provider results, history versus reuse policy, model headroom, bounded queues, account identity, trusted configuration quoting and grant review. |
| 22. Release evidence | Fresh validation run directories; finite stage cleanup; release inventory classifies directory symlinks before directory handling and excludes actual/previous evidence; image copy preserves links for explicit classification. Products rebuilt and compared as data. | Execute authored fixtures; provide the separately approved disposable installed-target workflow and exact image/package identities; complete native acceptance without weakening the source-test guard. |

## Required next acceptance boundary

Follow `docs/test-isolation.md`. No unavailable image permits a development-host
fallback, including syntax runners, imports, management helpers or policy loads.
An installed-target test environment needs its own kernel where required,
managers, package tree, security policy, network, devices and sockets, with no
host mounts or sockets. Provisioning or contacting a target has not occurred.

For each enabled profile, retain the image identity, package versions, source
and fixture fingerprints, product hashes, actual cases run, skips/failures and
retained recovery paths. In particular, test disk/EFI preservation, exact
policy recovery, manager late completion, simultaneous writers/pruning,
identity replacement, pipe/output overflow, finite cancellation, first/second
boot and native/private application launch/shutdown. Hardware and firmware
claims require designated disposable hardware/firmware acceptance.

The changed fixtures are specifications awaiting execution. They must not be
reported as passing mocks or native integration merely because AST parsing or
archive serialization succeeded.

## Changed paths

This inventory includes earlier uncommitted remediation work retained during this continuation. The four restored CUDA paths are described above and therefore do not appear as modifications.

- `d-i/forky/hooks/installer/partman/btrfs-early.sh`
- `d-i/forky/hooks/installer/partman/early.sh`
- `d-i/forky/hooks/installer/partman/f2fs-early.sh`
- `d-i/forky/hooks/installer/partman/finish.d/99-storage-layout.sh`
- `d-i/forky/classes/class-auto/arch/amd64.cfg`
- `d-i/forky/classes/class-auto/arch/arm64.cfg`
- `d-i/forky/hooks/target/etc/apparmor.d/desktop-wrappers.tmpl`
- `d-i/forky/hooks/target/etc/crowdsec/scenarios/nftables-tcp-scan.yaml`
- `d-i/forky/hooks/target/etc/kernel/header_postinst.d/zz-sign-kernel-headers.tmpl`
- `d-i/forky/hooks/target/etc/kernel/postinst.d/zz-sign-kernel.tmpl`
- `d-i/forky/hooks/target/etc/kernel/postrm.d/zz-sign-kernel-cleanup.tmpl`
- `d-i/forky/hooks/target/etc/labwc/plans.conf.tmpl`
- `d-i/forky/hooks/target/etc/rsyslog.d/20-auth.conf.tmpl`
- `d-i/forky/hooks/target/etc/apparmor.d/system-wrappers.tmpl`
- `d-i/forky/hooks/target/etc/skel-desktop/.config/labwc/menu.xml.tmpl`
- `d-i/forky/hooks/target/etc/skel-desktop/.config/labwc/rc.xml.tmpl`
- `d-i/forky/hooks/target/etc/skel-desktop/.recoll/recoll.conf`
- `d-i/forky/hooks/target/etc/udisks2/mount_options.conf`
- `d-i/forky/hooks/target/usr/libexec/install-tools/secure-boot-tool.tmpl`
- `d-i/forky/hooks/target/usr/libexec/install-tools/verify-module-signature.py`
- `d-i/forky/hooks/target/usr/local/bin/labwc-bluetooth.tmpl`
- `d-i/forky/hooks/target/usr/local/bin/labwc-capture.tmpl`
- `d-i/forky/hooks/target/usr/local/bin/labwc-greeter-output`
- `d-i/forky/hooks/target/usr/local/bin/labwc-ocr`
- `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/apt-repo-local/APTRepoLocal/Servicing/Discord.pm`
- `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/apt-repo-local/APTRepoLocal/Servicing/ChatGPT.pm`
- `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm`
- `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Metadata.pm`
- `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/labwc-adb/AndroidADB/ADB/Transfer.pm`
- `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/labwc-adb/AndroidADB/Command.pm`
- `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/labwc-adb/AndroidADB/Config.pm`
- `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/zram-writeback/Zram/Policy.pm`
- `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/zram-writeback/Zram/Setup/Lifecycle.pm`
- `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/zram-writeback/Zram/Setup/Lock.pm`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/key_manager/core.py`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_compz/isolation.py`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_firewall/cli.py.tmpl`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_firewall/files.py`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_firewall/nftables.py`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_firewall/validation.py`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/commands.py`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/sandbox.py`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/managed_workflows/fs.py`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/managed_workflows/process.py`
- `d-i/forky/hooks/target/usr/local/libexec/apt-refresh-lists.tmpl`
- `d-i/forky/hooks/target/usr/local/libexec/aptly-publishing`
- `d-i/forky/hooks/target/usr/local/libexec/bluetooth-controller-init`
- `d-i/forky/hooks/target/usr/local/libexec/dbus-broker-maintain`
- `d-i/forky/hooks/target/usr/local/libexec/labwc-admin-action-worker`
- `d-i/forky/hooks/target/usr/local/libexec/labwc-plans.pl`
- `d-i/forky/hooks/target/usr/local/libexec/obs-publishing`
- `d-i/forky/hooks/target/usr/local/libexec/obsidian-git-sync.py`
- `d-i/forky/hooks/target/usr/local/sbin/nft-policy-generate.py`
- `d-i/forky/payload.manifest`
- `d-i/forky/payload.tar.gz`
- `d-i/forky/preseed.cfg`
- `d-i/forky/scripts/desktop/android-platform-tools-extract.py`
- `d-i/forky/scripts/desktop/android-platform-tools.sh`
- `d-i/forky/scripts/desktop/components/desktop-config.sh`
- `d-i/forky/scripts/desktop/verify.sh.tmpl`
- `d-i/forky/scripts/firstboot/assets/etc/apparmor.d/firstboot.tmpl`
- `d-i/forky/scripts/firstboot/assets/var/lib/firstboot/bin/secondboot-cleanup`
- `d-i/forky/scripts/late/grub.sh`
- `d-i/forky/scripts/partman/detect-disk.sh`
- `d-i/forky/scripts/preseed/answers.sh`
- `d-i/forky/scripts/runtime/f2fs.sh`
- `d-i/forky/tests/test_dbus_broker.py`
- `d-i/forky/tests/test_desktop_release_integrity_20261005.py`
- `d-i/forky/tests/test_aptly_publication.py`
- `d-i/forky/tests/test_gitbuild_appearance_20260928.py`
- `d-i/forky/tests/test_installer_hardening.py`
- `d-i/forky/tests/test_key_manager_lifecycle_20261014.py`
- `d-i/forky/tests/test_layout_followup_20260923.py`
- `d-i/forky/tests/test_maintenance_20261004.py`
- `d-i/forky/tests/test_notification_policy_20261017.py`
- `d-i/forky/tests/test_process_capture.py`
- `docs/audit-remediation-20261017.md`
- `tools/release_audit.py`
- `tools/stage_process.py`
- `tools/test-init.py`
- `tools/tests/test_policy_file_classification.py`
- `tools/tests/test_scoped_lifecycle_keyrings.py`
- `tools/validate.py`
