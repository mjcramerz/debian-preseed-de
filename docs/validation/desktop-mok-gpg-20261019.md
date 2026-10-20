# MOK boot, primary GPG launch gate and desktop aliases — 19 October 2026

## Final checkout status

The source changes and all three installer products have been updated. **All
test execution stopped at the user's instruction after the reported host veth
failure.** No further VM, fixture, policy-parser, service, GUI, network or firmware
operations were run. Subsequent work was source editing, static inspection and
the explicitly permitted serialization-only build. The reported host failure
was not investigated or repaired as part of this source change.

Base revision: `f5d49636569baf5ae22cf6683ff449bfc28198a9`, branch `mcr/main`,
with uncommitted changes preserved. Target: Debian Forky, systemd 262 and Python
3.14. No software was compiled from source, no installer release was published,
and no live deployment is claimed. The Xwayland implementation, configuration
and Zoom/Discord-only eligibility remain unchanged.

This report supersedes the behavior and product fingerprints in the earlier
[MOK report](mok-reset-enrollment-20261019.md). The
[journal/Tailscale report](journal-tailscale-20261019.md) retains the diagnosis
of the supplied logs; its generated-product hashes describe an earlier snapshot.

## MOK request and boot changes

- Reset is attempted **in each d-i late storage-family path immediately after
  GRUB configuration generation**, after GRUB, shim, MokManager, kernel/initrd
  and `grub.cfg` are installed. It no longer depends on the desktop role’s
  later hook. Pre-pkgsel prepares DKMS signing material; it does not queue the
  firmware reset.
- No MOK inventory command is used as a gate. `mokutil --reset` is called for
  every fresh installation regardless of whether certificates are present,
  absent, vendor-only, malformed or unreportable. The selected Secure Boot
  support package set already includes mokutil and efibootmgr.
- The reset password is **always the primary account username**. A legacy
  password override is ignored. The validated value is supplied twice on stdin,
  never in arguments or diagnostics.
- Command success must be followed by a direct, nonempty `MokAuth` variable of
  the supported size and absence of `MokNew`, including dangling symlinks.
  `--list-new` being empty does not count as confirmation. `mokutil --timeout -1`
  requests immediate entry to the first management menu without its additional
  keypress countdown; a timeout-setting error does not discard a queued reset.
- Private per-install state claims `unknown` before the one reset attempt and
  records `queued` only after confirmation. Unknown/interrupted outcomes are
  not retried automatically. Missing EFI access, command errors, timeouts,
  optional preflight exits and boot-queue failures warn and continue installation
  without writing the mandatory first-failure sentinel.
- The installer mounts efivarfs when necessary and verifies the target's actual
  efivarfs filesystem type. The shim BootNext handoff and GRUB one-shot fallback
  are attempted independently after rechecking the pending request.
- BootNext matches the selected disk, kernel partition number, GPT partition
  UUID, active entry and exact shim loader path. The partition number comes
  from the selected device's sysfs identity because lsblk's PARTN can be empty
  in early boot. Both libefivar display forms, `File(path)` and a bare EFI path,
  are accepted with an exact final path match. Creation uses `--create-only`;
  persistent BootOrder is preserved and BootNext is read back.
- The GRUB MOK entry searches the selected ESP by UUID, uses its public
  enrollment certificate, switches to the EFI console, chainloads MokManager
  and executes `boot` explicitly. It restores gfxterm if the EFI application
  returns. No informational pause precedes the handoff. MokManager itself owns
  its firmware text mode and still requires reset/enrollment confirmation.

`mokutil --reset` queues deletion of owner-enrolled certificates and hashes;
MokManager applies it after physical confirmation using the primary username.
It does not delete shim's embedded vendor CA, firmware PK/KEK/db/dbx or the
separate MOK blacklist. Reset and enrollment remain separate so an import
request cannot overwrite the pending reset. After confirming Reset MOK and
rebooting, enrollment uses the public `/MOK Enrollment/MOK.der` on the ESP.
See [mokutil 0.7.2](https://github.com/lcp/mokutil/blob/0.7.2/src/mokutil.c) and
[MokManager 16.1](https://github.com/rhboot/shim/blob/16.1/MokManager.c).

## Primary GPG launch gate

The earlier KWallet/Secret Service readiness check establishes API availability;
it does not prove that the primary private key has been unlocked. Applications
can initialize before they request a stored secret. The new gate requires a
real decryption before a managed application payload starts.

The installer provisions a random challenge encrypted to the exact primary
OpenPGP fingerprint. A root-owned policy pins the account, home, fingerprint,
ciphertext and plaintext SHA-256. No private passphrase or plaintext challenge
is stored in the policy. Provisioning is wired into the existing GPG bootstrap,
and the active installer path checks the policy after account setup and before
desktop service enablement.

Every gated launch decrypts the challenge through trusted `/usr/bin/gpg`, checks
the primary fingerprint from `DECRYPTION_KEY`, requires `DECRYPTION_OKAY` and
compares the exact plaintext digest. No writable readiness/success marker grants
access. A cached key in the existing gpg-agent can satisfy a subsequent launch;
a locked key prompts through pinentry. Cancellation, unavailable state, failed
proof and timeout deny the launch with distinct diagnostics.

The proof runs in a uniquely named, bounded transient user service attached to
the existing session target. The service requires the shared gpg-agent socket;
GPG uses `--no-autostart`, keeping the shared agent outside the short-lived proof
cgroup. Input, output, status, runtime and cleanup are bounded. The dedicated
AppArmor profile grants the helper its fixed policy, GnuPG state and local
session socket access. No new firewall or network privilege is added.

Coverage includes all 25 central managed application policies, generic GUI
launches, configured app-veth routes, retained vendor desktop actions, Code URL
handling, ChatGPT's delegate and the dedicated qBittorrent path before storage
preparation. Terminals, key-management tools and the explicit desktop/recovery
controls remain available to unlock or repair the session. The existing SSH
askpass path already decrypts its GPG-sealed secret and remains unchanged.

This is a managed-launch policy. It is not a same-UID executable access-control
boundary: a user who runs an underlying vendor executable directly can bypass
desktop wrappers. The new code does not claim otherwise.

## Code desktop entries and Tailscale

`code.desktop` is the visible canonical Code ID.
`com.microsoft.VSCode.desktop` remains a managed `NoDisplay=true` compatibility
alias so pinned IDs and associations continue to resolve. The Code URL handler
is also hidden and uses the managed `--open-url` route. Retained vendor actions
are routed through managed dispatch; D-Bus activation cannot bypass rewritten
Exec commands.

The Tailscale changes retain native nftables selection. No iptables/ip6tables
package, compatibility backend or execution grant was added. Only exact benign
startup cleanup/shutdown diagnostics are filtered. The HTTP 409 superseded-map
message remains visible; the supplied log shows native recovery to Running.
No host veth, route or service operation was part of these source edits.

## Static and serialization evidence for the final tree

The reviewed build command was invoked through a bounded subprocess argument
array with a minimal environment:

```text
/usr/bin/make --no-print-directory build 'PYTHON=/usr/bin/python3 -I'
```

It completed with 1,819 payload members. Before/after SHA-256 snapshots of 2,361
tracked/untracked nonproduct files agreed: only the three authorized products
changed during generation. Static archive inspection, without extraction,
matched all 1,819 members (34,729,703 uncompressed bytes) against current source
bytes and manifest hashes, checked regular-file metadata and agreed with the
preseed archive, manifest and bootstrap-source pins.

Static `ast.parse` inspected 13 changed Python files and the inline target
runtime verifier without importing or executing repository modules. `git diff
--check` was clean. These are source/data inspections, not runtime acceptance.

Fingerprints below use SHA-256. The changed-runtime and fixture fingerprints
hash each sorted full repository-relative path, NUL, then its raw file digest.

```text
changed_runtime_paths=21
changed_runtime_sha256=d30822d1ceff2a52dcecd5ed1c2e972c1ebc1d6049ec31ad0bcaaf1516148788
fixtures_sha256=615e6dad41b0a958d644bfd500cf7e57ed9e25c79ce70e7d6b414578e382a6e1
payload.tar.gz_sha256=29586036bd43389e8e34a6e4181c76e2e5a4e4dbb609f9fe38e4f7513f132527
payload.manifest_sha256=0116be68e8b513738e5159d159ccf82fd5e7fa3d12f6f318dfa8f27b1673d344
preseed.cfg_sha256=be82be255ff5a4a93bfeba12ad7dac3f8cd0f0d6993dd72a4ece644880519839
```

## Earlier VM observations and limits

Before the stop instruction, native operations ran in a disposable TCG VM with
its own kernel, virtual disk/ESP, writable virtual NVRAM, procfs/sysfs/devices
and managers, no host shares/sockets/device passthrough and `-nic none`. Package
bytes were checked against a signed Debian Release and Packages index inside
the VM before unpacking, without maintainer scripts. This records the configured
boundary; it does not establish the cause of the reported host veth failure.

Observed target versions included systemd 262-1, Python 3.14.7-3, kernel
7.2.11+deb14-amd64, util-linux 2.42.4-1, mokutil 0.7.2-2, efibootmgr 18-4.1,
libefivar 39-2+b2, shim 16.1 and GnuPG 2.4.9-8. Secure Boot was disabled in OVMF
Setup Mode; no Secure Boot enforcement result is claimed.

Retained native evidence is under the private fixture directory
`/tmp/preseed-mok-final-20261019-xw56bwez`. The phase1g input manifest identifies
the exact copied sources and native fixture scripts; its SHA-256 is
`5e15e0c17ecdc025971ed86547a3f12f34362700c35038bb18af85f876396b43`.
The recorded phase1g QEMU argument array has SHA-256
`0c13b6f6ce1a875761d8609a2e61b9fc2ab5e570f816a7fdf65142ffdf4fc49b`.
The reviewed base artifacts in `/tmp/preseed-incidents-20261018-l8feg37f` had
these SHA-256 identities before use:

```text
rootfs.ext4=5a5d0eebaf4be1f03f8335c53064f53781a088f90daf9bc996a01b5480a51036
vmlinuz=216e0fcf65c969ad1760d2be22b3e0af58c5f6c3418ad80bd38e8af9f6997b77
fast-initrd.img=94f08cc532c697a314d9b86a708b1f4ccaeaf78b488c696a6c02e2847bbdab1f
```

Earlier logs confirmed a real queued reset with 176-byte MokAuth and no MokNew,
15 synthetic password/nonfatal-handoff cases, and eight real-GnuPG cases using
a synthetic key, cancellation pinentry and fixture Wayland socket. Those GPG
cases covered locked/cancelled, unlocked, wrong primary identity, wrong digest,
unsafe policy permissions, symlink policy, relocking and missing policy.

The native BootNext run failed and exposed two source defects: empty PARTN and
the bare-path libefivar output. Both source fixes are incorporated. **The final
bare-path correction was not executed after testing stopped.** Later GPG
diagnostic refinements and the active post-account verifier also have static
inspection only. There is no final-tree native pass claim. Sidecar review agents
failed initialization; they supplied no independent review evidence.

Not executed: guarded repository suites; final BootNext/readback and BootOrder
regression; MokManager reset/password confirmation, existing-owner-key removal
and subsequent enrollment; first-Enter GRUB/display behavior on hardware or
arm64; final user-systemd/pinentry/AppArmor integration; native application and
private Zoom/Discord lifecycle regression; final launcher/dock GUI behavior;
complete fresh-install acceptance. These remain explicit deployment limits.

## Exact changed paths

Runtime inputs, relative to `d-i/forky/`:

```text
hooks/installer/pre-pkgsel.d/90secure-boot-dkms.sh
hooks/target/etc/apparmor.d/desktop-wrappers.tmpl
hooks/target/etc/apparmor.d/system-wrappers.tmpl
hooks/target/etc/grub.d/40_custom.tmpl
hooks/target/etc/systemd/system/tailscaled.service.d/override.conf.tmpl
hooks/target/usr/libexec/install-tools/secure-boot-tool.tmpl
hooks/target/usr/local/bin/labwc-qbittorrent
hooks/target/usr/local/bin/labwc-sync-application-launchers.tmpl
hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/cli.py
hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/generic.py
hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/runtime.py
hooks/target/usr/local/libexec/labwc-primary-gpg
hooks/target/usr/local/share/grub-profiles/mokmenu.cfg.in.tmpl
scripts/desktop/components/gpg-bootstrap.sh
scripts/desktop/components/target-assets.sh
scripts/desktop/labwc.sh
scripts/desktop/verify.sh.tmpl
scripts/late/btrfs-family.sh
scripts/late/desktop.sh
scripts/late/f2fs-family.sh
scripts/late/grub.sh
```

Authored/updated repository fixtures, not executed:

```text
d-i/forky/tests/fixtures/contracts/grub-split.json
d-i/forky/tests/test_comprehensive_contracts_20261017.py
d-i/forky/tests/test_hardware_restore.py
d-i/forky/tests/test_installation_fixes_20260912.py
d-i/forky/tests/test_installer_hardening.py
d-i/forky/tests/test_installer_shell_boundaries.py
d-i/forky/tests/test_native_contracts_20260923.py
d-i/forky/tests/test_primary_gpg_launch_gate.py
```

Generated: `d-i/forky/payload.tar.gz`, `d-i/forky/payload.manifest`,
`d-i/forky/preseed.cfg`. Documentation: this report,
`docs/validation/mok-reset-enrollment-20261019.md`,
`docs/validation/journal-tailscale-20261019.md` and
`docs/validation/grub-timeshift-mok-20261018.md`.
