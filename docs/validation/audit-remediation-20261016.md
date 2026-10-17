# Audit remediation: source changes and acceptance boundary

## Scope and evidence

This work addresses F01–F13 and the bounded improvements R01–R13 in
`debian-preseed-de-audit.md`. The findings, component reviews, second-pass
boundary reviews, remediation gates and acceptance matrix were revisited during
integration. The supplied audit remains unchanged.

Baseline commit: `0fc01193e907de5bc087a7633a6a7a2ec19b3ddf`.
The remediation is an uncommitted working-tree change. Exact source/fixture
fingerprint and generated product hashes are recorded below.

**This is not a target acceptance report.** No repository test, native syntax
validator, policy parser, installed management helper or integration check was
executed on the development host. No prepared disposable Forky VM/image was
available. `AGENTS.override.md` and `docs/test-isolation.md` prohibit a host
fallback. The new fixtures are unexecuted, including the real qpdf fixtures and
race-aware process fixtures. Gates A–E remain pending isolated execution.

No software was compiled from source. No development-host service, firewall,
AppArmor policy, network, storage or credential state was changed. No deployment
or device flashing was performed.

## Findings and implementation

All paths below are relative to `d-i/forky/`. `P/` denotes
`hooks/target/usr/local/lib/perl5/site_perl/`.

| Finding | Implementation | Focused fixture files under `tests/` (unexecuted) |
|---|---|---|
| F01 | Correct list-operator error guards in ManagedModes TrustedPath, Workspace, Tool, Transition and LocalChildren. Register staging paths before fallible setup; retain cleanup ownership until rename/removal succeeds. | `test_boot_runtime_20260913.py` |
| F02 | Mode tools always edit with no reload. Stage the selected child include separately, validate the staged parent/child policy, publish both and reload explicitly once. Verify loaded labels inside the transaction. Restore prior bytes/disable-link state on failure; retain a durable recovery directory when loaded rollback cannot be proved. | `test_boot_runtime_20260913.py` |
| F03 | Map recorder exit zero to worker failure when the recording is missing/empty. Preserve the nonempty artifact and intentional-stop branch. | `test_capture_transfer_operands.py` |
| F04 | Keep generator backups on failed restoration/reload. Synchronize backups and parent directories, record restore paths privately, and mark a publication attempted before a possible rename-then-fsync failure. Report the retained bundle and outcome-unknown status. | `test_apparmor_rule_recovery.py` |
| F05 | Retain the original tempfile handle, exact basename, device and inode through verification/publication. Staging validation is separate from the unchanged final basename allowlist. Preserve canonical parent, root/group/mode, size, magic and digest checks. | `test_model_install_root.py` |
| F06 | Derive the validated final model name, acquire the existing model download lock nonblocking and restat under that lock. Skip active/recent partials; prune only validated partials at least 24 hours old. Check the 100-removal cap before unlink. | `test_model_install_root.py` |
| F07 | Route generic Postman/AppImage extraction through the existing locked, dedicated-UID, namespaced `tuta-extract` helper. Account tar entries/bytes before extraction; reject sparse/special/hardlink/unsafe-link members. Traverse incrementally and retain CPU/address-space/file/time bounds, live tree accounting and disk/inode headroom. | `test_security_hardening_20260924.py` |
| F08 | Supply a private user-password file to qpdf output validation. The encryption argument file remains private; password text is absent from argv/logging. | `test_pdf_workflow_outputs.py` |
| F09 | Give fix-qdf a distinct private output pathname and feed that repaired file to qpdf. Preserve qpdf validation and original document immutability. | `test_pdf_workflow_outputs.py` |
| F10 | Return EX_UNAVAILABLE (69) before reboot, USB probing or flashing. The installed nusb interface has no proven binding to the selected ADB/physical identity. Remove the unsafe unbound transition; firmware download/validation and existing confirmations remain. | `test_desktop_release_integrity_20261005.py` |
| F11 | Validate a complete private nft generation before publication; retain prior bytes/metadata and the two owned live tables until success. Restore previous bytes or absence and owned live policy on failure. Preserve/report recovery on failed rollback or ambiguous manager timeout. Reject invalid flag combinations before policy reads/writes. | `test_nft_generation_recovery.py` |
| F12 | Bracket validated IPv6/scoped IPv6 hosts and prefix ambiguous relative local operands with `./`. Preserve quoted arguments, port checks, SFTP and host-key trust defaults. | `test_capture_transfer_operands.py` |
| F13 | Pin candidate processes with pidfds before validating current session/liveness; signal only those descriptors. Keep an unreaped direct-child anchor, reject recycled/unverified identities and close descriptors on success/failure. Bound stream capture, anchor search, rescans and cleanup. Preserve the existing rootless engine/service/socket/storage model. | `test_podman_incus_redesign.py` |

### Recovery and lifecycle details

- Mode recovery lives under `/etc/apparmor.d/.apparmor-mode-recovery.*`, with
  previous parent/child bytes and `restore-paths`. END cleanup does not own a
  retained recovery directory.
- Generated-rule recovery remains under
  `/var/lib/apparmor/generated-rule-backups/generate.*`, mode 0700, with private
  backups and a bounded `restore-paths` record. Failed rollback returns 3.
- Standalone firewall recovery lives under the configured backup directory,
  normally `/var/backups/nftables/.nft-policy-recovery.*`. `previous.json`
  records previous presence/metadata and `live.nft` contains only the owned
  `inet labwc_filter` / `ip labwc_nat` restoration transaction. It never flushes
  another owner's tables. The separate desktop firewall package is unchanged.
- Extraction cleanup uncertainty retains both the worker directory and its
  outer `.vendor-*` workspace. A helper exit 3 or outer timeout is not flattened
  into an ordinary refresh failure followed by recursive workspace deletion.
- `rewrite_data` uses one monotonic deadline for pipe reads and final wait,
  bounds decompressor diagnostics and permits only a two-second cleanup wait.
  Reuse one selector for the stream instead of allocating one per read.
- The refresh unit needs `NoNewPrivileges=false` to enter its explicit AppArmor
  extractor/bwrap profiles. Its other service protections and cgroup lifetime
  remain. The parser then drops UID/GID/capabilities and sets no-new-privileges
  inside its isolated namespace. Native transition acceptance remains required.
- The live extraction watchdog is **not a filesystem quota**. Tar pre-write
  accounting, SquashFS inode preflight, process limits, periodic aggregate
  accounting and byte/inode headroom are complementary bounds. Verify reaction
  time and headroom using the exact target filesystem/tools.
- Container cleanup retains a five-second total escalation budget. Repeated
  cancellation is ignored only during that bounded cleanup/descriptor closure,
  then the original handlers are restored. The service cgroup remains the final
  owner for daemonizing/escaped jobs and uninterruptible work.

### Outcome contracts

| Boundary | Machine result |
|---|---|
| Shared Perl capture | Raw wait status; timeout `124 << 8`; signal in low seven bits. Public adapters decode once. Capture/setup/overflow/interruption errors throw. |
| Model install | Success 0; post-publication uncertainty 3 with final path retained for verification. Pre-publication rejection remains failure. |
| Mode reconciliation | Ordinary failure remains 1; failed rollback returns 3 and reports recovery. |
| Generated rules | Ordinary failure 1 at the entrypoint; usage 2; failed rollback 3; cancellation preserves 129/130/143. |
| Standalone nft generator | Invalid/failed generation 2; unknown policy/recovery result 3; cancellation 130. |
| Extraction | Worker cleanup unknown 3; publisher propagates that uncertainty as 4, distinct from its existing ordinary failure, rejected-inbox and cancellation results. |
| Container root helper | Ordinary failure 1; cleanup unknown 3; normal signal cancellation preserves `128 + signal` after successful cleanup. |
| Samsung automated flash | Unavailable 69; no device mutation is attempted. |

Do not automatically retry an unknown mutation. Inspect the reported recovery
path/current object first. No password, token, full environment or document body
was added to diagnostics.

## Improvement register

| Improvement | Disposition |
|---|---|
| R01 | Add `desktop_verify_runtime_contracts` at the existing staging boundary, before wrapping managed launchers and service enablement. Check rendered source/tokens, actual Python 3.14 and systemd 262, interpreter/module paths, code-root ownership/modes, configured identifiers and relevant repository service contracts. Do not import managed Perl modules or execute their BEGIN blocks. Preserve Perl constants and narrowly identified literal runtime markers. |
| R02 | Document the shared raw wait-status API and add fixtures for AndroidADB, SecurityAction, NetworkControl, NetworkScan, Timeshift, Whisper and Zram adapters. Preserve runner behavior and intentional interactive paths. |
| R03 | Bound changed metadata acquisition, HTTP redirects/retries, package streaming, parser cleanup and root container capture/cleanup. Preserve existing service/cgroup ownership; no blanket runner or unit-lifetime rewrite. |
| R04 | Synchronize durable artifact/recovery files and parents; retain recovery until rollback is proved. Transient desktop UI files are outside this durability change. |
| R05 | Apply streaming tar accounting, incremental output traversal, process limits, preflight headroom and a live watchdog using packaged parsers in the existing sandbox. |
| R06 | Model prune uses exactly the writer's lock; extraction retains its existing global ownership lock. Other reset/storage protocols are preserved. |
| R07 | Bind model staging identity; block Samsung's unbound transport mutation. Existing mapper, namespace and hardware ownership checks remain regression requirements. |
| R08 | Preserve raw capture errors and add explicit unavailable/unknown/recovery results at the affected boundaries, including cancellation at the rule-generation entrypoint. |
| R09 | Enforce the existing vendor HTTP host allowlist before every hop, with curl's own automatic redirect handling disabled. Record trust levels and the different model/generic URL redirect policies below. |
| R10 | Preserve root-private snapshots for privileged imports (`gitbuild.import_local`, repository inbox staging and extractor input copying). The new verifier checks code authority; same-UID desktop state remains a separate boundary. No assertion that same-UID control is a new root exploit. |
| R11 | Prepared current-revision fixtures and evidence identifiers. **Execution is pending a prepared disposable Forky VM/image.** Static inspection/build generation is not substituted for target integration. |
| R12 | Compare private compatibility sources/configuration against baseline and preserve the exact Zoom/Discord eligibility policy. No Xwayland implementation or configuration change. |
| R13 | Repair only the implicated root bootstrap runner with Linux/Python pidfd primitives, validated session anchors and bounded descriptor cleanup. No new supervisor, root API or engine/storage reset. |

## Artifact trust and redirect policy

| Input | Assurance and limits | Redirect policy |
|---|---|---|
| Tuta image | Existing vendor signature is checked with the installed public key; the later SHA-256 snapshot binds the exact already-approved bytes. | `app.tuta.com` must be allowed before each request. |
| Ledger image | Existing pinned-key signature verifies the checksum manifest; artifact SHA-512 must agree with that manifest and release metadata. | Existing download/signature origin allowlists apply before each hop. |
| Postman / ordinary unsigned vendor artifacts | TLS origin, bounded format/layout/version checks and retained content digests establish consistency. A calculated hash does not add an independent vendor signature. | Existing per-vendor allowlists apply before each hop. |
| Discord distributions | Preserve the existing advertised manifest/content digest checks and receipts. These do not imply an independently verified vendor signature. | Existing metadata/CDN allowlists apply before each hop. |
| Catalog models | Fixed catalog repository/revision/file and fixed-origin HTTPS metadata supply LFS SHA-256/size; final magic/size/digest checks bind downloaded bytes. No model signature is asserted. | Metadata does not follow redirects. Binary downloads allow at most five HTTPS-only CDN redirects without caller credentials; there is no model CDN host allowlist. |
| Generic administrator-selected repository URL | Root configuration chooses the origin; HTTPS/content identity checks do not turn it into a vendor-signed artifact. | Existing generic curl path permits eight HTTPS-only redirects and rejects embedded credentials. It does not claim the vendor wrapper's host allowlist boundary. |
| Published local APT repository | Local signing authenticates the local publisher's accepted generation. It does not upgrade unsigned upstream provenance. | Existing publication/discovery policy remains. |

The manual per-hop implementation uses curl's resolved `redirect_url`, without
`--location`, and validates it before another request. Curl documents that
contract in its [official manual](https://curl.se/docs/manpage.html). One
monotonic 1200-second budget covers the vendor redirect/retry sequence plus
the shared runner's bounded cleanup. The metadata capture budget is 16 KiB;
artifact byte limits and final content-policy checks remain per vendor.

## Isolated acceptance plan

Provision and review the VM/image boundary in `docs/test-isolation.md` first.
Use its source-copy/export workflow; never mount host configuration, devices,
HOME or management sockets into a suite. Use the exact regenerated payload and
source/fixture fingerprint from this report. Native commands must come from the
approved Forky image, not installed development-host helpers.

| Boundary / gate | Required isolated execution |
|---|---|
| Installed integration / A | `test_rendered_runtime_contracts.py`, actual rendered target installation, packaged Perl/Python modules and systemd 262. Exercise unresolved tokens, missing delegates, bad identifiers and owner/mode/path drift. Confirm offline service staging never contacts a running host manager. |
| Models / A, C | `test_model_install_root.py`: both families, real File::Temp basenames, final identity/content checks, replacement inode, publication uncertainty and concurrent lock/prune. Also run current catalog/Whisper integration suites. |
| Flash identity / A | Fail-closed fixture must show no device/storage/command delegate in either flash mode. Real automated Samsung flashing remains unavailable until a supported stable selector exists. |
| Perl I/O and AppArmor modes / B | `test_boot_runtime_20260913.py` plus packaged aa-* / parser tests in the VM: enforce/complain/disabled, all three local children, failure injection at I/O boundaries, one-invocation source/loaded convergence and retained rollback evidence. |
| Generated rules / B | `test_apparmor_rule_recovery.py`: parser/reload/rollback failures, exact old include bytes, private backups, restore-path record and status propagation. Verify policy load using the VM kernel. |
| Firewall / B | `test_nft_generation_recovery.py`: rejected candidate, middle write and rename/fsync failure, reload applied before timeout, failed rollback and invalid flags. Then test actual owned-table recovery and preservation of a foreign table with the VM nftables/systemd. |
| Extraction / C | `test_security_hardening_20260924.py`: member/byte flood, sparse/special/link rejection, watchdog, streaming stall and uncertain outer-workspace retention. Verify real bwrap UID/capability/namespace/AppArmor transitions and limits in the VM. |
| Vendor HTTP / C | `test_vendor_http_redirects.py`: approved chain, disallowed intermediate, downgrade, credentials, controls, loop cap and no publication on rejection. No live vendor traffic is needed for these fixtures. |
| PDF / D | `test_pdf_workflow_outputs.py` with actual packaged qpdf/fix-qdf: nonempty passwords via private files; length-changing QDF repair consumed by the next command; no password/body on stdout or argv logs. |
| Capture / D | `test_capture_transfer_operands.py`: missing, empty and nonempty artifacts after recorder zero; valid intentional stop. Follow with actual isolated Wayland recording/service status checks. |
| SSH copy / D | Same fixture suite captures intended DNS/IPv4/IPv6/scoped operands, colon/dash/space local names and no extra destination. Follow with disposable peer transport if needed. |
| Cleanup identity / E | `test_podman_incus_redesign.py`: stale candidate/recycled PID, lost/exited leader, unavailable procfs, closed pidfds, newly observed descendants, anchor deadline and repeated cancellation. Repeat real timeout/cancellation only after those identity fixtures pass. |
| Session/cgroups | Existing session reliability, workflow confinement and compatibility lifecycle suites, then logout/main-exit-with-child/escaped-session/simultaneous-restart in the VM. Assert actual cgroup membership and bounded stop. |
| veth/VPN | `test_kernel_veth_networking.py` and disposable network fixtures: namespace mismatch, disconnect, route churn, no uplink and cleanup failure. Assert closed policy and quarantined slot reuse. |
| Authorization | Existing power/security/network action suites plus active/inactive administrator, ordinary user, greeter and root-service matrices. Malformed/forged arguments must not reach generic commands. |
| Storage | Existing security/Zram fixtures plus VM-owned scratch block devices: mapper/source replacement, busy swapoff and incomplete setup. No operation on a different backing device. |
| TPM/MOK | Existing security/initramfs fixtures plus supported disposable boot hardware/emulation: wrong PIN, no passphrase fallback, interrupted publication, secret exclusion and a separate-boot confirmation. |
| Containers | Existing Podman/Incus suites: sub-ID overlap, socket metadata drift, existing store and ETag conflict; preserve rootless engine and no-reset state. |
| Hardware | Existing hardware tuning/refactor/handover suites and suitable disposable hardware: thermal refusal, paired-write failure and external-change conflict on reset. |
| Logging/queue | Existing native/managed logging and firstboot audit suites: malformed/long records, full disk, absent receiver and interrupted export acknowledgement. Retain bounded sanitized evidence. |
| Private compatibility | Existing `test_compat_lifecycle_ipc.py`, `test_compat_gpu_portal.py` and native session fixtures, then native plus Zoom/Discord private launch/shutdown. Exactly the existing two-app boundary; no global Xwayland. |

Existing suite names are execution entry points, not evidence that every matrix
case has already been implemented or passed. Hardware, boot, GUI, loaded policy
and package-version assertions require their actual isolated target operations.

## Checks performed and snapshot identifiers

- Read source, callers, installer staging, units, policy changes and fixture code
  as data. Rechecked failure/recovery ownership and private compatibility scope.
- Static AST parsing of the changed Python source/fixtures, the embedded tar
  worker and inline target verifier; no repository imports or execution.
- `git diff --check`: clean.
- Reviewed the Makefile/build/publication execution path, then ran only the
  permitted pure serializer:

  ```text
  env -i PATH=/usr/bin:/bin LC_ALL=C.UTF-8 /usr/bin/make --no-print-directory --no-builtin-rules --no-builtin-variables build 'PYTHON=/usr/bin/python3 -I'
  ```

- Read the generated archive/manifest as data and compared every member's bytes
  and SHA-256 against its current source. Checked the archive/manifest pins in
  generated `preseed.cfg`. This proves serialization consistency, not rendering,
  policy validity or installed behavior.

- Static AST data parsing: **18 units**; no repository imports/execution.
- Serializer: **1795 payload files**. Archive/source/manifest equality covered
  **34,419,466 uncompressed bytes**. All generated products are current.
- **45 new fixture methods** were added across 12 changed/new fixture files;
  none was executed. Existing test-method counts are not included in that number.
- **17 private compatibility boundary files** compared byte-for-byte equal to
  baseline, including the eligibility map, private runtime, sandbox/session
  support, AppArmor policy and Xwayland installer.
- Source/fixture fingerprint for **37 changed/new implementation and fixture
  files**, excluding generated products and this report:
  `2b066964ab54cab483636932457f0fe0d20dc13fde961a2ecb4ecbc74e20532e`.
  Compute SHA-256 over sorted records of relative path, NUL, file SHA-256 and LF.

| Generated product | SHA-256 |
|---|---|
| `d-i/forky/payload.tar.gz` | `05e37655735ff72fc7a8d23f6b90196e888dee7471444dd38f7ce4c7a90722fb` |
| `d-i/forky/payload.manifest` | `0015a64c3ee91eb0b6c2436dffa6a8b4c56b7aaa366e26e6b8f966aad7ce11f6` |
| `d-i/forky/preseed.cfg` | `52c59da410e3499832780a99cfd98a71ed4c933b0ad1b60ed6c6e51b34c9b0f1` |

Future acceptance logs must name this source/fixture fingerprint and the actual
VM/image/package identities. A later source edit invalidates these identifiers
until the serializer and data comparisons are repeated.


## Exact changed paths

```text
d-i/forky/hooks/target/etc/apparmor.d/desktop-wrappers.tmpl
d-i/forky/hooks/target/etc/apparmor.d/system-wrappers.tmpl
d-i/forky/hooks/target/etc/systemd/system/apt-repo-local-refresh.service
d-i/forky/hooks/target/usr/local/bin/labwc-capture.tmpl
d-i/forky/hooks/target/usr/local/bin/xssh-retrieve
d-i/forky/hooks/target/usr/local/bin/xssh-send
d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/ModelInstallRoot.pm
d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/apparmor-modes/AppArmor/ManagedModes/CLI.pm
d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/apparmor-modes/AppArmor/ManagedModes/LocalChildren.pm
d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/apparmor-modes/AppArmor/ManagedModes/Tool.pm
d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/apparmor-modes/AppArmor/ManagedModes/Transition.pm
d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/apparmor-modes/AppArmor/ManagedModes/TrustedPath.pm
d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/apparmor-modes/AppArmor/ManagedModes/Workspace.pm
d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/apt-repo-local/APTRepoLocal/Servicing/HTTP.pm
d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/PDF.pm
d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/labwc-adb/AndroidADB/Vendor/Samsung.pm
d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/labwc-security-action/LabwcSecurityAction/AppArmor/RuleGenerator.pm.tmpl
d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/runtime/Managed/Process.pm
d-i/forky/hooks/target/usr/local/libexec/apparmor-generate-rules
d-i/forky/hooks/target/usr/local/libexec/apt-repo-local
d-i/forky/hooks/target/usr/local/libexec/podman-devops-host
d-i/forky/hooks/target/usr/local/libexec/tuta-extract
d-i/forky/hooks/target/usr/local/sbin/nft-policy-generate.py
d-i/forky/payload.manifest
d-i/forky/payload.tar.gz
d-i/forky/preseed.cfg
d-i/forky/scripts/desktop/labwc.sh
d-i/forky/scripts/desktop/verify.sh.tmpl
d-i/forky/tests/test_apparmor_rule_recovery.py
d-i/forky/tests/test_boot_runtime_20260913.py
d-i/forky/tests/test_capture_transfer_operands.py
d-i/forky/tests/test_desktop_release_integrity_20261005.py
d-i/forky/tests/test_model_install_root.py
d-i/forky/tests/test_nft_generation_recovery.py
d-i/forky/tests/test_pdf_workflow_outputs.py
d-i/forky/tests/test_podman_incus_redesign.py
d-i/forky/tests/test_process_capture.py
d-i/forky/tests/test_rendered_runtime_contracts.py
d-i/forky/tests/test_security_hardening_20260924.py
d-i/forky/tests/test_vendor_http_redirects.py
docs/validation/audit-remediation-20261016.md
```
