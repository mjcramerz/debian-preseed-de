# MOK reset audit remediation — 21 October 2026

## Status and scope

The source fixes for `todo/audit.md` and the three generated installer products
are complete. Evidence is **static inspection and serialization only**. No test
runner, fixture, native shell/policy validator, firmware operation or installation
was executed. The prior instruction to stop testing after the reported host veth
failure remains respected. No approved disposable test environment was used.

Base revision: `3f909b2a571c2ad194e6c1fb3857ff2a174bc4ed`, branch `mcr/main`.
The worktree was clean before these changes. Target: Debian Forky with systemd
262, as specified by the user. Target image identity, installed package versions,
native GRUB, AppArmor and firmware behavior remain unverified. The repository
guidance's `debian-preseed-de-audit.md` is absent; the supplied `todo/audit.md`
was reviewed directly.

This report supersedes the MOK configuration, fallback timeout and reset-state
claims in [the 19 October report](desktop-mok-gpg-20261019.md). It does not change
that report's separate GPG/application work. No software was compiled, no release
was published and no host configuration was changed. Xwayland sources, policy
and the private Zoom/Discord eligibility boundary were not changed.

## Findings and corrections

| Audit item | Correction or retained contract |
| --- | --- |
| 1. Missing primary account in target configuration | `secure-boot.conf.tmpl` now contains `ACCOUNT_USERNAME=__INSTALLER_ACCOUNT_USERNAME__`. The existing real map shell-quotes the value and the installer publishes the configuration with mode `0600`. A new helper process obtains its reset password from that file without an inherited username. |
| 2. Infinite GRUB fallback timeout | The final display fragment selects `timeout=0` only when `boot_once=true` and `default=installer-mok-enrollment`. All ordinary selections retain `timeout=-1`. The fragment uses the variables available after `00_header` consumes and clears `next_entry`. |
| 3. Definite preflight failure recorded as uncertain firmware mutation | The installer prepares efivarfs/target access and invokes the new `reset-preflight` command before exclusively creating the `unknown` attempt record. This command checks root, required commands and the configured password without invoking mokutil or touching EFI variables. A failed preflight leaves no attempt record. After the exclusive claim, interrupted or unsuccessful reset attempts remain `unknown` and cannot trigger another automatic reset. |
| 3. Installation failure policy | The user's earlier explicit warning-and-continue requirement is preserved. Reset and boot preparation failures remain nonfatal, never establish certificate deletion, and cannot queue an automatic management boot without confirmed pending reset evidence. Mandatory installation failure was not introduced. |
| 4. MokManager timeout | Retained `mokutil --timeout -1`; its negative timeout skips MokManager's preliminary keypress countdown. This differs from GRUB's indefinite `timeout=-1`. |
| 5. Stale and incomplete fixtures | Existing fixtures now exercise the real map, scalar renderer, configuration loader, password resolver and reset body in a clean child environment, using a fake mokutil and private EFI files. Inventory-call and `900`-timeout expectations were removed. State fixtures cover preflight return/exit, correction, exclusive-claim interference and uncertain-result reuse. GRUB fixtures cover the emitted fragment and one-time/default combinations. These fixtures were authored and statically parsed, **not executed**. |

The existing reset points remain immediately after GRUB configuration generation
in both `btrfs-family.sh` and `f2fs-family.sh`. Pre-pkgsel continues to stage DKMS
signing material without requesting a reset. The helper still validates the
password immediately before its bounded `mokutil --reset` invocation, checks
pending `MokAuth` and absent `MokNew`, and supplies the password twice over stdin.
No inventory query can suppress the request. The shim BootNext and GRUB fallback
handoffs retain their existing selected-ESP checks and independence.

The password resolver and its single-token validator now explicitly propagate
validation failures. They do not rely on `set -e`, which can be suppressed inside
the conditional command substitution used by the reset caller. The existing
password fixture now uses that same calling context, and the configuration
fixture specifies that a missing username blocks both preflight and reset
without invoking the fake mokutil.

An `unknown` record from an older, already-running installer is deliberately
retained. Updating a template does not prove that no earlier EFI write occurred
and does not authorize clearing that record or repeating an uncertain operation.
The corrected products apply to a fresh installation lifecycle.

## Firmware semantics and reference sources

`mokutil --reset` creates an authenticated reset request. MokManager performs
the actual removal of owner-enrolled certificates and hashes from `MokList`
after confirmation. The confirmation password remains the configured primary
account username. The existing flow then reboots before enrolling the new public
certificate from `/MOK Enrollment/MOK.der` on the selected ESP.

Reference review:

- [mokutil 0.7.2 source](https://github.com/lcp/mokutil/blob/0.7.2/src/mokutil.c):
  reset delegates to an empty enrollment request.
- [shim 16.1 MokManager](https://github.com/rhboot/shim/blob/16.1/MokManager.c):
  reset confirmation, `MokList` deletion and negative countdown handling.
- [GRUB header source](https://github.com/rhboot/grub2/blob/master/util/grub.d/00_header.in):
  `next_entry` becomes `default`, is cleared, and sets `boot_once=true`.
- [GRUB manual source](https://github.com/rhboot/grub2/blob/master/docs/grub.texi):
  zero timeout boots immediately; negative timeout waits indefinitely.
- Debian's public Forky package pages list
  [mokutil 0.7.2-2](https://packages.debian.org/forky/mokutil) and
  [GRUB 2.14-4](https://packages.debian.org/forky/grub-common) at review time.
  These reference pages and the GRUB maintainer tree do not establish the
  packages or patched `00_header` present in a future installation target.

This operation concerns owner enrollment in `MokList`. Shim's embedded vendor
certificate, firmware PK/KEK/db/dbx and the separate MOK blacklist retain their
separate trust roles. No installed-system revocation claim follows from a queued
request, generated archive or successful static inspection.

## Changed paths

Runtime sources:

- `d-i/forky/hooks/target/etc/secure-boot.conf.tmpl`
- `d-i/forky/hooks/target/usr/libexec/install-tools/secure-boot-tool.tmpl`
- `d-i/forky/hooks/target/usr/local/share/grub-profiles/display-2.cfg.in.tmpl`
- `d-i/forky/scripts/late/grub.sh`

Existing fixtures:

- `d-i/forky/tests/test_comprehensive_contracts_20261017.py`
- `d-i/forky/tests/test_hardware_restore.py`

Generated products:

- `d-i/forky/payload.tar.gz`
- `d-i/forky/payload.manifest`
- `d-i/forky/preseed.cfg`

This report is outside the payload.

## Verification evidence

The Makefile, complete `tools/build.py` and imported `tools/publication.py` were
read before generation. The permitted serialization command was executed with
an explicit argument array, `PATH=/usr/bin:/bin`, `LC_ALL=C` and a 120-second
supervisor limit:

```text
/usr/bin/make --no-print-directory build 'PYTHON=/usr/bin/python3 -I'
```

Observed output: `built 1820 payload files`. Generation rewrote only the three
permitted products. It executed no tests or validators.

Static checks:

- `git diff --check`: clean.
- `/usr/bin/python3 -I -B` using standard-library `ast.parse` on the two changed
  fixture files: parsed successfully as data; no repository imports/execution.
- Bounded streaming tar inspection without extraction: **1,820** regular members,
  **34,733,093** uncompressed bytes; every member matched current source bytes,
  manifest SHA-256 and generated metadata. All four changed runtime inputs were
  present. Payload, manifest and bootstrap-source pins in `preseed.cfg` matched.
- Standard-library JSON inspection: both root inventories still reference the
  prior payload hash `7c40b05bcd73e2be069780a0eac09bb94785979abe62dddc5a31dd157867be3e`.
  `inventory.json` and `inventory-apt.json` are therefore stale relative to this
  payload. `make inventory` was not run; no APT refresh was included in this MOK
  correction.

Fingerprints use sorted repository-relative paths, UTF-8 path plus NUL, followed
by the raw SHA-256 digest for each file. Source and fixture sets are listed above.

```text
changed_sources_sha256=b1126964dfc446c52805c61985c25389d9c4e7189db367d076d62464112b53f5
fixtures_sha256=263138263cff493292fe51192071ddd4cb61852e0ca534ef9dfbfb119145d171
payload.tar.gz_sha256=ebe3ab9e1c0769164903d72ac399bbe18f5835626f3fec7672e4f110d2b5b67b
payload.manifest_sha256=36f31e646a30211bb595c155d4f841a39f396133136934ea2e6b6b2e141a6e39
preseed.cfg_sha256=4172c05ff599dc4928ade50cc9f967ee0e1325011e1f39f7fc3edccd18690fdc
```

## Remaining acceptance gates

No fixture test result or live firmware acceptance is claimed. Future execution
must obey `AGENTS.override.md` and `docs/test-isolation.md`; the earlier testing
stop instruction must also be resolved before test execution resumes.

1. Execute the changed MOK and GRUB fixtures in a reviewed disposable target,
   record the fixture fingerprint, exact target image and package versions, and
   exercise missing-command/configuration, uncertain-write and exclusive-claim
   failures without exposing any real host state.
2. Inspect the target's packaged `00_header`, parse the generated GRUB output
   with the target's native tooling, and verify the one-time fallback actually
   enters MokManager while ordinary menu behavior is preserved.
3. In disposable UEFI firmware, verify reset request creation through the real
   installer/chroot path, both storage-family timings, pending-state readback,
   shim BootNext, fallback boot and AppArmor permissions where loaded.
4. Confirm Reset MOK with the primary username, reboot, establish that prior
   owner-enrolled keys/hashes were removed, enroll the new ESP certificate, and
   verify signed-kernel/module boot. Runtime `MokListRT` can contain vendor trust;
   do not equate it with a pure owner-only inventory.
5. Refresh the paired root inventories before using them to describe this
   payload. Publication of the installer products or verification of served
   bytes remains outside this checkout-only change.
