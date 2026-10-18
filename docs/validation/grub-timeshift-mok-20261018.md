# GRUB, Timeshift and MOK integration — 18 October 2026

## Status and authority

The source corrections are incorporated in the generated installer products.
**Disposable native acceptance is pending.** `AGENTS.override.md` and
`docs/test-isolation.md` prohibit tests, imports, Perl compilation, native syntax
or policy validators, and installed management helpers on the development host.
No prepared disposable environment was supplied. No EFI variable, host manager,
AppArmor policy, snapshot, mount, package state or boot configuration was changed
on the development host.

Base revision: `20861dbc0b86d6bd4485306cafa4052ff24c669e`. The earlier managed
service fixes and their uncommitted files were preserved. This report records
the additional GRUB/Timeshift/MOK input set; it does not accept the earlier
runtime gates in `managed-services-20261018.md`.

## Findings and narrow corrections

### MOK inventory and ordering

`mokutil --list-enrolled` reads `MokListRT`. Shim adds its built-in vendor
certificate to that runtime list even if there is no owner-enrolled certificate.
The earlier fingerprint-presence check therefore treated the built-in Debian
CA as a reason for a full reset. The supplied firstboot inventory includes that
CA, and the installer log records a reset request at 00:22:19 UTC. The snapshot
alone cannot establish the entire inventory at the time of that earlier request.

The revised check validates full fingerprint fields and excludes the exact
built-in Debian CA display identity. Empty, diagnostic-only, hash-only and
vendor-only inventories skip reset, password resolution and timeout writes.
An owner certificate still requests the complete MOK reset. Malformed inventory
or a failed/timed-out query does not authorize a reset.

The vendor identity was checked against the 930-byte public DER certificate
read from [Debian's CA endpoint](https://dsa.debian.org/secure-boot-ca):

```text
SHA1 display identity: 53610cf81fbd7e0ceb67913c9ef3e794a9633ecb
SHA256: 079646974bce09b1f04da67bd722d1fb0947ae4c4010bccdbba52d5b23cbf1a2
```

This identity comparison grants no trust to a certificate and does not verify
vendor signatures. It recognizes the known Debian CA in the supported boot
chain. A changed vendor CA/boot chain requires renewed inventory review; this
is not a general classifier for every vendor's embedded certificates.

The reset command no longer calls key generation or copies enrollment material.
The shared staging route checks reset before `prepare-dkms` or `prepare` can
publish that material. The pre-pkgsel hook first ensures the already-required
`mokutil` package's command is available; `pkgsel/include` alone does not provide
a command before pkgsel. An installation failure or a missing binary stops
preparation, with the command failure status retained.

The installer claims a private attempt record before firmware access and
publishes one of three bounded results:

| Result | Meaning | Later installer behavior |
|---|---|---|
| `empty` | No owner certificate was reported | Reuse the check; first enrollment remains available without a reset |
| `queued` | The reset request returned success | Reuse the result; require MokManager confirmation before enrollment |
| `unknown` | Interrupted, failed, malformed or uncertain attempt | Retain the record, warn, and do not retry or force an enrollment boot |

The record is under the existing private installer lifecycle state directory,
root-owned mode 0600, singly linked, regular, not a symlink, and at most eight
bytes. Pre-pkgsel and late-command processes share it. Ordinary reset failure
retains the existing nonfatal installation behavior. A queued request is not a
completed firmware reset: physical confirmation and subsequent certificate
enrollment remain necessary. Passwords are supplied through stdin only after
the inventory establishes the need; the redundant bridge environment override
was removed.

The `secure-boot-tool` AppArmor profile now permits the exact inventory paths
and `MokNew`, `MokAuth`, and `MokTimeout` variables used by the reset operation.
It does not grant general EFI-variable writes. No policy was loaded here.

Primary implementation evidence:

- [mokutil 0.7.2 inventory/reset implementation](https://github.com/lcp/mokutil/blob/0.7.2/src/mokutil.c)
  and [runtime-list reader](https://github.com/lcp/mokutil/blob/0.7.2/src/util.c).
  Supplied installer logs report mokutil 0.7.2-2; this is target evidence.
- [shim 16.1 runtime-list construction](https://github.com/rhboot/shim/blob/16.1/mok.c)
  and [MokManager reset confirmation](https://github.com/rhboot/shim/blob/16.1/MokManager.c).
  These sources explain the contract; the native firmware path was not executed.

### Automatic snapshots, cleanup and GRUB refresh

Timeshift's native `--create` path already invokes retention cleanup. Its
cleanup deliberately preserves snapshots with nonempty comments. Every managed
automatic snapshot previously received a comment, exempting it from that
cleanup. The helper now supplies only the existing D/W/M schedule tags and
leaves comments empty. The configured cadence and retention fields are retained.
Native retention combines count and age rules; these fields do not establish
an exact maximum of 24 daily files under the eight-times-daily schedule.

Existing snapshots with comments are not relabelled or deleted by this source
change. A manual comment remains a native retention exemption. There is no
unproven migration that assumes ownership of existing snapshot data.

The duplicated snapshot/refresh lock implementation is now one core-only Perl
module. It validates ancestors, the lock inode, ownership and links, sets
close-on-exec, checks the named inode after locking, and uses a monotonic
deadline that also covers interruptions. Root-owned sticky shared parents keep
their existing modes. Lock files are never unlinked by these helpers.

GRUB refresh takes the same managed snapshot lock before reading the snapshot
tree. An early backup-hook request defers while creation/retention is running.
The service completion hook now uses `ExecStopPost`, so both successful and
failed snapshot jobs request reconciliation. Periodic reconciliation remains
the fallback. Snapshot services explicitly retain a service cgroup and bounded
stop interval. This lock coordinates repository-managed jobs; it does not claim
to control every independent native Timeshift GUI invocation.

GRUB kernel/module compatibility is checked once per snapshot/kernel and reused
for all three boot profiles. This removes repeated filesystem lookups without
changing profile selection or command lines. The menu reader now accepts the
full tag names actually stored in `info.json`, while retaining short aliases
and deduplicating labels. Deferred work is no longer logged as a completed
refresh. Existing validation-before-publication and last-good-menu behavior
remain in place.

The new lock module is staged from the fixed Timeshift module list before timer
enablement. That staging boundary checks every listed module's root ownership,
mode 0644, regular-file/single-link identity and unresolved tokens. GRUB's
AppArmor profile receives only the shared lock path needed for this contract.

The continuing source audit found a publication-status gap at that boundary:
the module loop could inspect an older valid destination after its replacement
failed. A conditional shell caller suppresses `errexit`, so relying on that
setting did not establish failure propagation. The loop now returns the actual
publication status immediately. Timeshift configuration and its storage-family
caller explicitly propagate layout, rendering, module/asset staging and unit
enablement failures, stopping subsequent work. Publication helpers retain their
explicit failure exits and the existing fatal target-layout checks.

Two additional guarded fixture methods specify the affected contracts. One
leaves a valid older `Command.pm` in a private tree, injects status 73 during
publication and requires that status without processing later modules. The
other covers successful configuration and failures at layout, rendering,
module, asset and enablement boundaries, including an explicit conditional
caller. Management actions are fixed stubs; no manager or real target is used.
These seven fixture cases are authored and statically reviewed, **not executed**.

Primary versioned behavior references:

- [Timeshift 25.12.4 create path](https://github.com/linuxmint/timeshift/blob/25.12.4/src/Core/Main.vala).
- [Retention and comment exemption](https://github.com/linuxmint/timeshift/blob/25.12.4/src/Core/SnapshotRepo.vala).
- [Native snapshot metadata](https://github.com/linuxmint/timeshift/blob/25.12.4/src/Core/Snapshot.vala).

Debian's source index identifies 25.12.4-1 for Forky. The installed Timeshift
version and its actual snapshot metadata were not provided as acceptance
evidence. The supplied Timeshift log's `Tagged ... ondemand` message reflects
the native create route's diagnostic; it does not alone prove the final stored
tag list. The native acceptance gate must inspect `info.json`.

## Exact additional changed input paths

```text
d-i/forky/hooks/installer/pre-pkgsel.d/90secure-boot-dkms.sh
d-i/forky/hooks/target/etc/apparmor.d/system-wrappers.tmpl
d-i/forky/hooks/target/etc/systemd/system/timeshift-daily.service
d-i/forky/hooks/target/etc/systemd/system/timeshift-monthly.service
d-i/forky/hooks/target/etc/systemd/system/timeshift-weekly.service
d-i/forky/hooks/target/usr/libexec/install-tools/secure-boot-tool.tmpl
d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/timeshift/TimeshiftManaged/GrubRefresh.pm
d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/timeshift/TimeshiftManaged/Lock.pm
d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/timeshift/TimeshiftManaged/Snapshot.pm
d-i/forky/scripts/late/btrfs-family.sh
d-i/forky/scripts/late/grub.sh
d-i/forky/tests/test_comprehensive_contracts_20261017.py
d-i/forky/tests/test_requested_repairs_20260920.py
```

Sorted `SHA256(file) + two spaces + path + LF` records for those 13 input files:
`b4095976ca51a1fb9ad9ca6103689f446020a113bd91834eb110485f5d7518c1`.
The three generated products and this report are also updated; the earlier
managed-service report receives a pointer to this later snapshot.

## Checks performed

- Source, delegate, installer-stage, service and AppArmor policy review as data.
- Static `ast.parse()` of the two changed Python fixture files, using
  `/usr/bin/python3 -I -B`, without importing repository modules or executing
  embedded Perl/shell fixture code.
- `git diff --check`: clean.
- Reviewed the complete Makefile build recipe, `tools/build.py`, and
  `tools/publication.py`, then ran
  `make --no-print-directory build PYTHON=/usr/bin/python3`.
  The permitted pure serialization completed with 1,817 payload files.
- Bounded standard-library archive/hash inspection: all 1,817 members,
  34,693,320 uncompressed bytes, match current source bytes and manifest hashes;
  normalized member metadata and the preseed payload/source pins agree.

```text
1c0e0adbf45633d910be884282d6cd56ccb5239fd4b4059e68f16a7755705bff  d-i/forky/payload.tar.gz
401612b1fd20c1450219e5087c1afd5efc4b6c5d037ce38e8ca36f10eca57d23  d-i/forky/payload.manifest
94f02375dd2acb7170bf2fa19c77ad213d3136f8529a1cee4aed4c4546f98cf1  d-i/forky/preseed.cfg
```

Earlier serializations were superseded after native-tag and publication-status
corrections; the hashes above identify the final recorded source set. Serialization consistency
does not establish runtime correctness. No validator was interrupted or
bypassed; none was started without the required disposable boundary.

## Required isolated acceptance

1. Execute the two updated fixture modules with packaged Perl/Moo dependencies
   and the target shell. Their management commands use explicit fixture stubs;
   the cached-state metadata fixture uses the real metadata reader only on its
   private files. No such fixture has been executed in this review.
2. On disposable Debian Forky/systemd 262 with its own EFI variables, verify
   vendor-only/empty/hash-only inventory performs no reset/password/timeout
   write, and owner-certificate inventory requests one reset before key
   preparation. Exercise malformed inventory, unavailable/readonly firmware,
   timeout, interruption, cached results and concurrent admission. Confirm
   physical reset precedes enrollment and the new signed system boots, while
   unrelated firmware databases remain unchanged.
3. Exercise both storage-family installation routes and the actual pre-pkgsel
   package timing, including an initially absent mokutil command and package
   failure. Confirm unknown outcomes do not retry or force an enrollment boot.
4. On a disposable Btrfs target, create each scheduled snapshot type and inspect
   final native metadata: correct D/W/M-derived tags, no automatic comment or
   ondemand retention pin. Advance fixture time/age and exceed configured
   retention; verify eligible automatic snapshots are cleaned and manually
   commented/ondemand snapshots remain protected.
5. Exercise concurrent snapshot/cleanup/refresh, lock identity replacement,
   writable and linked lock paths, service timeout/termination, failed snapshot
   work, failed menu validation and unchanged-menu publication. Verify final
   menus reference surviving bootable snapshots and native metadata labels.
   Include native GUI activity; the managed lock alone does not prove it safe.
6. Load and verify the complete candidate AppArmor profiles only in the
   disposable target, then exercise the scoped EFI and shared-lock accesses.
   Run native GRUB validation and boot/recovery checks. Preserve ordinary native
   application launch and private Zoom/Discord launch/shutdown as regressions.
7. Record image identity, actual package/kernel versions, fixture counts/skips,
   these input/artifact fingerprints, and exported acceptance logs. Earlier
   historical reports do not accept this working tree. No performance gains
   beyond the removed repeated work are claimed without measurements.
