# MOK reset and enrollment — 19 October 2026

> Historical snapshot, superseded later the same day by
> [the final MOK/GPG source report](desktop-mok-gpg-20261019.md).
> That report changes reset ordering, fixes the username password and boot
> handoff, and records the current products and the instruction to stop testing.

## Status and scope

Source changes and regenerated installer products are complete in this checkout.
**Disposable fixture execution and native firmware/boot acceptance remain pending.**
No prepared disposable environment was supplied. No host firmware, services,
package state, security policy, mounts or boot configuration were operated on.
No software was compiled from source. Xwayland sources and policy were not changed.

Base revision: `f5d49636569baf5ae22cf6683ff449bfc28198a9` on `mcr/main`.
The requested target is Debian Forky with systemd 262; target execution was not
performed. No installer server publication or verification of served bytes occurred.

This note supersedes the MOK inventory/reset behavior in
[the 18 October report](grub-timeshift-mok-20261018.md#mok-inventory-and-ordering).
Reset failures must remain nonfatal and installation must continue.

## Implemented behavior

### Once per fresh installation, without inventory exclusions

The pre-pkgsel route tries to make `mokutil` available, stages the managed tool,
and requests reset before `prepare-dkms` publishes the new signing material.
The shared staging route also covers late preparation for both storage families.

Every fresh installer lifecycle requests `mokutil --reset`. Inventory output is
informational and discarded. Certificate issuer, the known Debian CA, hashes,
empty output, malformed display text, query failure and query timeout cannot
suppress the reset request. This avoids relying on `MokListRT` as an exact
owner-enrollment inventory or on mokutil display formatting as a mutation gate.

The password uses the existing configured value or account-name fallback and
is delivered twice through stdin. Validation rejects whitespace, controls,
non-ASCII input and values longer than mokutil's 256-byte limit. Passwords are
not passed as command arguments or included in diagnostics.

After command success, the tool requires a nonempty, direct regular `MokAuth`
variable and absence of `MokNew`, including dangling symlinks, before reporting
`queued`. An empty `--list-new` result alone would not prove a pending reset.
The read-only `reset-pending` command repeats this check after package hooks and
immediately before queuing the boot handoff. It does not request another reset.

### Nonfatal failures and uncertain outcomes

The private installer record remains
`/tmp/install-runtime/state/secure-boot-mok-reset.state` by default. It is claimed
as `unknown` before the attempt, then atomically replaced with `queued` only on
confirmed success. Metadata and content checks remain in place. Later phases
reuse the record, including after a failed or interrupted attempt.

Only `queued` permits the automatic MOK boot handoff. `unknown`, unsafe state,
and the obsolete `empty` result do not authorize another firmware reset.
The install continues with a warning. Missing EFI access, missing commands,
password failure, reset failure/timeout, missing pending evidence and boot-queue
failure cannot be converted into successful revocation claims.

Optional target commands use `attempt_in_target`, whose warning path does not
publish the persistent mandatory `first-failure` sentinel. Optional bridge
preflight handlers are confined to warning and exit inside subshells. Catching
`run_in_target`'s exit alone would have left its persistent failure record behind.
Both storage-family callers also confine reset exits before continuing.

Inventory, reset and prompt-timeout commands have respective 15, 30 and 15 second
limits, each with a separate two-second kill allowance. Optional mokutil package
installation has a 240-second limit plus five seconds for termination. GRUB
queueing has 15 plus two seconds; firmware handoff has 45 plus two seconds.
There is no automatic retry of an uncertain firmware mutation.

### Selected ESP and boot handoff

The GRUB profile's `mok_der_path` now identifies the public certificate copy on
the ESP. The configured default is `/boot/efi/MOK Enrollment/MOK.der`; MokManager
sees `/MOK Enrollment/MOK.der`. Spaces are preserved and GRUB device paths are
quoted. Protected signing storage is not presented as a firmware-accessible path.

The generator requires the selected ESP's filesystem UUID and nonempty manager
and certificate files. It validates paths before emitting GRUB syntax. The menu
checks UEFI mode, clears stale ESP state, searches by UUID, checks both files,
sets the root device and then chainloads the selected MokManager. A failed
search does not fall back to another disk that happens to contain the same path.

After rechecking the pending reset, the installer sets and verifies the exact
`next_entry=installer-mok-enrollment` line in grubenv. It then invokes the formerly
unwired shim firmware-entry helper. That helper checks that the ESP belongs to
the selected install disk and matches active entries using the GPT partition
number, partition UUID and shim loader path together. Firmware inventory errors
stop this optional handoff before creation. New entries use `--create-only`;
`BootNext` is set and read back without rewriting persistent `BootOrder`.
Any failure warns and leaves installation running with a manual-menu fallback.

## Physical confirmation and trust scope

`mokutil --reset` queues an authenticated request. MokManager performs the
actual owner-list deletion after confirmation. This contract is visible in
[mokutil 0.7.2](https://github.com/lcp/mokutil/blob/0.7.2/src/mokutil.c) and
[shim 16.1 MokManager](https://github.com/rhboot/shim/blob/16.1/MokManager.c).

The first boot must confirm **Reset MOK** using the configured reset password.
After reboot, select the installed Debian boot entry if necessary, then
**MOK Enrollment**, **Enroll key from disk**, and `/MOK Enrollment/MOK.der` on the
selected ESP. Confirm enrollment and reboot before relying on the newly signed
kernel and modules. The menu describes this order. Reset and enrollment remain
separate operations; queuing an import must not overwrite the reset request.

Reset clears owner-enrolled certificates and hashes in `MokList`. Shim's embedded
vendor CA, firmware PK/KEK/db/dbx and the separate MOK blacklist have separate
trust roles and are outside this reset. A failed/uncertain request does not
establish that any certificate was removed.

Debian's published Forky package pages list
[mokutil 0.7.2-2](https://packages.debian.org/forky/mokutil) and
[efibootmgr 18-4.1](https://packages.debian.org/forky/efibootmgr) for amd64/arm64
at review time. The `--create-only` behavior is documented in
[efibootmgr 18's source](https://github.com/rhboot/efibootmgr/blob/18/src/efibootmgr.c).
These are reference versions, not evidence of packages installed in a test image.

## Changed paths

Runtime inputs:

- `d-i/forky/hooks/installer/pre-pkgsel.d/90secure-boot-dkms.sh`
- `d-i/forky/hooks/target/usr/libexec/install-tools/secure-boot-tool.tmpl`
- `d-i/forky/scripts/late/grub.sh`
- `d-i/forky/scripts/late/btrfs-family.sh`
- `d-i/forky/scripts/late/f2fs-family.sh`
- `d-i/forky/hooks/target/etc/grub.d/40_custom.tmpl`
- `d-i/forky/hooks/target/usr/local/share/grub-profiles/mokmenu.cfg.in.tmpl`

Fixtures, authored/updated but not executed:

- `d-i/forky/tests/test_comprehensive_contracts_20261017.py`
- `d-i/forky/tests/test_hardware_restore.py`
- `d-i/forky/tests/test_installer_hardening.py`
- `d-i/forky/tests/test_installer_shell_boundaries.py`
- `d-i/forky/tests/fixtures/contracts/grub-split.json`

The three generated products are `d-i/forky/payload.tar.gz`,
`d-i/forky/payload.manifest` and `d-i/forky/preseed.cfg`. This note and the
supersession note in the previous report are outside the payload.

## Evidence for this working tree

Permitted serialization command:

```text
/usr/bin/make --no-print-directory build 'PYTHON=/usr/bin/python3 -I'
```

It ran with a minimal `PATH=/usr/bin:/bin`, `LC_ALL=C` environment through an
explicit subprocess argument array and a 120-second supervisor limit.
The final run reported **1,818 payload files**.

Static checks performed:

- `git diff --check`: clean.
- `/usr/bin/python3 -I -B` with standard-library `ast.parse` on the four changed
  Python fixtures and `json.loads` on the GRUB contract. No repository module,
  fixture or installer script was imported or executed.
- Bounded standard-library tar inspection without extraction: all 1,818 members,
  totaling 34,708,095 uncompressed bytes, matched current source bytes and
  manifest hashes, with expected regular-file metadata. All seven changed
  runtime inputs were present. Archive, manifest and bootstrap-source hash pins
  in `preseed.cfg` agreed with the current files.

Working-tree fingerprints use SHA-256 over sorted full repository-relative paths,
each encoded as UTF-8 followed by NUL and the raw SHA-256 digest of that file.
The source set and fixture set are the two path lists above.

```text
changed_sources_sha256=1ff5cc18b24178c7a05e79eaf85761c78003f33ded38b2c5d90609cce6b73604
fixtures_sha256=87631f07c35df032a279cd4d9ee9a2148e74d4c8fd2d8839c50a6c5cd905f6e3
payload.tar.gz_sha256=67855f06a853a4385705013a60c678536ccc9431b0bc254d58bc92f8b2a3d588
payload.manifest_sha256=4adbcc050e322cb634525275bf84864ebc28f72e1b14cc3b37caab375167bb70
preseed.cfg_sha256=b541e866c539319236215d84533e4e1ca1cfe62971f2386b0c9b5d0a737b18c7
```

These checks establish serialization consistency and data parsing only.
Sidecar agents failed during initialization; no independent review result exists.

## Remaining acceptance gates

Under `AGENTS.override.md` and `docs/test-isolation.md`, the following were not run:

1. The four focused fixture modules in an approved disposable environment.
   Cases include certificate/hash/vendor/empty inventories, failed queries,
   password bounds, reset timeouts, pending-variable evidence, stale pending
   state, nonfatal explicit exits, no mandatory failure sentinel, and reuse of
   the per-install record without retrying firmware writes.
2. Native GRUB syntax and amd64/arm64 boot validation, including the certificate
   path with spaces and unavailable/missing ESP assets. The authored chroot
   generator fixture uses a fake GRUB checker and fake EFI/certificate bytes;
   it cannot establish native syntax or signature acceptance.
3. Disposable UEFI/OVMF reset, physical confirmation and new-certificate enrollment
   with persistent virtual NVRAM. Check removal of prior owner certificates and
   hashes, and retention of the separate trust/revocation stores.
4. Failure injection for read-only/unavailable EFI access, pending-write failure,
   timeout/termination, cleared or replaced pending requests and queue failures.
   Verify installation continues, uncertainty is reported, no mandatory failure
   record is created by optional MOK work and no reset is blindly retried.
5. Multiple-ESP, inactive-entry, wrong-parent-disk and identity-replacement cases.
   Verify the selected partition/loader is used and `BootOrder` is preserved.
6. Enforcing target AppArmor and a complete fresh installation through the two
   reboots. The existing scoped `MokAuth`, `MokNew`, `MokTimeout` and inventory
   permissions were inspected as data; no policy parser or policy load ran.

Record the exact disposable image, kernel, systemd, shim, GRUB, mokutil,
efibootmgr, libefivar, coreutils and fixture versions with native results.
No live acceptance or revocation success is claimed by this note.
