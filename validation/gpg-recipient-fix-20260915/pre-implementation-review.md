# Pre-implementation review - 2026-09-15

Basis: the previous complete no-stat-fixed archive, all 4,114 physical lines of
installer.log (Files rendering includes additional blank-line positions), and
all 20,324 physical lines of syslog. Raw user logs are not copied into the
public codebase. SHA-256 and line references will accompany the final review.

## Reproduced blocking defect

The desktop bootstrap chooses one secret primary by its managed UID and verifies
its public aggregate encryption capability. Earlier, devops imports the Aptly
signing secret into this same account's .gnupg. The sealing helper instead lists
ALL secret keys and insists every primary can encrypt and that the entire
keyring contains exactly one primary. That contradicts the existing design.
A real GnuPG fixture with a signing-only primary plus future-default desktop
identity reproduces exactly `InstallError: managed GPG key cannot encrypt`.

Correction: hand the validated full desktop primary fingerprint from bootstrap
to seal over a private root-owned staging record, require it explicitly in the
installer CLI, scope both public and secret listings to that primary, validate
local encryption subkey material, and never remove/change the Aptly identity.
No random key fallback, no downgrade, no unprotected GPG key, and no secret in
argv/env/logs. Cover cleanup and mixed-keyring cases with real GnuPG tests.

## Other actionable integration inconsistencies

1. Four adopted-binary APT transactions omit DPkg::Use-Pty=0 although the adjacent
   direct-chroot package installation path already uses it. The resulting four
   posix_openpt errors are nonfatal in these logs. Apply the same non-PTY option
   to this installer-only path, retaining diagnostics and package exit checks.
2. The common in-target transport inherits installer locale variables while
   executing newer target libc/locales. Logs contain invalid/unavailable locale
   diagnostics. Use C for the installer bridge and C.UTF-8 for its target child;
   preserve user locale configuration and allow explicit command overrides.

## Reviewed, not an authorization for speculative changes

Wi-Fi firmware was subsequently loaded; debug-yoyo is explicitly ignored by d-i.
Early debootstrap dependency warnings completed successfully. Vendor AppArmor
reloads were attempted against a non-booted chroot; managed policy staging later
succeeds without loading into the installer kernel. Missing installer-kernel
modules in NVIDIA maintainer initramfs calls precede successful target XanMod
installation; do not fabricate modules or compile components. Inspect final
boot validation before claiming those transient images are safe. CUDA legacy
authentication bypass is explicitly selected by the profile; do not silently
change that policy or call a missing signing key trustworthy. PCI/firmware/BIOS
messages, SB_MOK USB discovery, intentionally suppressed os-prober, alignment
tolerance, and workspace limitations are distinct from the GPG terminal error.
AppArmor policies, PID/user namespace decisions, power controls and Codex clone
staging must remain unchanged unless a separate reproduced defect requires it.
