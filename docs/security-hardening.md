# Security repair, authoring contract and acceptance gates

Target: Debian Forky, systemd 261.2. This revision addresses the supplied findings;
repository checks do not substitute for a booted target or a physical TPM test.
The packaged binaries remain the execution dependencies. No vendor source patch
or new source-compilation step is introduced. Existing private Xwayland support
remains restricted to Zoom and Discord and is not changed by this repair.

## Directly editable sources and modular installation

`d-i/forky/` is the only installer/installed-system source tree. There is no root
`src/` directory and no profile generator. Every environment under `hosts/`, and
`repo.env`, remains a directly editable input. No build command replaces those
files with a schema/default-derived version. The ten host profiles retain their
complete settings; changing one profile does not rewrite any other profile.

Shared paths and filesystem policy remain in `hosts/installer/`; logging policy
remains in `hosts/logging/`. Resolution order is unchanged: profile, identity,
runtime, observability, layout, storage family, then boot policy. Hardware class
mappings and tuning values are retained, not guessed or retuned.

The large common, desktop and DevOps implementations now execute from real modules
inside `scripts/common/modules/`, `scripts/desktop/components/`, and
`scripts/late/devops/`. The storage runtime additionally uses
`scripts/runtime/modules/`. Four small entrypoints list the 46 modules explicitly,
by dependency order. There are no generated monolithic mirrors. The existing
validation, configuration resolution, action and verification functions keep
their implementation and ordering; the DevOps entrypoint invokes `devops_main`
only after its definitions load. Sourcing definition modules does not execute
installation actions.

`bootstrap_source_module` in `scripts/common/bootstrap.sh` is the shared loader.
It resolves only explicit safe script paths through the existing repository
transport and logging renderer, into a private runtime directory. It rejects
symlinked/writable module directories and linked destinations. A missing member
of an authenticated payload never falls back to a moving remote or local source,
or silently sources a stale staged file. Remote module loading requires the
preseed-authenticated snapshot. Explicit trusted local development inputs retain
the existing bootstrap transport semantics; they are not a remote authentication
bypass. Source code and runtime state remain trusted administrator/installer
inputs, not a security boundary against another process with the same root uid.

The credential, debconf and APT-source readers have one shared implementation.
Lifecycle has one authoritative implementation with the sole necessary embedded
bootstrap copy in `source.sh`, which must operate before a payload is available.
Common and storage libraries no longer carry duplicate embedded readers.

Run `python3 -B tools/build.py` as the repository owner after editing. The builder
validates inputs and module wiring, refreshes existing browser/bootstrap artifacts,
and packages the actual editable files into the deterministic payload and manifest
with updated preseed pins. `--check` is non-mutating and never repairs input files.
`tools/check_modules.py` validates references, module inventory, shell syntax and
the rsyslog spool settings; it writes nothing.

Snapshot publication uses `tools/publication.py`: immutable byte inputs, an
absolute destination, a fixed output allowlist, temporary files, fsync, rename,
and owner/mode/hash postconditions. Environment-file destinations are rejected.
Handled snapshot publication failures restore the previous generation. This is
**not** multi-file power-loss atomicity: rerun/check after interruption and deploy
the complete checked repository using an atomic deployment-directory switch.
Never serve a directory while rebuilding it or edit inputs during publication.
Private initrd inputs and deployment credentials remain outside the served tree.

Regression checks cover real module loading with dash and BusyBox ash, a new
standalone cached-hook process, dependency/metadata failures, and all environment
files surviving both build and check. Older isolated function fixtures read
actual module definitions into temporary test views; they do not exercise or
replace the real loader tests and never generate production sources.

## Storage and the installation failure

Every profile contains `TMPFS_VAR_SPOOL_RSYSLOG="true"` and
`SIZE_TMPFS_VAR_SPOOL_RSYSLOG_MIB="256"`. The latter is the canonical size;
`SIZE_TMPFS_RSYSLOG_SPOOL_MIB` is a derived compatibility alias in `layout.env`,
not a second independently configurable setting. Both storage families call one
emitter. The mount is `/var/spool/rsyslog`, with nodev, nosuid, noexec, mode 0700,
`huge=within_size`, a 256 MiB ceiling, and a systemd dependency on `/var/spool`.
The size is a limit, not a reservation. The existing 64 MiB rsyslog disk-assisted
queue and 8 MiB segment policy fit within this supplied ceiling; reducing the
ceiling below queue requirements is not a supported operational tuning.

The tmpfiles ownership, rsyslog work directory, service mount dependency, mount
pre-clean ordering, allowed paths and generated cleanup policy agree. Disabling
the flag suppresses this fstab mount and its conditional pre-clean wiring; the
ordinary private spool directory remains. Volatile queues are deliberately lost
at reboot and do not offer durable message delivery or reboot-retained forensics.

The tailscaled/defaults guard now accepts root:root, single-link, non-writable
configuration files with restrictive read modes, including 0640, instead of
assuming only 0600/0644. It still rejects symlinks, hardlinks, non-root ownership
and group/world-write access, validates the parent, and renders the managed file
with the intended installed mode. A rejection now includes observed metadata.
The original failure report did not contain its stat output, so the precise
historical mode cannot be established from that message alone.

## A01-A04: ownership and privileged input

**A01.** The firewall owns only `inet labwc_filter` and `ip labwc_nat`. An atomic
transaction destroys/recreates those named tables; a global flush and arbitrary
ownership names are rejected. Disabled managed NAT is also removed, so an old
managed NAT table cannot linger. The service stop override does not flush the
kernel ruleset. Other owners' tables are neither enumerated nor restored.

Persistent local extensions belong in root-maintained `/etc/nftables.local.d/*.nft`
and may append rules to the managed `local_input`, `local_forward`, or
`local_output` chains. The UI-maintained `95-firewall-security.nft` and its state
are preserved during re-staging. Rules inserted only at runtime **inside the
project's tables** are not persistent: put such rules in a local snippet. Do not
place one-shot creation of independently owned tables in repeatedly included
snippets. An upgrade from the old generic `inet filter`/`ip nat` names requires an
administrator to inspect and migrate/delete only positively identified old project
tables; automatic deletion would reintroduce the ownership defect. Coexisting
base-chain verdicts still interact: preserving another owner's table is not a
promise that its traffic is permitted by every other firewall policy.

**A02.** The actual installer initramfs function rejects the current
`var/lib/tpm2-enrollment/install-passphrase`, the obsolete pathname, enrollment
configuration and the home key. Tests pass synthetic member listings through the
production function, including `/` and `./` prefixes. This fixes a broken negative
check; it is not a claim that an installed initramfs was found to contain a secret.

**A03.** Passwordless inspection uses exact arguments or anchored single-unit
regular expressions. Argument-free `dmesg` is explicitly `""`; clearing logs,
changing journal storage, adding extra systemctl options, or adding commands is
not authorized by that alias. Ordinary password-protected administrative sudo is
unchanged. `visudo` validates the rendered syntax.

**A04.** After existing authorization, the OpenVPN reader drops supplementary
groups, gid and uid before opening any caller-controlled path component. It rejects
symlinks, unsafe metadata, changes while reading, oversized input and external
file/script/plugin directives. The privileged parser gets a root-private snapshot,
not the original pathname. Only self-contained `.ovpn` files are accepted; embed
certificates/keys, and use NetworkManager credential prompting instead of a path to
an authentication file. Intentional external-file profiles require direct,
password-authenticated administrator configuration outside this import action.
WireGuard behavior is unchanged. Failed imports remove the temporary snapshot.
The authorized wrapper has a mandatory transition into a dedicated import policy;
its dropped-uid reader and private snapshot paths have explicit permissions.

## A05-A06: application containment and extraction

Tuta explicitly enables Electron's inner sandbox. The conditional Mullvad Browser
RDD-disable environment variable is removed. No unsafe fallback is added.
Tuta-specific AppArmor policy permits its nested user-namespace setup; the shared
desktop/Electron abstraction is not given broad new capabilities. Namespace-local
AppArmor capability permission does not grant a host capability to an unprivileged
process. A GUI smoke test on the actual GPU/vendor build remains required.

Both Tuta installer and updater use `/usr/local/libexec/tuta-extract`. A verified
AppImage is **never executed as root to extract itself**. The helper snapshots the
artifact, verifies SHA-256, bounds/parses Type-2 ELF/SquashFS metadata, and runs the
packaged `unsquashfs` inside private filesystem/PID/network/IPC/UTS namespaces.
Its dedicated locked `tuta-extract` identity is provisioned by packaged
`systemd-sysusers`; it is not the shared `nobody` principal. Extraction is serialized,
preexisting processes under that identity are rejected, and inherited groups,
capabilities, privilege gains and host credential/home access are removed.

Limits cover input/output sizes, entry counts, CPU, address space, file size,
descriptors and wall-clock execution. The output expansion watchdog is not a hard
filesystem quota. Escaping links, hardlinks, special files, unexpected AppRun
metadata and hash mismatches fail before publication. Files become root-owned with
set-id/write bits removed. Existing caller generation backup/rollback remains in
place. Parser namespace/tool failure is fatal, not permission to run the AppImage.
The updater makes a mandatory transition into a dedicated extractor policy, with
a separate bubblewrap child domain; its former Tuta-AppImage execution permission
is removed. This does not alter Ledger or private Zoom/Discord policies.

## A07: measured-boot release is a state machine, not an enrollment command

The final policy is SHA-256 PCR **7+8+9+14 plus PIN**. Packaged GRUB TPM measurement
is enabled. The helper requires Secure Boot, replays the TPM2 event log, identifies
kernel-command-line and initrd measurements, and compares the replay with actual
PCR values. A nonzero PCR alone is not accepted as evidence. Unmeasured or
incompatible boot paths fail closed; there is no silent PCR-7-only fallback.

Finish normal firstboot provisioning and let secondboot cleanup rebuild initramfs
without the temporary health hooks. Reboot into that cleaned image **before**
final enrollment. Run `sudo /usr/local/sbin/tpm2-enroll.sh` interactively. It requires
and tests an offline recovery passphrase for both root and home, enrolls the PIN
policy, verifies the exact token using cryptsetup's token-only test path, compares
LUKS metadata before/after, removes bootstrap passphrase slots, and records an
`enrolled` generation. The pending gate stays in place. Reboot, run the helper again
with the same recovery secret/PIN, and confirm the existing tokens without mutation.
Only then is the completion marker published and the pending marker removed.

`sudo /usr/local/libexec/tpm2-policy-check --release-check` must succeed before
claiming a released crypto installation. Durable JSON evidence records boot IDs,
PCRs and LUKS-metadata fingerprints. Interrupted publication remains pending or
requires confirmation again. Keep the recovery passphrase offline: changes to the
kernel, initrd, command line, firmware/trust state or measured GRUB path can require
recovery. Boot the intended new image using recovery, run `tpm2-enroll.sh --reenroll`,
and repeat separate-boot confirmation. The permanent helper/configuration/policy
are retained for this maintenance. Never delete the bootstrap secret manually
before verified recovery and final-token checks have succeeded.

A physical acceptance run must demonstrate valid PIN/recovery, wrong PIN rejection,
changed-command-line/initrd rejection, reboot stability and update/recovery behavior.
These tests were not executed against a TPM in the repository-validation container.
An installation still marked pending must not be represented as having the final
physical-security assurance.

## A08: sealing keys and truthful logging policy

The supplied profiles keep `/var/log` on tmpfs. They now render **Seal=no**, even
when journal Storage is named persistent: that directory is still volatile in
these profiles. Disk-backed persistent journaling (`TMPFS_VAR_LOG=false` and the
nonvolatile journal policy) renders Seal=yes and enables the oneshot
`journal-sealing.service`. Effective logging configuration is checked for drift.

The helper verifies a disk-backed journal and RAM-backed `/run`, provisions keys
only when absent, never forces replacement, rotates to begin a sealed generation,
and stores the verification seed **only under root-private `/run/journal-sealing`**.
Persistent evidence contains its fingerprint, not the verification secret. Transfer
the output of `sudo /usr/local/libexec/journal-sealing --show-verification-key`
directly to an independently protected off-host destination **before reboot**.
Compute SHA-256 over that exact output, including its newline, then run
`sudo /usr/local/libexec/journal-sealing --acknowledge-export <sha256>`.
This explicit operator attestation removes the on-host RAM copy.
`--release-check` refuses an unexported/unacknowledged generation. A lost seed or
preexisting unmatched FSS state requires administrator recovery; the helper will
not silently destroy/replace an existing sealing generation. Export is an operator
attestation, not proof of remote durability. Existing journals are not retroactively
sealed. Validate an archived journal with the independently retained verification
key on the acceptance system.

## A09 and validation boundaries

A user systemd unit, cgroup, transient scope or private PID namespace provides
lifecycle/resource management, not general isolation from the same account.
That account can modify its writable files, exercise delegated user-manager/IPC
permissions and launch other processes. Use explicit AppArmor and filesystem,
capability, namespace and IPC restrictions for containment; use a distinct UID or
VM for a separate security principal. Portal/DBus permissions are deliberate
capability delegations. A completed unit or empty cgroup is not proof that an
application could not affect another permitted resource.

`docs/validation/latest/` records the final executable checks and blocked tools.
Static hardware mapping/profile checks are not hardware benchmarks, display tests,
Suspend/resume tests or proof of an absence of performance bottlenecks. No disk was
partitioned, no target system booted, and no new vendor software was compiled for
validation. Before production use, perform the destructive installer run only on
a disposable target, then check `findmnt /var/spool/rsyslog`, rsyslog queue behavior,
reload with foreign nftables tables present, Tuta/Mullvad GPU launches, private
Zoom/Discord Xwayland sessions, and the crypto/logging release gates above.

### Primary references used for the design

- nftables manual: https://netfilter.org/projects/nftables/manpage.html
- sudoers command/argument matching: https://www.sudo.ws/docs/man/sudoers.man/
- NetworkManager OpenVPN parser: https://gitlab.freedesktop.org/NetworkManager/NetworkManager-openvpn/-/blob/main/properties/import-export.c
- Electron process sandbox: https://www.electronjs.org/docs/latest/tutorial/sandbox
- GRUB measured boot: https://www.gnu.org/software/grub/manual/grub/html_node/Measured-Boot.html
- systemd TPM enrollment: https://www.freedesktop.org/software/systemd/man/systemd-cryptenroll.html
- Journal key provisioning: https://www.freedesktop.org/software/systemd/man/journalctl.html
- systemd key-output implementation: https://github.com/systemd/systemd/blob/main/src/journal/journalctl-authenticate.c
