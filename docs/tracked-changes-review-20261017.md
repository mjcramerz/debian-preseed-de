# Tracked-change integration review — 17 October 2026

## Scope and disposition

Base commit: `16282bfcfc771fbb0fed81135f4b276886766d9c`.

The review began with `debian-preseed-de-audit.md` and used its findings,
component boundaries and acceptance matrix. All 77 tracked modifications
present at intake were read as diffs against HEAD. The final inventory below
contains 78 tracked modifications because this review also extends the existing
LAN-sharing regression file. The three generated products were inspected as
archive, manifest and bootstrap data. Required untracked delegates and fixtures
were read, including the module-signature verifier, Platform-Tools extractor,
notification fixtures, Aptly fixtures and stage runner.

Existing changes were retained. Review concentrated on caller/delegate
integration, installer state handoff, fixed command arguments, process ownership,
recovery, artifact limits, dependency staging and AppArmor access. It does not
certify every unchanged branch or close all items in the earlier audits.
Independent sidecars failed during encrypted-context initialization, including
fresh-context retries; no independent review result is claimed.

## Corrections made in this review

### 1. Sensitive-service guard rejected the configured LAN

The changed guard treated every range outside its hard-coded local-address list
as public exposure. The existing LAN-sharing fixture uses a globally numbered
IPv6 /64 and exact managed Ethernet/Wi-Fi interfaces. This caused the reported
`services.lan_share_http: sensitive service has a public allowlist` rejection.

The guard now resolves both direct CIDRs and named CIDR groups, then collapses
each address family before checking for unrestricted coverage. Explicit subnets
remain valid, including globally numbered LAN prefixes. Direct default routes,
aliases containing default routes, and split ranges whose union covers an
entire family still require the existing explicit public-service override.
Unknown/empty named groups fail closed. The installer does not add
`--allow-public-sensitive`.

Integration traced: `scripts/late/security.sh` prepares managed network state
and renders `nftables_lan_share_service_placeholder_map`; the
`etc/nftables/services/lan-share.yml.tmpl` overlay carries exact enabled-family
subnets and managed interfaces; the staged generator validates and serializes
the selected profile/overlays using `--write --summary`; the existing nftables
unit is enabled for the installed system. No service activation was executed.

Three regression methods were added to
`d-i/forky/tests/test_logged_failures_20260927.py`: explicit global subnets
through the real policy-rendering fixture; direct/aliased/mixed default-route
coverage including split /1 ranges in both families; and unknown aliases.
These fixtures have not been executed.

### 2. Interruption could remove firewall recovery after partial publication

`PendingMutation.install()` previously left `rollback_failed` false until
live reload. An interruption after its first rename, including during directory
synchronization, could therefore reach `_apply_rules()`'s unconditional cleanup
and remove the recovery backups while persistent files were only partly
published.

The existing recovery-retention flag is now set before the first rename.
The transaction owner clears it after verified application or successful
restoration. No second lock or recovery protocol was added. The added fixture
in `tools/tests/test_scoped_lifecycle_keyrings.py` interrupts directory sync
after the first commit and requires both prior-byte backups and the receipt
to survive cleanup. This fixture has not been executed.

## Exact paths changed by this review

- `d-i/forky/hooks/target/usr/local/sbin/nft-policy-generate.py`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_firewall/files.py`
- `d-i/forky/tests/test_logged_failures_20260927.py`
- `tools/tests/test_scoped_lifecycle_keyrings.py`
- `d-i/forky/payload.tar.gz`
- `d-i/forky/payload.manifest`
- `d-i/forky/preseed.cfg`
- `docs/tracked-changes-review-20261017.md`

The other tracked modifications in the inventory were reviewed and preserved.
Private Xwayland eligibility remains exactly Discord and Zoom. No Xwayland
implementation/configuration, nvidia-legacy or cuda-legacy source was changed
by this review. No software was compiled.

## Verification actually completed

| Activity | Observed result | Limit |
|---|---|---|
| Source/diff and caller inspection | All tracked diffs read; relevant untracked delegates and fixtures inspected. | Static review, without executing the installed workflows. |
| Python AST parsing | 35 changed/new Python sources, templates and extensionless entrypoints parsed as data. | No repository imports, dependency check or target interpreter execution. |
| Whitespace | `git diff --check` returned 0 with no output. | Diff formatting only. |
| Reviewed generation path | Clean-environment pure serialization completed; 1,797 payload members. | No tests, validators, browser generators, policy parser or management helper executed. |
| Archive/source/manifest comparison | All 1,797 members match current source bytes and SHA-256 records; 34,511,233 content bytes. | Serialization consistency only. |
| Archive metadata | Regular members only; unique contained paths; mode 0644; UID/GID/mtime zero; empty owner names. | Does not establish installed ownership/modes after staging. |
| Bootstrap pins | Payload, manifest and bootstrap-source hashes occur in generated preseed. | No unattended installation executed. |
| Build write accounting | Only the three permitted product files changed; containing directory timestamp changed as expected. 3,101 other checkout entries retained their recorded metadata. | The initial comparison was corrected to account for the parent directory timestamp; no source mismatch was observed. |
| Tests, native validation and deployment | Not run. | No approved disposable image/target identity supplied; host execution is prohibited. |

Exact generation command:

```sh
/usr/bin/env -i PATH=/usr/bin:/bin LC_ALL=C.UTF-8 /usr/bin/make build 'PYTHON=/usr/bin/python3 -I' SHELL=/bin/sh
```

Data-only AST, archive, membership, hash and metadata inspection used
`/usr/bin/python3 -I -B -` with only explicit standard-library inspection code.
No shell syntax runner, Perl compiler/BEGIN block, unittest discovery, native
policy parser, package probe or host service operation was invoked.

## Fingerprints for this reviewed snapshot

```text
payload.tar.gz   7500f2ac5fdd39ebf88ccb9329253087313a86864513061737858c87fa4750a2
payload.manifest 2ede1af90ba10e595f18fd611d272096b99b5acee80a28496c9b9e6ec4b40a52
preseed.cfg      7f9df130a6aa5f053f6bf50755e3bb1ea028f11f6201623348aef68577860257
source          96530b517af1da50dbb14c09cfdcb65cd6fa722364b11e503e3df1289ac417ac
fixtures        8270b2909c765a2d72eccd5f8e56326f05523a21ea087516a8d1339a1ff4924b
```

Source fingerprint: SHA-256 over sorted
`four-digit-mode SHA256  relative-path\n` records for 2,310 unique direct regular
files from `git ls-files --cached --others --exclude-standard`, excluding the
three products, this report and private input basenames `preseed.env`,
`git_ed25519`, `git_ed25519.pub`, `id_git_ed25519`.

Fixture fingerprint: SHA-256 over sorted
`relative-path NUL raw-SHA256-digest` records for all 256 regular fixture files
under `d-i/forky/tests` followed by `tools/tests`, excluding bytecode caches.

These product hashes supersede the earlier snapshot hashes in
`docs/audit-remediation-20261017.md`; that record was preserved as historical
evidence. Current generated products match their current source inputs.

## Remaining acceptance and deployment risks

Follow `AGENTS.override.md` and `docs/test-isolation.md`. This review supplies
no host-test fallback. The required target is Forky/systemd 262, but an approved
disposable image identity, native package versions and installed runtime
evidence were not supplied or measured.

Required gates include execution of the four added regression methods;
rendered installer/profile coverage; native nftables validation and
loaded-policy semantics; manager late completion and recovery failure;
interrupted publication; concurrent writer/cleanup and identity replacement;
disk/EFI/encryption preservation; native module signing and compressed-module
handling; first/second boot; notification dispatch; service/cgroup cleanup;
and native application plus private Zoom/Discord launch/shutdown.

The broader implementation gaps already recorded in
`docs/audit-remediation-20261017.md` remain open. Examples visible in current
source include the separate Debian signer-name shortcut in
`module_has_debian_signature()`, incomplete shared AppArmor transaction
serialization/previous-state recovery, and operation paths whose synchronous
credential or filesystem work has no cancellable total deadline. The desktop
firewall's loaded-rule check currently compares rule comments/order; it is not
complete semantic verification of match expressions and verdicts.
These are not marked accepted by the source review or payload rebuild.

## Complete tracked-diff inventory

- `d-i/forky/classes/class-auto/arch/amd64.cfg`
- `d-i/forky/classes/class-auto/arch/arm64.cfg`
- `d-i/forky/hooks/installer/partman/btrfs-early.sh`
- `d-i/forky/hooks/installer/partman/early.sh`
- `d-i/forky/hooks/installer/partman/f2fs-early.sh`
- `d-i/forky/hooks/installer/partman/finish.d/99-storage-layout.sh`
- `d-i/forky/hooks/target/etc/apparmor.d/desktop-wrappers.tmpl`
- `d-i/forky/hooks/target/etc/apparmor.d/system-wrappers.tmpl`
- `d-i/forky/hooks/target/etc/crowdsec/scenarios/nftables-tcp-scan.yaml`
- `d-i/forky/hooks/target/etc/kernel/header_postinst.d/zz-sign-kernel-headers.tmpl`
- `d-i/forky/hooks/target/etc/kernel/postinst.d/zz-sign-kernel.tmpl`
- `d-i/forky/hooks/target/etc/kernel/postrm.d/zz-sign-kernel-cleanup.tmpl`
- `d-i/forky/hooks/target/etc/labwc/plans.conf.tmpl`
- `d-i/forky/hooks/target/etc/rsyslog.d/20-auth.conf.tmpl`
- `d-i/forky/hooks/target/etc/skel-desktop/.config/labwc/menu.xml.tmpl`
- `d-i/forky/hooks/target/etc/skel-desktop/.config/labwc/rc.xml.tmpl`
- `d-i/forky/hooks/target/etc/skel-desktop/.recoll/recoll.conf`
- `d-i/forky/hooks/target/etc/udisks2/mount_options.conf`
- `d-i/forky/hooks/target/usr/libexec/install-tools/secure-boot-tool.tmpl`
- `d-i/forky/hooks/target/usr/local/bin/labwc-bluetooth.tmpl`
- `d-i/forky/hooks/target/usr/local/bin/labwc-capture.tmpl`
- `d-i/forky/hooks/target/usr/local/bin/labwc-greeter-output`
- `d-i/forky/hooks/target/usr/local/bin/labwc-ocr`
- `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/apt-repo-local/APTRepoLocal/Servicing/ChatGPT.pm`
- `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/apt-repo-local/APTRepoLocal/Servicing/Discord.pm`
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
- `d-i/forky/tests/test_gitbuild_appearance_20260928.py`
- `d-i/forky/tests/test_installer_hardening.py`
- `d-i/forky/tests/test_key_manager_lifecycle_20261014.py`
- `d-i/forky/tests/test_layout_followup_20260923.py`
- `d-i/forky/tests/test_logged_failures_20260927.py`
- `d-i/forky/tests/test_maintenance_20261004.py`
- `d-i/forky/tests/test_process_capture.py`
- `tools/release_audit.py`
- `tools/test-init.py`
- `tools/tests/test_policy_file_classification.py`
- `tools/tests/test_scoped_lifecycle_keyrings.py`
- `tools/validate.py`

