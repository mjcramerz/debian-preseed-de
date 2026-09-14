# Managed GPG recipient and installer-log repair

Date: 2026-09-15. Baseline: `debian-preseed-de-installer-no-stat-fixed.tar.gz`.

## Incident and evidence boundary

The supplied installation stopped at 2026-09-14 22:17:38 UTC. Immediately before
that, the desktop GPG bootstrap reported `status=ready`; the SSH sealing helper
then emitted `InstallError: managed GPG key cannot encrypt`. Earlier in the same
run the managed Aptly signing-key import completed. Codex installation and its
ownership checks had already completed, so the previous missing-`stat` clone
staging failure was not the failure in this run.

The complete supplied files were inspected, including earlier package and kernel
messages rather than only the final fatal lines. No newly supplied raw log,
private initrd, actual passphrase, deployment private key, or customer keyring is
added to the served repository. Source references below use LF-delimited physical
line numbers; rendered text tools split additional carriage-return progress lines.

| Input | Bytes | SHA-256 |
|---|---:|---|
| installer.log | 607588 | `866d0fda65b36afe622d2085b0aebb02dc83442bb33edc47ee5bf12bf9a6c7a2` |
| syslog | 1779185 | `dedf907cf0e49719c4db76ca4aad8f328d9308e2e8c3a3be3e52914317f28f2d` |

Evidence: installer.log 4098-4114 records the bootstrap-ready/seal-failed sequence;
its earlier Aptly import and Codex steps appear around 21:46-21:47 UTC. The logs do
not include a complete colon-formatted customer secret-key listing. No assertion
about the exact bytes or capabilities of the customer's private imported key is
made. The incompatible whole-keyring assumption is directly visible in the
baseline source, and the exact diagnostic was reproduced with disposable keys.

## Root cause

`desktop_bootstrap_primary_account_gpg_key` deliberately selects a managed desktop
identity by its UID and checks its encryption capability and ultimate owner trust.
The DevOps importer also deliberately installs an Aptly signing identity into the
same account's `.gnupg` directory.

The previous `managed-ssh-install.py:seal` ignored the bootstrap's selection. It
listed **every** secret primary, rejected the operation if **any** of them lacked
an encryption capability (or was invalid), and then required the entire keyring
to contain exactly one primary. A valid desktop key could therefore never make
the intentional shared-keyring arrangement reliable. Selecting the first usable
key instead would also be wrong: it could encrypt the SSH passphrase to an
unrelated identity.

A real GnuPG 2.4.7 fixture containing a signing-only primary and a future-default
desktop identity reproduced exactly:

```text
Two generated secret identities; primary capability fields: ['scSC', 'scESC']
PRE-FIX REPRODUCED: InstallError: managed GPG key cannot encrypt
```

## Implemented correction

The desktop bootstrap now returns its validated full primary fingerprint through
a root-private temporary record. It invokes:

```sh
managed_git_ssh_target_action seal --gpg-fingerprint "$gpg_fingerprint"
```

The Python CLI requires that argument for sealing and rejects it for the other
actions. It scopes both public and secret listings to that exact fingerprint and
checks that GnuPG returned the expected primary. Only that identity's usable,
locally available encryption key/subkeys are candidates. Ultimate owner trust,
non-revocation, non-expiry, encryption capability and safe filesystem metadata
remain required. Signing-only, absent, disabled, mismatched, malformed and
card/offline-only candidates fail closed; no unrelated identity is a fallback.

GnuPG's uppercase aggregate `E` and lowercase per-key `e` have different meanings;
the parser preserves that distinction. It checks the local-secret indicator and
forces the chosen encryption subkey by full fingerprint plus `!`, preventing a
newer unavailable card/offline subkey from being selected instead. It accepts the
40- and 64-hex primary/fingerprint forms already supported by the bootstrap.

The Aptly key is not deleted, replaced, re-generated, moved, or modified by the
sealer. The normal desktop identity and its existing passphrase protection remain
in use. The runtime askpass/decryptor does not need a new secret source: it
continues to decrypt the resulting GPG ciphertext through its existing pipe.

The other GPG consumers were also checked: Aptly runtime publishing already
selects its configured signing fingerprint; the external-software repository's
single-key rule applies to its separate root-managed `repository-signing`
directory, not the desktop account's keyring. Firstboot validates the managed
SSH files and unit metadata, not an account-wide single-GPG-key assumption. The
runtime decryptor uses the ciphertext recipient. No second whole-account-keyring
restriction was found in those paths.

## Secret handling and lifecycle

The GPG bootstrap's existing temporary passphrase transport now uses one random,
root-private target staging directory, rather than a predictable target pathname
plus a second installer-side copy. It is normalized to `0700`, including clearing
inherited set-ID bits. The result record is `0600`. Its full primary fingerprint
is public metadata, not a password.

Success, bootstrap failure, invalid/missing fingerprint, sealing failure and
HUP/INT/TERM clean up the stage. Cleanup errors cannot report success. The target
bootstrap stops its installer-owned GPG agent on both success and failure; the
sealer also stops any account agent autostarted by its secret-key listing before
publishing the ciphertext. These are installation-time operations, not runtime
logout actions or an instruction to kill a user's live desktop agent.

The Git SSH passphrase continues to enter through the private initrd reader and
a private stdin pipe. Its SSH askpass transport remains anonymous sealed memory.
Only the encrypted OpenSSH key, public key and GPG ciphertext persist. No new
password argument, environment entry, log entry, HTTP input or plaintext Git
passphrase file was introduced. No installer-side `stat` dependency was added.

## Other corrected log-related integration issues

**APT pseudo-terminal errors.** Four adopted-binary APT transactions logged
`posix_openpt (19: No such device)` (installer.log 2123, 2145, 2167 and 2189).
The installer-only loop in `scripts/late/software.sh` lacked `DPkg::Use-Pty=0`,
although the neighboring direct-chroot APT path already used it. The loop now
uses the same option. Package exit-status handling and diagnostic output are
retained. No `/dev/pts` mount or new namespace/capability permission is required.

**Installer/target locale boundary.** The log contains invalid/unavailable locale
diagnostics and three apt-listchanges locale warnings (syslog around
18785-18865 and later). The common `target_exec` transport previously inherited
the installer's locale state into the upgraded target. It now runs the installer
bridge with `LC_ALL=C`, drops inherited `LOCPATH` and `LANGUAGE`, and supplies
`LANG=C.UTF-8 LC_ALL=C.UTF-8` to the target command. Explicit per-command locale
overrides still work. User desktop locale files are not changed. This corrects
the managed transport boundary, not unrelated earlier calls in vendor d-i code.

## Disposition of the other warning/error families

| Log family / evidence | Review disposition |
|---|---|
| Initial Intel Wi-Fi firmware failures, syslog 1145-1179 | Media firmware discovery subsequently installs and successfully loads the requested firmware. The optional debug-yoyo file is explicitly ignored by d-i. No driver rewrite or fabricated firmware supplied. |
| Early debootstrap missing fields/pre-dependencies, syslog 1602-2218 | They occur during initial package unpack/configuration and the bootstrap advances to the full package installation. They are not the terminal late-command failure. |
| Missing media package indexes, setupcon cache directory, embedded-firmware marker | These belong to the private installer/media or vendor d-i bootstrap, which is not part of this served repository. Later phases proceed. No claim to have rebuilt/repaired that external media. |
| NVIDIA hook targets installer kernel, syslog 16908-16918 and 17409-17419 | Package configuration generates an initrd for the running installer kernel, whose modules are absent in the target. Later target kernel initramfs generation succeeds (syslog 18152-18154). The managed late stage then repairs installed kernel signatures/initrds and passes boot-pair validation (installer.log 1178-1192). No dummy modules, kernel build, or removal of rescue images. A successful target boot is still a live acceptance item. |
| Vendor AppArmor profile reloads against the chroot | Package postinst reload attempts cannot use an active target kernel interface. Later managed policy mode staging explicitly avoids loading into the installer kernel and succeeds. These are not evidence justifying broader policy. Existing profile sources and isolation remain unchanged. |
| CUDA legacy signature warning, syslog 6481 | The selected legacy class explicitly disables archive authentication/date checks for that source, as logged in installer.log 390. This pre-existing, reduced-assurance policy is not silently broadened, endorsed as authenticated, or changed as an unrelated fix. |
| Certificate/key trust notices and CA-bundle rehash notice | They are distinct from the managed desktop GPG recipient; normal later package/verification steps succeed. No trust shortcut for the desktop identity is introduced. |
| EFI-variable and SB_MOK USB discovery warnings | Installer GRUB installation reports success; later alternate/removable-path and signing-media probes produce warnings. No firmware enrollment or boot success can be established from these logs. The disposable-target boot/MOK acceptance remains necessary. |
| User home ownership warning during user creation | The storage-layout stage pre-creates the home; later account/desktop provisioning applies its ownership policy and reports completion. Not the GPG capability mismatch. |
| FAT CP850 conversion, Btrfs runtime-feature deprecation, partition alignment tolerance | The recorded formatter fallback and subsequent mounts succeed; the existing alignment tolerance is explicit. No destructive storage-layout changes are made to silence these messages. |
| `/etc/mtab` symlink, denied service start/runlevel/fake-daemon messages, dbus compatibility messages | These arise from offline target construction. Do not start target daemons in the installer or replace normal mtab symlinks to hide them. The managed D-Bus compatibility stage completes. |
| PCI resource/ROM, ACPI/ASPM and SGX messages | Firmware/hardware constraints reported before the application phases. No speculative kernel parameter changes based only on these logs. |
| Missing `/dev/sda2` during signing-medium probes | Existing initrd fallback and later import completion are recorded. The served repository cannot manufacture an absent USB partition. |
| Logrotate debug warning | The command is a dry-run validation by design, not a request to rotate live logs inside d-i. |
| No workspace-local task strip on stock labwc | An explicit existing limitation without a broker; the log names native Alt+Tab as the fallback. Not an installation failure. |
| Unversioned local-APT metadata baselines / newer upstream versions | Existing supply-chain limitations are explicitly reported; no fabricated digest or automatic unpinned upgrade is introduced. |
| Duplicate desktop informational lines | Existing logging outputs to two paths/categories. No duplicated cryptographic operation is inferred from duplicate messages. |

These dispositions distinguish corrected repository defects, successful fallbacks,
and external/live-target items. They do not assert that every warning disappeared
or that a machine was successfully booted after the correction.

## Scope preservation

Production changes are limited to the installer GPG bootstrap/sealer, the common
target locale boundary and the adopted-binary APT command. The managed Git guide
and regression tests document those changes. The matching payload, manifest and
preseed are regenerated together.

The existing SSH host policy, runtime SSH/GPG loader, AppArmor profiles, systemd
units including selective `PrivatePIDs`/`PrivateUsers` decisions, power-action
flows, GitOps engine and protection lists, debugsys collectors/hooks, Codex SSH
clone staging and runtime agent isolation are unchanged. The archive comparison
lists all changed files and verifies retention of every baseline file and mode.

## Deployment and acceptance

Publish the complete new snapshot together, including `payload.tar.gz`,
`payload.manifest` and `preseed.cfg`; do not mix generations. The failed installer
has already cached the old payload under `/tmp/install-runtime`. Replacing HTTP
files does not replace its executing helper. Start a fresh disposable installer
boot against the new snapshot; do not remove the terminal-failure marker and
resume arbitrary partially completed destructive phases.

Keep the existing private initrd key pair and `/preseed.env` outside the served
checkout. Do not delete the Aptly identity, make the GPG key unprotected, disable
AppArmor, loosen SSH host verification, or add `stat` to d-i to work around this
incident. None is required by this fix.

On the live acceptance target, confirm that the desktop bootstrap is followed by
successful sealing, the ciphertext belongs to the account with mode `0600`, the
Git SSH private key remains OpenSSH-encrypted, and no private staging directory
or installer-owned GPG/SSH agent remains. After first boot, exercise normal
`git-ssh unlock`, agent-backed signing, cancellation/retry, logout cleanup,
provider authentication, AppArmor enforcement, and the existing secure-boot /
initramfs acceptance procedures. Do not print or export the decrypted secret as
a diagnostic.

## External specification references

The implementation was checked against GnuPG's primary documentation, separately
from the customer log evidence:

- https://raw.githubusercontent.com/gpg/gnupg/master/doc/DETAILS : colon records,
  aggregate versus per-key capabilities, validity, ownertrust and local-secret
  indicators.
- https://www.gnupg.org/documentation/manuals/gnupg/Specify-a-User-ID.html : full
  fingerprint selection and `!` to force the specified primary/subkey.

No component was compiled. Offline test results and their explicit limitations
are in the accompanying validation report.
