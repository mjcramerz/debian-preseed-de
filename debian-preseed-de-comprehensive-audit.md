# Debian Forky / systemd 262: Audit and implementation plan

**Audit date:** 17 October 2026  
**Purpose:** Identify what must change, why it matters, how to implement it narrowly, and what evidence is required before release.  
**Change scope:** Report only. The supplied implementation and generated installation products remain unchanged.

## Release decision

**Do not approve this snapshot for unattended fleet deployment yet.** The source contains installation blockers, a coupled EFI preservation defect, unsafe private-key export, an optional package-authentication exception, and recovery paths that can lose the evidence needed to restore a failed operation. The default task-notification configuration also needs a deliberate privacy boundary before activation.

The appropriate response is a sequence of small repairs to the existing design. Preserve its established isolation, explicit authorization, staged publication and fail-closed device handling. A broad rewrite would increase the review burden without resolving the specific defects more reliably.

This report replaces inventories, symbol listings and historical narration with an actionable backlog. It retains the substantive findings and necessary implementation qualifications. Each numbered work package identifies the required result and the acceptance evidence that would justify closing it.

## Evidence and priorities

The audit covered the installer and generated payload, disk and boot configuration, system and transient services, application networking, routing and firewall policy, AppArmor and authorization, desktop integration, vendor packaging, developer tools, document and device utilities, model workflows, logging, maintenance and validation infrastructure. Shell, Perl/Moo/MooX and Python implementations were traced through their relevant delegates and configuration boundaries.

**Evidence is static inspection of the supplied snapshot.** Archive/manifest consistency and selected syntax/data structure checks were performed without importing or executing project code. Source integrity checks found no audit changes. Installer boots, native service operation, kernel policy loading, destructive disk operations, GUI behavior and hardware behavior were **not run**. The repository requires those checks to use an explicitly prepared disposable environment; this report does not substitute host execution for it.

Project-specific observations below come from that source inspection. Primary documentation is cited where a native tool's contract determines a finding. A source-confirmed defect means the incompatible logic is present; it does not mean an actual installation failure, compromise or data loss was observed.

| Priority | Required treatment |
|---|---|
| **P0 — Before deployment** | Correct installation blockers and preservation defects; close the identified key, package-trust, firewall-recovery and notification-default risks. An optional affected feature may remain explicitly unavailable until repaired. |
| **P1 — Before operational acceptance** | Correct lifecycle, rollback, data-preservation and result-reporting defects in enabled features. Exercise the targeted failure paths. |
| **P2 — Before relying on the capability** | Resolve compatibility gates, establish explicit trust/maintenance policies, and complete bounded hardening of the corresponding feature. These are not all demonstrated vulnerabilities. |

## 1. Repair the complete unattended installation path

**Priority: P0. Status: source-confirmed installation blockers.**

Three faults occur across two failure families. One verification helper is defined in a child shell and then called from a different child shell that does not inherit it. Two embedded command strings also cross their quoting boundaries incorrectly: a package-format expression is exposed to the outer shell, and a quoted Python expression loses the literal quotes it needs. The earlier quoting faults can prevent the installation from reaching the missing-helper fault.

### Required implementation

- Define the small verification helper inside the actual shell that invokes it, or invoke an already installed, explicitly validated helper. Do not rely on child-shell definitions being available in a subsequent process.
- Correct the two literal boundaries so the package query receives its intended format and the Python interpreter receives the intended program. Keep substitutions limited to the values that are deliberately rendered.
- Preserve the assertions and nonzero failure propagation. Removing a verification step would hide incomplete installation rather than repair it.
- Validate the fully rendered command at the real shell/process boundary. A parser accepting the outer script does not establish that the embedded program will be delivered unchanged.

**Benefit:** A valid installation can reach the existing completion checks, and invalid deployment remains a hard failure.

**Acceptance:** In the disposable target, run the complete rendered verification route with the unrelated outer-shell value both absent and populated. Verify the exact package-query argument and embedded program, helper availability, rejection of forbidden paths and dangling links, and truthful failure status. These checks occur after target modifications; a failure must not be described as leaving the target untouched. [POSIX shell rules][posix]

## 2. Make partition selection and EFI preservation one coherent contract

**Priority: P0. Status: source-confirmed defects; destructive behavior remains unexecuted.**

The F2FS flow does not persist the selected EFI partition slot into the state consumed by a later installer phase. The later phase can therefore load apparently reusable state while lacking a required partition identity.

A second defect is concealed behind that blocker. An existing EFI System Partition can pass the early FAT/GPT reuse checks, yet a later formatting helper treats a missing preferred volume label as a reason to format it. A valid reused EFI partition does not need the installer's preferred label. Repairing only the missing handoff state can expose the destructive branch.

Fresh encrypted Btrfs and F2FS installs also select a custom partition handler whose registration is limited to the dual-boot route. Earlier disk sanitization may already have occurred before that mismatch causes failure.

### Required implementation

- Persist one complete layout decision before crossing installer phases: selected disk identity, intended partitions, the reused/new distinction and all required partition identifiers. Reject incomplete or inconsistent state before the next mutation.
- Separate **validate a preserved EFI partition** from **format a newly created installer-owned partition**. The preservation route must never use a preferred label as permission to format.
- Register the required handler for every route that selects it. Before disk sanitization, verify that registration and the handler's fresh/reused EFI assumptions match the persisted layout. Separate common registration from dual-boot-specific preparation; calling that entire preparation path from a fresh install is not a safe shortcut.
- Revalidate the selected physical disk and partition identity immediately before destructive operations. Do not treat a reused device pathname as sufficient identity after hotplug or rescanning.
- When reusing an existing encrypted mapping, validate the expected backing identity and encryption metadata instead of accepting its name alone.

**Benefit:** The selected layout remains deterministic across processes, existing boot files are preserved, and encrypted installations execute a handler that actually exists.

**Acceptance:** Treat the missing-state and EFI-formatting repairs as one release unit. Cover fresh/reused layout, Btrfs/F2FS and encrypted/unencrypted combinations. Place recognizable unrelated boot files on a correctly formatted EFI partition with a different label and prove they survive. Reject incomplete state, disk replacement and mismatched existing mappings before further mutation. Confirm native Debian Installer consumption of the handler; static selection/registration evidence alone cannot establish the installer’s exact failure behavior.

## 3. Protect Secure Boot keys and change firmware trust precisely

**Priority: P0 for private-key export; P1 for identity and enrollment corrections.**

The installer can automatically copy an unencrypted private signing key with its backup directory to FAT removable media. FAT permissions do not provide the confidentiality implied by restrictive Unix modes. Exposure requires access to that medium; the audit did not observe an actual export or key disclosure.

Trust maintenance also uses a display-name substring to select a broad enrollment reset. Firmware confirmation is still required, so this is not silent remote trust removal. Nevertheless, unrelated enrolled keys can be affected by a decision based on presentation text. Separately, signer-name or signature-presence checks do not establish that a module or boot artifact was signed by the currently intended key.

### Required implementation

- Export public enrollment material by default. Make private-key backup a separate, deliberate operation using a protected encrypted container and an explicit recovery procedure.
- Identify managed enrollment by the exact owned certificate fingerprint. Delete or replace only that identity, preserving unrelated trust. Do not use a display label as ownership evidence.
- Verify signatures against the intended key and applicable chain before accepting existing artifacts or publishing replacements. Handle key regeneration with the same display name as an identity change.
- Keep signing keys private throughout installer staging and cleanup. Prefer protected credential injection over boot command-line secrets; later file permissions cannot make an earlier exposed transport confidential.
- Describe recovery responsibilities clearly: backup, enrollment, rotation and external trust retirement are different actions. Local key deletion does not revoke copies or remote trust.

**Benefit:** The installation no longer creates an unprotected signing-key backup by default, and trust changes affect only the intended identity.

**Acceptance:** Public-only export, explicitly encrypted private backup, failed/unavailable media, replacement certificates with the same display name, unrelated enrolled keys, unsigned artifacts and signatures from the wrong key. Exercise required physical confirmation in a disposable firmware environment. Preserve the existing hardware/TPM recovery boundary. [Module signing][module-signing] · [MOK administration][mokutil]

## 4. Restore a consistent package and artifact trust policy

**Priority: P0 for the legacy CUDA exception; P1 for floating initial installations.**

The optional legacy CUDA route deliberately allows unauthenticated/weak repository metadata and disables freshness checks for a fixed vendor archive. HTTPS still authenticates transport, and this is not a global APT exception. It nevertheless removes independent repository authentication for packages whose maintainer scripts execute with target root authority.

Several initial vendor installations also follow moving release endpoints without comparing the received artifact with an independently approved digest or vendor signature. A digest recorded after receipt provides a useful receipt, but it does not authenticate the received artifact. The standalone Codex installation route executes its moving installer as the desktop account, not as root; that distinction must remain explicit.

### Required implementation

- Restore normal repository authentication for legacy CUDA using a narrowly scoped, pinned vendor signing identity. If the archived repository cannot satisfy the target verifier, use a maintained authenticated snapshot with reviewed versions/digests, or leave that optional feature unavailable.
- Do not weaken global APT cryptographic policy or silently fall back to unsigned metadata.
- Apply the existing pinned-release pattern to the moving Bitwarden, Postman, Zoom, Filen, Android Platform-Tools and standalone Codex acquisition paths where reproducible installation is promised. Prefer independently verified vendor signatures when available.
- If a moving-release contract is intentional, make it explicit and separate it from the reviewed installer release. Retain the accepted version, digest, source and verification method, with a responsible update owner.
- Preserve stronger existing signature checks. Signing a vendor package into the local repository authenticates the local publisher; it does not replace upstream verification.

**Benefit:** The deployment either installs reviewed bytes under an explicit trust chain or clearly refuses the optional capability. A repeated installation does not silently inherit a changed upstream artifact while claiming reproducibility.

**Acceptance:** Wrong signing key, unsigned or expired metadata, downgrade, modified package, changed bytes at an unchanged URL, version/architecture mismatch, unavailable approved release, and cleanup after a rejected download. Verify that the exception cannot escape its selected feature. No supplied package is alleged to be malicious. [APT authentication][apt-secure]

## 5. Make firewall updates recoverable and exposure checks semantic

**Priority: P0 for lost recovery state; P1 for exposure-policy validation.**

The desktop firewall transaction can restore configuration bytes, clear rollback bookkeeping, then fail to restore the live ruleset. Its final cleanup can delete the remaining backups despite that unresolved live state. A timed-out manager operation can also still complete later. An error return therefore does not prove that the old firewall is active.

A separate public-exposure guard recognizes sensitive network names rather than the resolved address scope. An alias can reach an equally broad public range without triggering the intended acknowledgement. This weakens an administrative safety interlock; it is not an unprivileged firewall-editing exploit.

### Required implementation

- Keep one transaction owner across snapshot, candidate validation, file publication, live application, verification and rollback.
- Retain previous bytes, metadata, absence state and required live-policy evidence until restoration is positively verified. Synchronize durable recovery records and relevant parent directories before discarding them.
- Distinguish successful rollback, failed rollback and **outcome unknown**. A manager timeout must not immediately trigger a conflicting retry or discard its recovery material.
- Preserve unrelated firewall tables and administrator state. The desktop transaction and the standalone ruleset transaction have distinct ownership boundaries; do not merge their cleanup indiscriminately.
- Evaluate public exposure from the resolved IPv4/IPv6 ranges, including unrestricted ranges, regardless of aliases or display names. Require the same acknowledgement for equivalent exposure.

**Benefit:** A failed edit retains a deterministic route back to the last verified state, and an alternate name cannot bypass the intended public-exposure decision.

**Acceptance:** Failure before/after publication, failed live reload, late manager completion, failed restoration, disk synchronization failure, and interruption while recovery is pending. Verify original bytes/absence, owned live tables and untouched unrelated rules. Equivalent aliases must produce identical exposure decisions. Keep recovery state when the actual live outcome cannot be established.

## 6. Make external task notifications deliberate and disabling effective

**Priority: P0 for the default disclosure boundary; P1 for queued-message behavior. These repairs must ship together where pending queues already exist, or delivery must remain stopped until reconciliation.**

Plans enables external ntfy delivery to a fixed hosted destination without establishing a protected reader policy. The message includes task content and associated scheduling/source information. If publication is accepted on an unreserved readable topic, others can receive it. If the topic is protected or rejects publication, delivery may fail instead. The audit did not contact that destination or establish its current reservation/access controls.

The current enable/disable decision also does not govern every later dispatch of persisted pending messages. Disabling a channel can therefore leave old queued work eligible for transmission.

### Required implementation

- Default ntfy task publication to disabled until the operator deliberately enables an authorized destination.
- Require suitable publisher authentication and verified reader restrictions. A random or obscure topic name alone is not access control. Keep credentials in the existing private credential mechanism.
- Evaluate the current channel policy immediately before every send, including retry and restart recovery.
- Reconcile pending work under the existing queue lock. Define whether disabling pauses or cancels queued messages, and require a deliberate decision before sending a previously paused backlog.
- Keep independently configured channels independent. Correcting ntfy must not silently alter an explicitly authorized Telegram destination.

**Benefit:** Task content follows the operator's current sharing decision, including work that was queued before that decision changed.

**Acceptance:** With fake tasks and fixture endpoints, untouched ntfy defaults make no ntfy request; disabled channels never send old queued messages; authenticated publication reaches only authorized readers; acknowledged work is not resent; and enable/disable races have deterministic outcomes. These are runtime concerns for existing or corrected installations, not proof that a fresh install blocked earlier already disclosed data. [ntfy access control][ntfy]

## 7. Finish the process-lifecycle contract across all affected runners

**Priority: P1. Status: source-confirmed inconsistencies; actual stuck processes and identity reuse were not reproduced.**

Several runners bound ordinary command execution but then wait indefinitely during final reaping. Other paths signal a numeric process group after its leader has already been reaped, discard control state after uncertain cleanup, or lose the distinction between an ordinary failure and an unknown outcome while crossing a language bridge. The diagnostic recovery path can start a replacement boot-image operation without proving the first writer has stopped.

The affected contracts span managed desktop jobs, archive operations, ADB, hardware control, Whisper, Git/Obsidian operations, Codex teardown, installer SSH cleanup, vendor servicing and validation runners. One shared correction strategy is appropriate; a new general execution framework is not required.

### Required implementation

- Use a monotonic operation deadline covering streaming, retries and command completion, followed by a separate finite cleanup/reap budget. Do not remove the bound with a final blocking wait.
- Retain identity through every permitted signal. For process-group cleanup, keep the group leader unreaped until signaling is complete. Use verified pidfds for process-specific signaling where supported. A stored numeric PID, an existence check or a fallback after identity loss is insufficient.
- Keep daemonizing or session-escaping jobs in their existing owning systemd cgroup. A process group alone does not prove ownership of those descendants.
- After TERM, account for surviving descendants even if the leader exits. Escalate only within the verified ownership boundary and finish reaping within the cleanup budget.
- Propagate cancellation, ordinary failure, unavailable and unknown outcome distinctly through Perl/Python/shell adapters and the UI. Preserve the existing Perl raw wait-status contract until the public adapter decodes it exactly once.
- On uncertain termination, retain workspaces, control state and recovery receipts necessary for safe reconciliation. Keep conflicting work excluded until reconciliation. Do not launch a competing writer, reset device state, delete active staging or claim rollback complete.
- Preserve intentional interactive operations. A user entering credentials or making a selection should not inherit a short timeout intended for an automated probe.

**Benefit:** The caller returns a truthful bounded result, cannot signal a reused identity, and does not destroy the state needed to resolve late completion. A deadline cannot force uninterruptible kernel work to exit; the implementation must represent that uncertainty.

**Acceptance:** Controlled fixtures for ignored TERM, surviving descendants, retained pipes, late manager completion, interrupted cleanup, lost child identity and cancellation during escalation. Verify no numeric fallback, no unbounded final wait, no removal of in-use recovery state, and no second boot-image writer after an uncertain first writer. Recheck direct command entry points as well as service invocation. [systemd process control][systemd-kill] · [Python subprocess behavior][subprocess]

## 8. Enforce resource limits before allocation and extraction

**Priority: P1. Status: source-confirmed placement defects and closely related hardening gaps.**

Some Git, provider API, publication and diagnostic helpers collect complete output before checking its size. Some directory scans allocate full listings before enforcing entry limits. Selected Android and desktop tool installers validate total expanded size only after extraction. These checks can reject oversized input after memory, disk or inode resources have already been consumed.

Pinned trusted archives reduce the hostile-input exposure, but they do not make a post-extraction quota a real extraction bound. Conversely, this finding does not establish arbitrary writes or a native archive-parser exploit.

### Required implementation

- Apply byte limits while draining both standard output and standard error, with bounded sanitized diagnostics. Stop the owned operation on overflow under the lifecycle contract in section 7.
- Bound directory entries, recursion depth, records and aggregate bytes during enumeration, before building a complete list or schedule. Include provider output, Git status/tree data, publication descriptors, model/state directories and notification expansion.
- Validate archive paths, member types, duplicate names, counts and declared sizes before extraction; enforce actual per-member and aggregate bytes during copying. Bound ignored members and headers where a selective extractor otherwise traverses unlimited input.
- Reuse the existing descriptor-bound extraction and private staging mechanisms. Reject unsupported special nodes and links rather than introducing a permissive generic extractor.
- Account for aggregate concurrent disk demand, including several model downloads or builds. Free-space polling is a useful guard but is not equivalent to an enforced filesystem quota.

**Benefit:** Advertised limits constrain resource consumption when it occurs, making large or malformed input a controlled refusal instead of a host-availability incident.

**Acceptance:** Oversized simultaneous output streams, a child retaining a pipe, huge directory/member counts, declared versus actual expansion mismatch, unsafe members, many ignored headers, low disk space and cancellation on overflow. Preserve bounded diagnostics and retain staging if cleanup remains uncertain. Existing properly bounded extractors should remain unchanged.

## 9. Serialize policy changes and recover complete multi-file state

**Priority: P1. Status: source-confirmed policy and publication defects.**

Three separate transaction gaps need narrow repairs.

**AppArmor concurrency:** Desktop policy changes use a transaction lock, but independent managed mode/service/package entry points do not all participate. Two legitimate writers can validate different candidates and restore snapshots over each other's changes.

**Vendor policy staging:** The ChatGPT integration can overwrite policy or alter a diversion before the managed transaction has captured the real previous state. A later validation failure can therefore lose the old on-disk configuration. This does not prove that the previously loaded kernel profile immediately disappears.

**Key bundles:** A destination can be renamed into place before the following directory synchronization fails. The caller records the destination only after the write returns, so rollback can omit a file that was already committed.

### Required implementation

- Use the existing policy ownership protocol for every managed writer from snapshot through loaded-state verification and recovery. Handle nested calls by an explicit verified lock handoff or one top-level owner; blindly taking the same lock again in a child can deadlock.
- During Debian Installer execution, preserve target staging and validation without loading target AppArmor policy into the installer's kernel. Loaded-state verification and restoration apply to the booted target.
- Prepare and validate the complete policy candidate before changing live bytes or diversions. Snapshot the true previous state, including absence, ownership, modes and managed diversion state, before the first mutation.
- For key bundles and comparable multi-file publications, record an attempted destination before an operation that can commit and then raise. Retain expected content identity and prior absence so exception recovery can reconcile each attempted publication.
- Remove an attempted output only if it is still the transaction's own content. Never delete an unrelated replacement merely because its pathname appears in the attempt log.
- Keep recovery material until disk state and required loaded state are verified. Synchronize durable files and parent directories at commit/recovery boundaries.

**Benefit:** Existing careful transactions remain correct under concurrent legitimate entry points and failures after partial commit, without broad policy expansion or a new transaction subsystem.

**Acceptance:** Concurrent mode reload/rule generation/draft activation; failure before/after policy publication; diversion changes; failure between key-bundle members; and directory-sync failure after rename. Verify exact restoration or retained recoverable state. Manual root policy loading remains an external administrative boundary, not something this cooperative lock can automatically serialize.

## 10. Make package integration converge after failure and removal

**Priority: P1. Status: source-confirmed servicing defects and required recovery improvements.**

The live Discord bootstrap/repair route can disregard its valid previous-generation receipt when the current installation is absent or invalid, precisely when recovery needs that receipt. Ordinary Python repository-generation updates take a different staging route; they must not be described as exhibiting this same live-repair defect.

The optional D-Bus package integration can also leave a managed local diversion after package removal, with no distribution counterpart to restore. A later refresh treats that optional absence as fatal. A package-manager post-hook failure may be reported after package changes have already happened.

Related source-normalization and repository-maintenance flows need to converge even when the package bytes themselves are unchanged.

### Required implementation

- Recover the live vendor installation from its recorded, validated prior receipt independently of whether the current live generation validates. Preserve an uncertain recovery outcome instead of deleting the backup.
- Distinguish mandatory assets, legitimately absent optional packages and foreign/inconsistent diversion state. Remove only owned optional aliases/diversions when absence is authoritative; make removal/reinstallation converge. Do not accept arbitrary missing files as normal.
- Require D-Bus and unit-candidate validation to succeed before activation; a failed parser is not an empty configuration. Use a verified private updater lock location and validate the opened lock inode instead of assuming its parent directory establishes safe ownership.
- Reconcile managed repository/source configuration even when a release comparison finds no new package. A previous failure after package commit must remain repairable on the next run.
- Stage and validate a complete intended source set before replacing or deleting its managed members. Restore that owned set on failure while preserving unrelated administrator entries.
- Preserve previous repository generations for active readers and rollback. Coordinate pruning with the existing writer lock; do not add a competing cleanup lock.
- For signing-key rotation, establish an explicit overlap/transition sequence so trust is available before clients need the new signature and remains sufficient for retained generations.

**Benefit:** Repeated servicing repairs interrupted managed state rather than treating the presence of current package bytes as proof that all integration succeeded.

**Acceptance:** Missing live Discord generation with a valid recovery receipt, corrupted live content, interrupted repair, optional D-Bus removal/reinstall, missing mandatory integration, foreign diversion, unchanged package with broken source configuration, source-set failure halfway through commit, and readers using an older retained generation. Verify the exact native package-manager behavior in the disposable target.

## 11. Enforce the download boundary before making each request

**Priority: P1. Status: source-confirmed destination-policy defects and a bootstrap trust requirement.**

The installer and a vendor download route check redirect destinations after following them. Rejection at that point cannot undo contact with a disallowed host. A final approved destination also cannot prove that every intermediate destination was approved. The installer route needs scheme enforcement as well; the HTTPS-only vendor route retains its separate transport and package-signature protections.

### Required implementation

- Validate each next destination before contact: permitted scheme and authority, no embedded credentials, bounded redirects, and the exact allowed vendor/CDN scope.
- Apply one operation deadline across transfers, redirects and retries, plus an appropriate byte ceiling. A new timeout for each hop or socket operation is not a complete delivery deadline.
- For uploads promising a reproducible copy of the selected file, use a private stable snapshot rather than silently accepting content that changes during streaming.
- Preserve independent artifact hashes/signatures and private staging. Destination checks and content authentication solve different problems.
- Authenticate the initial installer/preseed distribution through the deployment's boot trust mechanism. Hashes supplied inside a replaceable preseed do not authenticate that preseed.
- Publish complete immutable installation generations. Switch the advertised generation only after preseed, manifest and payload agree. Exclude editor backups, old generated evidence and private input history from the served product; no actual published secret was established by this audit.

**Benefit:** Network policy constrains requests before they occur, and installation integrity begins at the initial trust source rather than assuming its own supplied hashes prove authenticity.

**Acceptance:** An isolated redirect fixture must show that forbidden destinations receive no request, including an approved–forbidden–approved chain. Cover downgrade, loops, malformed locations, approved redirects, slow progress and retry exhaustion. Reject mismatched installation generations. For notification/upload helpers, distinguish connection loss after submission from confirmed non-delivery; do not automatically duplicate an uncertain delivery.

## 12. Make boot and package-maintenance completion truthful

**Priority: P1. Status: source-confirmed failure-propagation and retry defects.**

Three kernel-signing hooks capture the status of a negated shell condition instead of the failed signing command, turning failure into success. Explicit installation deferral is intended, but the failure is also hidden when that deferral is disabled.

Secondboot cleanup deletes temporary hooks before rebuilding the initramfs. If the rebuild fails, the next invocation can see nothing left to delete, skip rebuilding and report completion. Cleanup can be marked complete without proving that the boot image was rebuilt without the temporary hooks.

An optional memory-backed APT-list refresh has a missing command continuation. It can report successful service completion without running the intended index update.

### Required implementation

- Preserve and propagate the actual signing result. Permit success-with-warning only under the existing explicit deferral policy, and make that deferred state visible.
- Record durable pending boot-image work before deleting its source hooks. Clear the pending state and retire temporary provisioning policy only after the resulting image has been rebuilt and verified.
- Stage and verify newly signed boot artifacts before replacing the previous valid artifact. Preserve recovery across interruption rather than relying only on an ordinary exception handler around in-place writes.
- Correct the APT refresh command boundary and verify the actual argument sequence and nonzero error propagation.
- Never start boot-image recovery while the previous writer has an unknown outcome; apply section 7 first to that failure path.

**Benefit:** Package and boot-maintenance success describes a completed operation, and retry finishes interrupted work instead of inferring completion from deleted inputs.

**Acceptance:** Signing failure with deferral both enabled and disabled; interruption after hook deletion and after image generation; failed verification; full disk; and a failed refresh with the optional mount enabled. Reboot the disposable target through the repaired path, including the chosen encryption/TPM configuration. Later timers repairing state do not retroactively make a false-success helper correct.

## 13. Preserve application save time and serialize terminal power actions

**Priority: P1. Status: source-confirmed lifecycle and launch-policy inconsistencies.**

For some native applications, the first stop signal terminates their supervisor and Bubblewrap's parent-death behavior kills the payload before the advertised save interval can elapse. Separately, the power frontend releases its lock after service startup acknowledgement. Different shutdown/reboot requests, including requests by different authorized users, can then overlap cleanup and handoff.

Some compositor menu entries also launch application binaries directly instead of using their intended managed route. AppArmor may still apply; the bypass concerns the additional transient-service, mount and network behavior, not a demonstrated absence of all confinement.

### Required implementation

- Extend the existing graceful native supervision behavior to the affected applications. Retain a supervisor until the save opportunity has elapsed, with the owning cgroup and final escalation intact. Removing parent-death behavior without establishing replacement ownership is insufficient.
- Reserve one root-owned terminal power operation across shutdown/reboot and all callers, retaining ownership through accepted handoff until manager teardown. A successful handoff-client return must not admit a competing action. Give subsequent requests an explicit already-pending result.
- Keep that reservation independent of package/sleep preparation locks, preserving the ability to request shutdown during those operations.
- Preserve the current deliberate save/cleanup intervals and authorized single-force behavior. Do not shorten them to make the transaction easier to serialize.
- Route the affected native menu entries through their existing managed launchers. Preserve the distinct authorization path for administrative helpers.

**Benefit:** Applications receive their promised opportunity to save, one operation owns final drive cleanup, and application policy is consistent across menus, shortcuts and desktop entries.

**Acceptance:** Delayed application flush, ignored termination, failed supervisor startup, two users requesting different power actions, duplicate requests during saving, and cleanup failure. Compare the effective cgroup, namespace and AppArmor attachment for each affected launch route. Preserve the exact existing private Xwayland implementation and its eligibility for **Zoom and Discord only**.

## 14. Preserve source data and validate outputs before reporting success

**Priority: P1. Status: source-confirmed defects and a format-capability limitation.**

| Affected operation | What must change | Required acceptance |
|---|---|---|
| Desktop recording | A requested stop plus a nonempty file must not hide an independent recorder error. Accept only documented handled-stop outcomes and a valid finalized media container. | Normal stop, simultaneous write failure, empty/header-only/truncated output, cancellation and retained partial data. |
| Android recording transfer | Delete the device recording only after successful transfer and local validation. On failed/empty transfer, preserve the device copy and report its managed recovery location. | Failed pull with a still-reachable device, full local disk, interrupted transfer, invalid output and failed remote cleanup after a successful copy. |
| Metadata editing/removal | ExifTool output mode rejects an already existing destination. Use an absent name in the private operation directory, or edit a deliberately created private copy without that output mode; validate, then publish without overwriting. | Supported image/PDF formats, existing output collision, tool failure, cancellation and original preservation. |
| DOCX metadata mutation | Stop offering unsupported edit/remove operations through a backend that lists DOCX as read-only. Keep reading available. Implement a bounded OOXML editor only if the feature actually warrants it. | Unsupported action is clearly unavailable; any later implementation preserves unrelated document parts and opens correctly in the intended office tools. |
| PDF privacy removal | ExifTool's incremental changes can leave earlier metadata recoverable. Describe the result as visible-metadata editing, or use a verified format-aware rewrite when privacy sanitization is promised. | Check recoverability of old metadata, preserve valid document content and distinguish metadata from page text, attachments and other sensitive content. |
| OCR/conversion output | Define an explicit no-overwrite or selected-overwrite policy; repeated input basenames must not silently replace previous output. Preserve valid empty OCR results where the operation supports them. | Duplicate basenames, expected output type, invalid tool output and legitimate empty recognition. |

Do not fix the ExifTool output conflict by combining its output option with original-overwrite behavior; that combination can remove the source. Reuse the existing private workspace, password handling and no-replace publication patterns. A zero process exit is only one part of a usable output contract. [ExifTool output and PDF behavior][exiftool] · [Supported formats][exiftool-formats]

**Benefit:** Transfer or conversion failure does not destroy the only complete input, and the UI describes a result the selected backend can actually deliver.

## 15. Trust security-event origin and own the maintenance policy

**Priority: P1 for event routing; P2 for explicit operational coverage.**

The authentication log route admits a sender-selected facility before the ordinary trusted-origin routing. A local sender can therefore submit authentication-looking messages to a protected destination without being an authentication producer. A protected log file does not authenticate the records written into it. Whether a forged record causes an actual security-engine decision or ban depends on the installed parser and remediation chain and remains untested.

### Required implementation

- Admit remediation inputs using trusted producer identity or a protected authoritative source. Do not rely on the facility, tag or formatted message alone. Preserve legitimate privilege-separated authentication producers rather than assuming all authentic messages must have root UID.
- Keep rejected same-facility messages as identifiable application diagnostics without promoting them into authoritative authentication events.
- Reconsider automatic blocking based only on dropped initial TCP probes: those packets do not establish that the apparent source is reachable. Use alert-only handling or independent evidence establishing source reachability or an appropriately authenticated origin, then test the actual decision chain. Additional dropped packets alone are not such evidence.
- Document the enabled CrowdSec community API participation and monitor local detection outages. Separate remote backoff from local engine recovery where the packaged implementation supports it; a lengthy retry delay also affects unrelated engine failures.
- Assign an owner and cadence for manual security updates. The deliberate unattended-upgrade exclusions include major security-sensitive components, so automatic updates are partial coverage. Preserve the intended controlled boot/driver update workflow rather than removing its exclusions indiscriminately.
- Describe audit rules as selected observability. Validate the intended syscall/ABI coverage, including relevant alternative mutation operations, without adding an indiscriminate high-volume rule set.
- Verify rotation/reopen behavior, protected sink ownership, final journal configuration and failure propagation. Keep sealing-key export/verification separate from local sealing; local configuration alone does not prove an independent verifier has retained the necessary material.
- Bound automated early-boot diagnostic collection by time as well as bytes. Treat diagnostic redaction as best effort and require review before sharing; identifiers or embedded data can remain.

Keep network-scan classifications at their observed/review level: an exposed port or present security header is not proof of a vulnerability or an effective security policy. Align directly exposed port-input validation with the authoritative network policy.

**Benefit:** Automated security decisions are based on attributable events, and the maintenance/observability claims match what the system actually does.

**Acceptance:** Forged facility/tag input alongside genuine SSH, PAM, sudo and login events; privilege separation; collector restart; parser/bouncer decisions; rotation under load; crash-retention expectations; and update selection for both automated and deliberately deferred packages. Reject ambiguous native configuration rewrites rather than silently dropping unrelated administrator actions.

## 16. Correct zram admission and preserve storage/device identity

**Priority: P1 for incomplete-snapshot admission and cleanup boundaries; P2 for hardware acceptance.**

Automatic targeted zram writeback can consume candidates from a truncated scan before checking that the snapshot is authoritative. That contradicts the stated suppression behavior. The operation is bounded, and no memory corruption was demonstrated; the defect is admitting work from incomplete evidence.

Installer cleanup also selects a shallow set of directory entries and then removes them recursively. That does not prevent crossing a mounted descendant. A same-filesystem bind mount is not excluded by a filesystem-device check alone.

### Required implementation

- Require complete, fresh and authoritative telemetry before admitting automatic targeted writeback. Preserve explicitly supplied manual indexes as a separate documented operation. Keep missing pressure data unknown rather than converting it to healthy zero pressure.
- Distinguish a periodic maintenance skip from an unperformed lifecycle action. Start/reset must finish, wait within its budget or report busy; it must not inherit a successful skip result while doing nothing.
- Validate the intended zram and encrypted backing-device identity, mounts and holders before mutation. State clearly whether the writeback budget is per boot or durable across reboots; a runtime-only counter does not enforce a long-term endurance budget.
- Before recursive cleanup, reject symlinked or noncanonical roots, verify the intended target and mount namespace, and reject both active root mountpoints and mounted descendants, including same-filesystem bind mounts. Do not skip a mounted descendant and declare its underlying directory clean.
- Bind external-drive and hardware changes/restoration to the same physical device lifetime, rechecking identity immediately before action. Use a supported generation identity where available; a reused device number alone is insufficient after hotplug.
- Preserve system-storage, active-swap and layered-device exclusions. Verify synchronization and unmount before power-off; retain accurate failure/recovery state instead of forcing through busy writers.
- Respect competing hardware controllers and later ownership. Restoration must not overwrite settings another authorized controller has since taken over. Apply the existing manual/lease/power-source precedence deliberately.

**Benefit:** Automatic tuning uses valid evidence, cleanup cannot silently cross its intended storage boundary, and a device selected earlier is not confused with a replacement.

**Acceptance:** Truncated/empty/unavailable zram scans, valid manual indexes, lock contention, mismatched backing identities, nested bind/submounts, hotplug during cleanup, active holders, failed restoration, suspend/resume and competing controllers. Performance/thermal settings need acceptance on the actual supported machine; the audit provides no thermal benchmark. IOCost calibration also needs an explicit stale-lock and device/model-identity recovery policy before unattended recalibration is relied upon.

## 17. Verify the effective network, container and access boundaries

**Priority: P2. Status: important design contracts and native compatibility gates, not blanket findings of broken isolation.**

| Boundary | Required decision or verification | Benefit |
|---|---|---|
| Application veth broker | Preserve peer-credential authorization, pinned namespace descriptors and owned lease cleanup. Describe the application selector as policy available to an authorized account, not cryptographic proof of the requesting executable. Test wrong users, namespace replacement and restart recovery. | The stated authority matches the interface actually exposed. |
| IPv4/IPv6, DNS and VPN transitions | Verify initial allocation, uplink/VPN changes, DNS bootstrap, lease loss and cleanup. Test fresh guest DHCP acquisition, not only renewal, and the required IPv6 control traffic. Host output policy currently does not establish a host-wide prohibition on ordinary DNS. | Connectivity and leak-prevention claims follow effective policy rather than intended topology. |
| Firewall group composition | Resolve aliases and overlays consistently. Reject unsupported multi-group forwarding combinations instead of silently using only the first group; retain intentional intersection semantics. | Accepted configuration has a defined effect. |
| Shared rootless Podman | Preserve the explicit shared engine account/group authority, existing-store no-reset rules and container survival across API restarts. Its API service has intentionally different lifetime behavior from an isolated one-shot job. | Lifecycle hardening does not destroy the intended shared container service. |
| Incus | Keep the privileged daemon distinct from its restricted user interface and administrator access. Verify the primary user's intended lack of administrative membership. | Root-equivalent container administration is not misrepresented as ordinary rootless access. |
| Kernel settings | Inspect final effective forwarding and user-namespace values after all fragments and services. Later enabling settings are intentional requirements in some profiles; earlier restrictive text is not the final policy. | Security documentation matches the active system. |
| NFS | Keep the trusted-client/LAN assumption explicit. Network restriction, UID mapping and root squashing do not provide cryptographic client identity or confidentiality. Verify the mount before reporting UI success. | Users know the actual trust boundary and receive truthful results. |
| Login, sudo and polkit | Verify the rendered rules with exact target packages, active/local-session distinctions, special helper arguments and positive/negative authorization cases. Validate SSH configuration before enabling it. | Package integration cannot silently weaken or block intended authorization. |

These gates must use the installed policy and packages. Do not broaden AppArmor or expose a privileged socket simply to make an acceptance check pass.

## 18. Make developer publication and credential delivery verifiable

**Priority: P1 for false publication assurance; P2 for endpoint, ancestry and credential-delivery gates.**

The Aptly wrapper checks that a public release object exists and then reports that the new snapshot is published. An old cached object can satisfy that presence check. Cloud publication and public propagation are separate outcomes.

The OBS wrapper validates project/package metadata but not the working copy's stored API origin. Current upstream code uses that stored origin; the exact pinned target version was not exercised, so misdirected publication or credential disclosure is not established.

Private publisher state also sits beneath deliberately shared writable ancestry. A private leaf prevents traversal but does not stop another authorized group member replacing that leaf through its parent. Whether that is unacceptable depends on whether group members are mutually trusted.

### Required implementation

- Verify the expected new signed release identity or digest with a bounded read. Keep publication committed, propagation pending and outcome unknown distinct; retain the exact snapshot/operation identity for reconciliation.
- Serialize the complete managed publication workflow, not just individual native commands. After a remote timeout, inspect the expected operation before retrying; do not assume exactly-once remote execution.
- Require a bounded direct OBS destination record to match the normalized configured HTTPS origin, and preserve/recheck that metadata identity across mutation. Retain project/package checks and reject ambiguous or option-like identifiers.
- Decide the shared-group trust model. If publisher credentials must be isolated from other group members, place the publication-specific state under non-replaceable private ancestry and keep the validated configuration bound to the native consumer. Changing only the leaf permissions is insufficient.
- Serialize multi-secret import/rotation and remove only the validated pending generation. Reject blocking special files before consuming input, and preserve source identity across read/use boundaries.
- Give Codex credential delivery an execution-side contract: read bounded, allowlisted credential data in the trusted wrapper, without shell sourcing or manager-global secret exposure. The current prestart may affect credential availability; this audit does **not** establish that every cold start fails.

**Benefit:** Publication success proves the expected content, checkout metadata cannot silently redirect the managed workflow, and credentials follow an explicit ownership/delivery boundary.

**Acceptance:** Old cached release after a successful switch; delayed propagation; remote timeout after commit; mismatched OBS origin under the exact pinned version; concurrent publication/rotation; two-account parent replacement where isolation is required; and Codex cold start/restart with dummy credentials and no inherited fallback. Verify delivery without exposing the dummy value in logs or process arguments. [systemd credential execution][systemd-exec] · [OBS package implementation][osc]

## 19. Own dependency closure, private runtimes and recovery scope

**Priority: P2. Status: reproducibility, maintenance and recovery requirements.**

The project has substantial pinning and staging controls. Remaining differences should be made explicit rather than flattened into a claim that all downloaded software is untrusted or all pinned software is reproducible.

### Required implementation

- Retain an approved dependency closure for npm/pipx-style installations where only the top-level release is pinned. Record exact dependency versions and integrities, or use an approved wheel/package set. Define source-build and lifecycle-script policy explicitly.
- Stage dependency installation under the existing restricted non-root builder before the small privileged publication step. Do not infer current npm script behavior from older defaults; test the selected tool version and required native packages.
- Record target package versions, build-image identity, selected source commit and accepted upstream artifacts. A mutable branch checkout is not made immutable by a pinned executable elsewhere in the installation.
- Assign update ownership to private application runtimes and libraries outside APT, including the private graphics/runtime compatibility components. Where self-update is intentionally disabled, the project must supply the authenticated repinning cadence.
- Revalidate intentionally removed vendor dependencies and maintainer integration against each accepted package generation. A successful local repack does not prove those removals remain compatible with a later vendor release.
- For supported in-place upgrades, preserve a verified previous generation until replacement and selection are complete and durable. Do not treat fresh-install delete-and-replace logic as a proven upgrade transaction.
- Keep root-executed native probes within the approved installation boundary; move only appropriate probes to the existing restricted build account. A temporary home directory alone does not isolate a privileged executable from the target.
- Give root snapshots an accurate recovery scope. Separate data, home, application state, encryption material and current boot artifacts require a coordinated plan; a Timeshift root snapshot is not a complete host backup.
- Make any forced package purge an explicit repair escalation with defined configuration recovery. Do not present it as a harmless generic retry.

**Benefit:** Reproducibility, security patch coverage and recovery have identifiable owners and verifiable inputs instead of depending on moving upstream state or undocumented assumptions.

**Acceptance:** Reinstall the same reviewed release with the retained closure, reject changed dependencies, recover an interrupted supported upgrade, and restore a snapshot with matching boot/kernel/module state. Confirm interpreter and Perl/Python module availability on Forky; host syntax acceptance cannot prove target imports or native functionality.

## 20. Correct desktop capability and result reporting

**Priority: P1 for a potentially blocked greeter; P2 for smaller defects and compatibility gates.**

| Issue | Narrow implementation | Acceptance |
|---|---|---|
| Greeter output query can block before login appears | Bound automated output discovery/configuration and its cleanup, with a deterministic visible or restartable failure path. Keep interactive credential entry outside that short probe deadline. | Hung query, failed configuration, hotplug and a usable login path. Render matching terminal settings if non-default terminals are supported. |
| Renderer checks reject harmless operands | Match actual options and relevant option values, preserving argument separators, URLs and filenames containing similar words. | Real prohibited switches rejected; ordinary operands preserved. |
| Shortcuts force NVIDIA on non-NVIDIA profiles | Render affected shortcuts through the existing validated renderer selection. | Supported Intel/plain and explicit NVIDIA launch paths. |
| Bluetooth pairing overstates success | Report pairing, trust and connection as separate outcomes. Optional initialization must not equate processed controllers with successfully powered controllers. | Independent follow-up failures produce accurate status. |
| Portal capability is assumed | Verify the exact installed screenshot/screencast/remote-control interfaces. Select a compatible backend only if remote control is required; the wlroots portal's advertised capabilities alone do not establish it. | Required portal methods, consent and application behavior on the target. |
| Browser developer-tools route is unproven | Check page loading, mandatory proxy routing and loopback debugging together. If incompatible, compose the existing managed route without weakening proxy enforcement. | Actual debugging-profile connectivity; no general unproxied fallback. |
| qBittorrent receives the raw session bus | Inspect installed AppArmor abstractions and required methods before considering a narrow bus proxy. Preserve intentional peer-network behavior. | Required methods work; unrelated methods are denied where that is the intended policy. No bus escape or anonymity guarantee is asserted. |
| Appearance changes need native acceptance | Validate the complete rendered labwc/Waybar/Crystal Dock/theme candidate before publication; retain coherent recovery and report restart failures separately from saved settings. | First login/relogin, display changes, theme rollback and application restart failure. |
| Minor policy/documentation mismatch | Align the intended NTFS driver preference with actual native priority ordering, and label firewall preview/application instructions accurately. | Effective mount driver/options and documented transactional apply behavior agree. |

**Benefit:** The desktop offers supported capabilities, preserves login availability and reports what actually succeeded. Keep required Wayland behavior and the existing two-application private Xwayland boundary unchanged. [wlroots portal capabilities][wlr-portal] · [UDisks mount policy][udisks]

## 21. Preserve user workflow state and make privacy claims accurate

**Priority: P2, with the shared P1 lifecycle/data-preservation repairs applied first.**

These are focused follow-ups for otherwise deliberately constrained workflows, not findings that every application is insecure.

- **Git and Obsidian:** Preserve recovery references, non-force atomic pushes and refusal of divergent history. Cooperative locks do not exclude arbitrary manual Git or synchronization clients. If a race leaves a staged index or local commit, report that recoverable state instead of automatically resetting user changes. Across multiple remote providers, retain per-provider results; the combined publication is not one global atomic transaction.
- **Destructive Git maintenance:** Keep verified private recovery bundles durable before pruning history. Reconcile the saved plan and expected remote/local state before resuming an interrupted operation.
- **Indexing and OCR:** Exclude actual credential-bearing calendar configuration and private exports from document indexing. Test with fake secrets. Preserve output identity and the no-overwrite decision described in section 14.
- **AI history:** Separate history retention from prompt-context reuse. The current memory setting controls reuse while a bounded prompt history is still stored. Rename/explain that behavior or provide a narrowly defined no-history choice if that is the intended promise. Protect recordings/transcripts and describe retention of independent copies accurately.
- **Models and inference:** Preserve per-model locks, authenticated artifact identity, private staging and active-work pruning exclusions. Add aggregate disk-headroom policy for concurrent downloads, target validation of persisted resource values, and explicit model format/license/resource expectations. Model hashes and inference-runtime pins cover different artifacts.
- **Queues and diagnostics:** Apply count/byte/age limits under existing ownership locks to failed-sync reports, delivery backlogs and retained diagnostic output. Preserve useful recovery evidence without allowing indefinite growth.
- **Firmware/device operations:** Keep Samsung flashing unavailable until the native tool can maintain the selected device identity through mutation. For programmer/UART workflows, validate the actual chip/device, voltage and usable backup as part of the operation; menu selection is not proof of physical correctness. Do not invent a selector the native tool cannot enforce.
- **Accounts and deployment identity:** Validate supported reused subordinate-ID allocations against authoritative account state when non-fresh targets are in scope. Do not repair unrelated accounts broadly. Use a fleet identity scheme with sufficient uniqueness; a short bounded numeric suffix alone does not guarantee collision-free host identity.
- **Trusted profile customization:** Preserve quoting when converting trusted configuration into shell inputs, or reject unsupported values. Current supplied values do not establish safety for every customized quote or expansion. Treat sourced profiles as trusted executable inputs, not an unprivileged data API.
- **Policy learning:** Keep generated AppArmor grants reviewable before the existing explicit apply action. Show the proposed scope and risk-expanding permissions; observed denial text is not proof that the application needs the requested authority.

**Benefit:** Recovery remains under user control, retained data matches stated privacy choices, and convenience workflows do not claim stronger identity, atomicity or physical safety than they implement.

**Acceptance:** Concurrency with manual edits, interruption after local/remote commit, restoration from a verified recovery bundle, fake-secret indexing, disabled history/reuse semantics, concurrent model downloads, bounded repeated failures, and fail-closed device replacement. Apply section 7's ownership rules to every cleanup path involved.

## 22. Make release validation match the deployed system

**Priority: P1 for validator lifecycle and inventory correctness; P2/native gate for installed-system claims.**

The existing live container probe requires conditions incompatible with the ordinary disposable source-test guard: an installed manager, installed helpers and service/image state. Bypassing that guard would remove the protection precisely when the check needs broader authority.

The release inventory also tests directory status before explicitly rejecting directory symlinks, and its output exclusion can miss the actual generated evidence location. That can omit a prohibited entry or include stale evidence. It is not proof that the supplied payload escaped its intended tree.

### Required implementation

- Preserve ordinary checkout refusals. Provide a separate explicitly approved disposable installed-target workflow with its own packages, managers, devices, sockets and network. No host mount/socket fallback or override flag should turn the source-test environment into the real host.
- Apply section 7 to validator TERM/KILL/reaping paths, including descendants surviving leader exit. A test runner must not outlive its declared ownership or signal an identity it no longer holds.
- Inspect entry type without following it before directory handling. Reject disallowed symlinks explicitly; exclude the actual evidence destination and use a fresh run identity so old output cannot contaminate the result.
- Validate rendered commands and native behavior at the affected boundary. Text assertions and an inventory are useful structural evidence, not substitutes for the shell-phase, transaction or service behavior that failed.
- Record the exact source/product identity, disposable image, systemd 262 package build, interpreter/native tool versions and actual result of each required gate. Report failed, skipped, blocked and not-run cases separately.
- Rebuild generated installation products only when implementation inputs change, then verify that preseed, manifest and payload refer to the same generation. The current audit made no such source change.
- Keep historical evidence dated and separate from current release acceptance. Older package versions, counts and test runs cannot establish the current Forky/systemd 262 result.

**Benefit:** A release decision is based on the actual target and changed contracts, without weakening the isolation that protects the development host.

**Acceptance:** An ordinary checkout still refuses execution; the dedicated installed-target workflow can exercise its intended services; interruption leaves only owned recoverable state; directory-symlink and stale-evidence fixtures are rejected; and the final report distinguishes static, fixture and native evidence accurately.

## Implementation sequence and ownership

Keep each change limited to the affected implementation, its callers and the specific acceptance case. Reuse the existing locks, staging helpers, process supervisors, release formats and configuration authorities. Do not bundle cosmetic renaming, module reshuffling, formatting or unrelated feature changes into these repairs.

| Delivery step | Work to complete | Dependency and exit condition |
|---|---|---|
| **1. Restore install correctness** — installer owner | Sections 1–2: embedded execution, complete phase state, preserved EFI handling and handler registration. | Ship the two F2FS repairs together. All supported installation routes reach completion without altering preserved boot files. |
| **2. Close deployment security risks** — boot, packaging and desktop owners | Sections 3–6: private-key export, exact trust identity, legacy package authentication, firewall recovery and notification defaults/backlog policy. | Affected optional capabilities stay explicitly unavailable until their boundary is verified. Uncertain rollback never discards evidence. |
| **3. Establish shared execution guarantees** — runtime owner | Sections 7–8 and relevant validator fixes: process identity, final deadlines, unknown outcomes and streaming limits. | Complete the runner contract before relying on it in vendor repair, diagnostic rollback, device cleanup or publication. Preserve intended interactive and shared-service lifetimes. |
| **4. Repair persistent transactions** — security and package owners | Sections 9–12: policy/key publication, vendor recovery, optional integration, transport checks and boot/package completion. | Failure injection proves exact restoration or retained recovery. Retry converges without inventing a successful previous outcome. |
| **5. Repair user-visible correctness** — desktop, storage and tooling owners | Sections 13–16 and the corrective rows in 20: save intervals, power ownership, output preservation, log origin, zram and cleanup boundaries. | The enabled feature reports its actual result and preserves user data through interruption. |
| **6. Freeze operational contracts** — platform and release owners | Sections 17–21: effective authority, publisher identity, dependency closure, maintenance ownership, native compatibility and privacy/recovery scope. | Every enabled capability has an explicit supported contract and owner; unsupported variants are rejected clearly. |
| **7. Accept the release** — release owner | Section 22 and the native gates below. | Evidence is tied to the final source/product and exact Forky/systemd 262 image. Remaining failures block the affected release capability. |

The ordering is by dependency, not a request for one large patch. Independent corrections such as the malformed APT refresh command can proceed alongside foundational work, provided their release evidence remains tied to the final snapshot. Estimated effort should be assigned after the small patch boundaries are reviewed; the static audit does not justify invented delivery dates.

## Native acceptance required before rollout

The section-specific acceptance cases above remain unexecuted. Run the enabled-profile cases in an explicitly prepared disposable target. Physical acceptance additionally requires designated test hardware and an approved procedure; designating a device does not permit development-host access or bypass the test guard.

Tie results to the final source/product and exact Forky/systemd 262 image. Include first boot, repeat maintenance and recovery where the affected contract crosses those boundaries. Verify requested AppArmor modes and required enforcing profiles rather than inferring the loaded policy from template text. Document any required firmware enrollment or boot-menu interaction; an unattended installer does not by itself establish zero-touch firmware provisioning.

## Controls the implementation plan must preserve

- Native Wayland operation and the existing private Xwayland exception for Zoom and Discord only.
- Peer/namespace identity checks, explicit privileged authorization and the distinction between shared rootless Podman and privileged Incus.
- The repaired standalone firewall recovery behavior; it is separate from the open desktop transaction defect.
- Existing identity-safe container bootstrap cleanup, conservative archive extraction and model-lock/pruning ownership.
- Validated staging, no-overwrite artifact publication, exact signing identities and private secret transport already present in the stronger workflows.
- Fail-closed Samsung flashing, deliberate manual update boundaries and explicitly authorized destructive operations.

These are regression requirements, not additional implementation projects. The release is ready only when the required fixes and enabled-feature acceptance gates are supported by current evidence.

## Primary references

These references support the native contracts used above. They do not certify that the supplied implementation passed target execution. For version-sensitive behavior, the release evidence must retain the documentation and package version used by the actual Forky/systemd 262 image.

- [POSIX shell command language][posix]
- [systemd execution environment and credentials][systemd-exec]; [systemd process termination][systemd-kill]
- [Python subprocess lifecycle and capture semantics][subprocess]
- [Debian APT authentication][apt-secure]
- [Linux kernel module signing][module-signing]; [MOK administration][mokutil]
- [ntfy authentication and access control][ntfy]
- [ExifTool output, overwrite and PDF behavior][exiftool]; [supported file formats][exiftool-formats]
- [wlroots portal capability declaration][wlr-portal]
- [UDisks mount-option and driver policy][udisks]
- [OBS package implementation and stored API origin][osc]

[posix]: https://pubs.opengroup.org/onlinepubs/9799919799/utilities/V3_chap02.html
[systemd-exec]: https://manpages.debian.org/testing/systemd/systemd.exec.5.en.html
[systemd-kill]: https://manpages.debian.org/testing/systemd/systemd.kill.5.en.html
[subprocess]: https://docs.python.org/3.14/library/subprocess.html
[apt-secure]: https://manpages.debian.org/testing/apt/apt-secure.8.en.html
[module-signing]: https://docs.kernel.org/admin-guide/module-signing.html
[mokutil]: https://manpages.debian.org/testing/mokutil/mokutil.1.en.html
[ntfy]: https://docs.ntfy.sh/config/#access-control
[exiftool]: https://exiftool.org/exiftool_pod.html
[exiftool-formats]: https://exiftool.org/index.html
[wlr-portal]: https://github.com/emersion/xdg-desktop-portal-wlr/blob/master/wlr.portal
[udisks]: https://storaged.org/udisks/docs/mount_options.html
[osc]: https://github.com/openSUSE/osc/blob/master/osc/obs_scm/package.py
