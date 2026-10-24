# Storage reporting and fstab source repair — 2026-10-24

## Scope and revision

This is source inspection and serialization evidence for an uncommitted working
tree based on Git revision `e0e3bbb9fe8e6937b55bc737ba75ed2494721a24`.
The payload manifest hash below fingerprints the complete packaged source
snapshot; fixture hashes identify the unexecuted regression sources separately.

No test, validation runner, discovery import, shell syntax checker, policy parser,
mount operation, host management helper, service operation or disposable
execution environment was used. The installed machine was not modified.

## Supplied incident evidence

| Evidence | Observation |
| --- | --- |
| `todo/journalctl:1442` through `:1444` | The managed NFS client share was mounted at 00:31:04 in the supplied log. |
| `todo/managed/system/kernel.log:1088` | At 00:45:47 the kernel reported that NFS server `192.168.50.82` was not responding and had timed out. |
| `todo/managed/system/kernel.log:1121` through `:1141` | Repeated timeouts continued across the period containing the reported `df` attempts. |
| `todo/managed/security/audit/auditd.log:2019` and `:2020` | `df -h` successfully executed under `desktop-terminal`. This records exec success, not command completion. |
| `todo/managed/security/audit/auditd.log:4149` and `:4150` | The sudo attempt also executed `df -h` as root under `desktop-terminal`. |
| `todo/managed/security/audit/auditd.log:8094` and `:8095` | The storage click launched `ncdu /` as the desktop user under `desktop-terminal`. |
| `todo/managed/system/kernel.log:1` | The recorded kernel is `7.2.12-x64v3-xanmod1`. |

The selected source profile `hosts/profiles/btrfs-de-flex-duo.env` enables the
client with that server address. Shared mount options in
`hosts/installer/hosting.env` include `hard`, and the NFS settings validator
requires it. GNU df includes remote mounts by default. An unavailable hard NFS
mount can therefore block an all-filesystem capacity query. The unrestricted
ncdu scan can also enter that mount, including its propagated home view.

That is the evidence-backed explanation for these reporting paths becoming
unresponsive. The logs do not contain a stack trace of the particular df
process, or establish why the remote server became unavailable. No corresponding
df/ncdu denial was found in the supplied AppArmor log. This is not proof about
all historical loaded policies.

The ncdu warning about `/var/lib/apt/lists/partial` is consistent with ordinary
DAC restrictions on a desktop user's recursive root scan. Directory scanning is
unnecessary for reporting filesystem capacity.

References: [GNU df documentation](https://www.gnu.org/s/coreutils/manual/html_node/df-invocation.html),
[GNU df implementation](https://github.com/coreutils/coreutils/blob/master/src/df.c),
[NFS mount semantics](https://www.man7.org/linux/man-pages/man5/nfs.5.html),
[findmnt options](https://www.man7.org/linux/man-pages/man8/findmnt.8.html).
These explain the flags and behavior; they do not identify the installed
coreutils or util-linux package versions.

## Implemented source behavior

- Managed interactive Bash and Zsh now alias `df` to `df --local`. Thus the
  ordinary interactive `df -h` report avoids remote mounts. Explicit
  `/usr/bin/df`, scripts and `sudo df` keep their upstream behavior; an explicit
  remote pathname can still require a remote operation.
- Both Waybar disk buttons open `labwc-system-action storage-overview`, replacing
  the recursive `ncdu /` action. The existing terminal action keeps the result
  visible until Enter and preserves the result status.
- The desktop storage action uses an unprivileged shared report. The existing
  privileged storage adapter delegates to the same report for consistent behavior.
- The report prints local capacity first with `df --local -hT`, a block-device
  inventory without filesystem-capacity columns, and a kernel mount inventory
  with path canonicalization disabled. It labels remote capacity as excluded
  and does not traverse, mount, unmount or repair shares.
- Each of the three report commands uses a 10-second timeout and a separate
  two-second forced-termination interval. Failures, including statuses 124 and
  137, propagate without retry. Native termination has not been exercised.
- The report has an AppArmor attachment and explicit transitions from both
  system-action profiles. Its policy grants read-only mount, sysfs and udev
  metadata and its four command delegates. No network, device-content, state
  write or privilege-delegation grant was added. The existing general terminal
  inheritance policy remains intact.
- The active asset-staging path checks the report's root ownership, exact 0755
  mode, regular single-link identity, bounded size, unresolved tokens, and the
  four packaged delegates' ownership, executable modes and parent directories.
  This check reads source and metadata without invoking the storage report.
  It was authored and inspected, not executed in this session.
- Both storage-family fstab generators now emit named comment sections.
  The initial AWK formatter and later network-sharing formatter omit blank
  rows and align fields within each section. Long remote mount options do not
  widen local sections. Mount fields, record order, escapes, options and inline
  comments are preserved. The sharing bind mounts and remote NFS entry have
  separate headings.
- The NFS `hard` mount policy, existing private Zoom/Discord Xwayland behavior,
  and test isolation guards were not changed.

### Fstab section order

Btrfs layouts use kernel/boot, system subvolumes, home subvolumes,
application/data, temporary storage/logs, persistent journal, sharing bind
mounts and optional remote NFS sections. F2FS layouts use kernel/boot, local
filesystems, temporary storage/logs, persistent journal, sharing bind mounts
and optional remote NFS sections. Comment headings separate contiguous rows;
there are no generated empty spacer rows.

## Exact changed paths

### Reporting and installation

- `d-i/forky/hooks/target/etc/skel-desktop/.bash_aliases`
- `d-i/forky/hooks/target/etc/skel-desktop/.zsh_aliases`
- `d-i/forky/hooks/target/etc/skel-desktop/.config/waybar/config.tmpl`
- `d-i/forky/hooks/target/usr/local/bin/labwc-system-action.tmpl`
- `d-i/forky/hooks/target/usr/local/libexec/labwc-system-action-root`
- `d-i/forky/hooks/target/usr/local/libexec/labwc-storage-report`
- `d-i/forky/hooks/target/etc/apparmor.d/desktop-wrappers.tmpl`
- `d-i/forky/scripts/desktop/components/target-assets.sh`
- `d-i/forky/scripts/desktop/verify.sh.tmpl`

### Fstab generation

- `d-i/forky/scripts/late/btrfs-family.sh`
- `d-i/forky/scripts/late/f2fs-family.sh`
- `d-i/forky/scripts/late/target-assets.sh`
- `d-i/forky/scripts/late/network-sharing.py`

### Fixtures, generated products and this record

- `d-i/forky/tests/test_storage_report_20261024.py`
- `d-i/forky/tests/test_network_sharing.py`
- `d-i/forky/tests/test_security_hardening_20260924.py`
- `d-i/forky/tests/test_log_launchers_20260915_r3.py`
- `d-i/forky/payload.tar.gz`
- `d-i/forky/payload.manifest`
- `d-i/forky/preseed.cfg`
- `docs/validation/storage-report-fstab-20261024.md`

## Checks actually performed

1. Read the applicable repository instructions, incident logs, callers,
   renderers, staging/policy sources, Makefile, `tools/build.py` and its sole
   local import `tools/publication.py` as data.
2. `git diff --check` completed with no whitespace errors.
3. One-off `/usr/bin/python3 -I -S -B -` commands used standard-library
   `ast.parse` on the five changed Python modules and three embedded Python
   snippets (the staging contract, existing desktop contract and private
   fixture stub). Repository modules and fixtures were not imported or executed.
4. Ran the explicitly permitted generation command:
   `env -i PATH=/usr/bin:/bin /usr/bin/make --no-print-directory build 'PYTHON=/usr/bin/python3 -I -S'`.
   It reported `built 1839 payload files`. After the final whitespace-only
   formatter edge case was corrected, the same generation command was rerun.
5. A one-off standard-library reader compared all 1839 archive
   members (34,949,678 source bytes) to current source bytes,
   reconstructed and compared the manifest, checked completeness of the
   packaged source inventory, and checked current archive/manifest/bootstrap
   pins in preseed. It read members without extracting them, with limits of
   10,000 members, 16 MiB per member and 128 MiB aggregate.
6. Read both root JSON inventory payload pins as data. Both still pin
   `f5ddfddf6f195db43291a9b6fc468b248813c00031c70ff5f2e5774927f69558`,
   so `inventory.json` and `inventory-apt.json` are stale for this payload.
   Inventory generation and public APT acquisition were not performed.

### Generated artifact SHA-256

| Artifact | SHA-256 |
| --- | --- |
| `d-i/forky/payload.manifest` | `91d7add35f5d5889d165995b44dd35ded78cf92126e05982f6d82d436402a616` |
| `d-i/forky/payload.tar.gz` | `3d1fd825404c3ebf2673e2e4b495695acbf1222bfa0f3dccd15d771acd138e46` |
| `d-i/forky/preseed.cfg` | `315ad63052e46ef92e24e24965e99df7ef501e05ee53b367a050b7db92859050` |

### Unexecuted fixture SHA-256

| Fixture | SHA-256 |
| --- | --- |
| `d-i/forky/tests/test_log_launchers_20260915_r3.py` | `151f02b86d0eeed14088351d55839b61200dc390bca9d93dad2b5b562cd5cdbb` |
| `d-i/forky/tests/test_network_sharing.py` | `5de79bcb3ce019d975e1e79be5e8acc203a07427f9f2855ce4d3c381746353a7` |
| `d-i/forky/tests/test_security_hardening_20260924.py` | `877b8ffb74d3842544ada3673ea32acc03574b9ad0e546204e42576853baa811` |
| `d-i/forky/tests/test_storage_report_20261024.py` | `bfed9e1b5b2f35b62fd6d8dccb9bf05ac54c1d0275789e4f2f7da57b5ec4d1ce` |

The new fixture source contains seven methods covering synthetic staging
metadata rejection, private storage delegates, local-only query selection,
missing delegates, malformed arguments, failure/timeout propagation and
desktop/root adapters. The timeout outcomes are mocked statuses, not evidence
of native signal delivery or worker cleanup. Fstab fixture changes cover
semantic/escape/comment preservation, section-local alignment, repeat
formatting, blank input, and preservation of previous file bytes and mode on
malformed or comments-only input. No fixture was run.

## Verification and deployment limits

The installation target remains Debian Forky with systemd 262 as specified by
repository guidance. No target image identity or installed package inventory
was supplied for this source snapshot; coreutils, util-linux and AppArmor
runtime versions were not inferred from the development host.

Static parsing and archive consistency establish source/serialization facts.
They do not establish loaded AppArmor acceptance, native GUI launch, boot-time
mount behavior, NFS recovery, signal cleanup, hardware behavior or deployment.
Neither the installed fstab nor the user's current shell/Waybar configuration
was changed. Existing installations do not acquire these changes from a payload
rebuild alone. No host repair, service reload, unmount or policy load was attempted.
The remote NFS server's availability remains unresolved by the supplied evidence.

The independent sidecar log/review agents failed at startup with an encrypted
content hydration error; their findings were not used. The root agent completed
the source review and artifact comparisons recorded above.

