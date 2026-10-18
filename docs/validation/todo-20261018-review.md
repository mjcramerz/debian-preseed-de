# Current supplied-log review: 18 October 2026

## Scope and evidence

This review concerns the current 95 regular files under `todo/`, including
`todo/.~`. The inventory records each file's byte count, physical line count,
SHA-256 and incident candidate positions in
[todo-20261018-inventory.json](todo-20261018-inventory.json).
The snapshot contains 9,502,020 bytes and 25 empty files. Empty scanner/model
logs do not establish that those workloads ran successfully.

The starting revision was `e0d7684` (`added inventory`). The working tree was
clean before this task's changes. Earlier remediation reports describe earlier
log snapshots; their counts and acceptance statements do not apply to these
current files. The repository guidance names `debian-preseed-de-audit.md`,
which is absent from this checkout.

The supplied installation reports systemd **262-1** and kernel
**7.2.11-x64v3-xanmod1**. These are observations from supplied target logs,
not queries of the development host.

## Confirmed failures and source repairs

### Tailscale: Bubblewrap cannot open its first mount source

`todo/journalctl:867` reports
`bwrap: Can't open source /: Function not implemented` before the supervisor's
timeout at line 977. The constructor failed before handing back its private
mount tree. Increasing the accept timeout would not repair this failure.

The service override set `RestrictSUIDSGID=true`. systemd 262 implements that
restriction by returning `ENOSYS` for `openat2`, because the syscall carries
its flags and mode in an indirect structure. Bubblewrap uses `openat2` for
safe resolution of its mount sources. Its fallback can be omitted when built
with an assumed minimum kernel. The reported error therefore has a concrete
service-policy explanation. See the primary implementations in
[systemd 262 seccomp-util.c](https://github.com/systemd/systemd/blob/v262/src/shared/seccomp-util.c)
and [Bubblewrap 0.13.0 safe_openat.c](https://github.com/containers/bubblewrap/blob/v0.13.0/safe_openat.c).

The repository's `tailscaled.service.d/override.conf.tmpl` now explicitly sets
`RestrictSUIDSGID=no`. The service still uses its existing AppArmor constructor
and daemon profiles, private mount tree, control-group lifecycle, native syscall
architecture, locked personality and other existing restrictions. This removes
the conflicting service-wide SUID/SGID creation filter; it does not add an
AppArmor execution transition or a new daemon capability.

`tailscale-netkit` also checks for constructor exit while waiting for the
handoff connection. A failed constructor now reports its stage and exit status
promptly. One 15-second deadline covers connection, descriptor receipt and final
wait. The separate pinned termination budget, cgroup drain requirement, received
descriptor closure and retained recovery evidence remain in place. A queued
handoff is accepted before checking for an already exited child.

### Tailscale: cleanup rejects its own unreachable route rule

At `todo/journalctl:982`, cleanup reports `unexpected managed route rule;
evidence retained`. Later bootstrap attempts encounter the retained state and
refuse automatic mutation.

The helper invokes `ip -N`. In numeric output, iproute2 represents the
`RTN_UNREACHABLE` rule action as the string `"7"`; the existing comparison
accepted only `"unreachable"`. Cleanup now accepts those two representations
for its exact priority-5191/source/protocol-242 rule. It retains its checks on
table absence, allowed fields, flags, source selector and ownership. Other
actions remain rejected before mutation. The relevant primary implementation
is [iproute2's route-type formatter](https://github.com/iproute2/iproute2/blob/v6.17.0/ip/rtm_map.c),
called by [the rule JSON printer](https://github.com/iproute2/iproute2/blob/v6.17.0/ip/iprule.c).

No retained state from the installed machine was deleted or automatically
retried. This task changes the installer sources and disposable guest fixtures.

### Filen: both confined accounts cannot initialize the pinned runtime

The current AppArmor log contains **180 DENIED events**, grouped into **18
profile/path/operation patterns**: nine per account, ten repetitions each.
They affect only `filen-sync-private` and `filen-sync-offsec` in this snapshot:

- The account's `memory.high` and `memory.max` cgroup files.
- Its own process `statm`.
- Directory reads of `/`, `/usr/lib/` and `/usr/sbin/`.
- Reading `/usr/bin/ldd` and attempting to execute `getconf` and `ldd`.

The matching service logs repeatedly end with `startup-deadline` and
`service-cgroup-cleanup`; extending the deadline would not grant the required
runtime operations.

The profile template now grants only the missing metadata reads and native
`getconf` execution. Its cgroup rule contains the literal escaped systemd slice
name and the selected account's service name. The `/proc` rule retains its
`owner` qualifier. `ldd` is readable as data; its shell script is not executable
under this policy. Shell execution remains explicitly denied.

An isolated run of the actual pinned CLI also exposed a directory-read denial
on `/var/` while resolving its private state directory. The profile now permits
directory reads of `/var/` and `/var/lib/`; it does not grant reads of their
other contents. The native metadata probe covers these public ancestors too.

The pinned watcher's `detect-libc` first invokes `getconf GNU_LIBC_VERSION` and
uses its `ldd` fallback when that fails. See
[detect-libc 1.0.3](https://github.com/lovell/detect-libc/blob/v1.0.3/lib/detect-libc.js)
and [Filen CLI v0.0.36's lockfile](https://github.com/FilenCloudDienste/filen-cli/blob/v0.0.36/bun.lock).
The offline installer now requires a trusted native ELF `getconf` and a valid
glibc response as each actual service UID, with no supplementary groups,
before enabling either service. Missing, failed, timed-out or malformed probes
prevent all enablement.

The staging path remains `scripts/desktop/filen.sh` -> `filen-install.py` ->
root-owned wrapper/modules, rendered account profiles and the existing service
template. Neither account's credentials or sync configuration were changed.

## Other supplied evidence and dispositions

| Evidence | Disposition |
| --- | --- |
| Firstboot exits before the later Tailscale/Filen startup failures; validation reports status 0 and no failed units at that earlier instant. | An early snapshot does not prove later service health. The supplied marker also retains `installation_success=not_yet`. A fresh target acceptance run remains necessary. |
| Journal forwarding becomes `state=on` after rsyslog readiness. | No new forwarding failure is established by this snapshot. Existing source corrections remain intact. |
| 29,724 audit records, correlated into 4,736 event groups. | Failed syscalls include 14 Filen reads and four Filen executions denied with EACCES, 21 stale `rm` unlink attempts returning ENOENT, and one glycin PATH probe of `/usr/local/bin/bwrap` returning ENOENT before the packaged path. These are distinguished from successful security audit records. |
| CrowdSec duplicate grok notices, pending console synchronization, and an initially absent external qBittorrent log. | Existing local API/bouncer verification and acquisition polling are present. The snapshot does not prove remote console approval or discovery after the external volume appears. No enrollment credentials or named collections were altered. |
| Timeshift snapshot creation and a deferred GRUB refresh while its lock is held. | The supplied sequence later completes the refresh. No new deterministic source failure is established. |
| Installer AppArmor reload warnings during the Mullvad package postinst. | Offline package installation must not load host policy. Subsequent target policy observations are separate evidence; no development-host policy was loaded. |
| MOK/firmware warnings and an uncertain prior reset outcome. | Existing uncertainty handling is retained. No firmware mutation or automatic uncertain retry was performed. |
| UCSI `GET_PDOS` error `-5`, unsupported Bluetooth features, spi-nor dummy regulator fallback and other hardware diagnostics. | Hardware/firmware acceptance remains open. The supplied evidence does not establish a narrow repository configuration repair. No speculative device or driver disabling was introduced. |
| Sudo authentication conversation failure. | No evidence justifies weakening authentication. No authorization policy was changed. |
| Native Labwc Xwayland messages; older Waypaper fallback in `todo/.~`. | Existing Xwayland implementation and the Zoom/Discord-only private eligibility boundary are preserved exactly. The older monitor fallback is not proof of a current failing operation. |

## Validation record

Static inspection has parsed the four affected Python files as data and reviewed
the source/caller/staging/profile/service contracts. `git diff --check` has been
run. These activities do not execute the helpers and are not native acceptance.

Runtime verification uses a disposable Forky QEMU guest with its own kernel,
procfs, sysfs, devices, managers, AppArmor policy and package state. The VM uses
TCG, no NIC, no host directory shares, no host management sockets and no physical
device passthrough. Its disks and fixture ISO are private regular files created
for this task. No tests, test discovery, repository helper imports or policy
parsers have run on the development host.

The guest image is Debian's generic-amd64 Forky daily `20261018-2635`, with
systemd 262-1, kernel 7.2.11-1, Python 3.14 and AppArmor 4.1.8-2. Its downloaded
image was checked against the published SHA-512. Fixture Debian packages are
checked against the repository's existing APT snapshot hashes. The pinned Filen
v0.0.36 ELF has SHA-256
`be690d94d3310187dc7b4fe46b3e49becfb327c29ac64d49cfe73252c7c3c04a`.
Tailscale 1.104.1's official static archive has SHA-256
`108d1d96ecf410d305571e173516f27038f870919a9b89c914a167c6d33a4528`.
These digest checks establish byte consistency against the retrieved metadata;
this record does not claim separate OpenPGP verification of those fixture assets.

Earlier guest attempts did not establish acceptance: boot timeouts, a stale
original-partition `fstab`, a missing minimal-boot system bus and a rejected
direct private-bus transient-unit request prevented valid probe results. The
affected attempts are recorded as interrupted or failed harness runs. A QEMU
process exit status of zero alone is not a passing fixture result.

Additional harness corrections were required for a network namespace's own
writable sysfs, idempotent creation of fixture account homes, and
`systemd-run --expand-environment=no` to preserve Perl's literal `$$`. The
earlier failures from these causes are not source-policy acceptance results.
One later combined run exceeded the Tailscale command/activation deadline under
TCG before reaching Bubblewrap. That attempt is not counted as a passing
lifecycle recheck; the subsequent complete lifecycle run below supersedes it.

The intermediate Filen native-keyring failure was a fixture defect. It also
occurred with AppArmor disabled. Adding libraries omitted from the minimal
image did not resolve it; native `ldd` resolved every dependency of the embedded
GNU keyring module, and the plain CLI succeeded as the same unprivileged UID.
A guest syscall trace then showed `openat("/tmp", ... O_DIRECTORY) = EACCES`.
The fixture's `DefaultDependencies=no` changed systemd's private-tmp setup.
The final fixture explicitly uses `RequiresMountsFor=/tmp` to retain the
connected `PrivateTmp=yes` behavior of the real source unit, which has normal
default dependencies. Both confined accounts then passed actual CLI startup.
The repository's Filen service hardening and CLI release were unchanged. See
[systemd 262's private-tmp dependency rules](https://www.freedesktop.org/software/systemd/man/262/systemd.exec.html).

One attempted fixture-ISO serialization failed with `ENOSPC` before any guest
started. Only explicitly named, superseded task-owned ISOs and that incomplete
ISO were removed. Their hashes and all console logs were retained; the final
ISO was then serialized and booted successfully.

### Recorded native results

The latest completed lifecycle run used source-bundle fingerprint
`a19522e464cc81a64f3ff1f58165bf0f1297535a9ee0e56e39e86a7f6fccb545`
and fixture ISO SHA-256
`b44f6f38eea4c70351e9bbdaf6bbf5503b4526daffa3f19ec73120d4d2b675d7`.
That bundle includes the final constructor polling race correction and the
Filen `/var/` ancestor rules.

The final Filen run used the same execution-source bundle and fixture ISO
SHA-256 `ff15eabc66a3f8f2099c6fc81f177c4089d569b7c53a4c390f3ee4caf8130df9`.
Its native probe script has SHA-256
`2f7eb327ea1d0e37db58fb70558bae263ae1f90cb3729888a9b7af7a4eb6b575`.
All **2,102** entries in the bundle's sorted source-hash list were compared
with the final checkout bytes. This fingerprint covers execution sources under
`d-i/forky/` and `tools/`, excluding generated products and private inputs;
generated products are pinned separately below.

| Check | Observed result |
| --- | --- |
| Actual Bubblewrap 0.13.0 under the source service properties with the former `RestrictSUIDSGID=yes`. | Reproduced the exact mount-source `ENOSYS`; the helper promptly reported constructor exit status 1, and cleanup cleared its owned state. |
| Actual Tailscale 1.104.1 under the corrected source service properties. | Two complete starts reached `active/running`; LocalAPI returned `BackendState=NeedsLogin`; both stops returned result `success`, and owned state/rules were absent after each stop. The fixture recorded `NATIVE_SERVICE_LIFECYCLE=success`. |
| Real iproute2 7.2.0-1 IPv4 and IPv6 rules in a separate guest network namespace. | Both rule dumps used action `"7"` for the owned priority-5191 rule. The source setup and cleanup completed with no retained state. This earlier run used source fingerprint `b3e571d5b11b1f21f4a98828e8dc6f6df18c507d6d9270c3dd48abfffa7d40eb`; the tested cleanup comparison is unchanged in the latest bundle. |
| Confined Filen metadata probes as each actual fixture service UID, using all 31 selected identity/hardening properties from the source unit. | Both `private` and `offsec` read the exact cgroup/proc/directory/ldd metadata and successfully executed native `getconf GNU_LIBC_VERSION` (`glibc 2.43`). |
| Actual Filen v0.0.36 `--skip-update --version` in the final connected-private-tmp fixture. | Both confined accounts exited successfully and returned `Filen CLI 0.0.0`, the pinned release's displayed version. Both per-account success markers and final fixture status zero were present. The complete final console log contains no AppArmor DENIED events. No cloud credentials were used. |

The lifecycle fixture preserves the actual source `[Service]` properties,
including AppArmor, `Type=notify` and cgroup ownership, while replacing network
boot ordering with `DefaultDependencies=no` for the minimal guest boot. The
Filen transient-unit probes use the minimal-boot dependency exception together
with the explicit `/tmp` mount requirement described above. The version probe
runs the actual CLI directly in the selected account's service context; it does
not run the credential-consuming continuous-sync wrapper. Its 240-second
fixture runtime limit provides TCG headroom and is not a change to production
startup deadlines or a production performance measurement. These fixture
differences are material when interpreting native runtime behavior.

The earlier combined diagnostic script recorded individual failed CLI results
without failing its process; its final status zero was **not** aggregate Filen
acceptance. The final Filen fixture instead requires each CLI command to succeed,
checks its actual version response and reports both account outcomes explicitly.
All completed native VMs were powered off and their QEMU processes reaped.

Retained console evidence under the private task directory
`/tmp/preseed-incidents-20261018-l8feg37f/`:

| Evidence file | SHA-256 |
| --- | --- |
| `qemu-diagnostic-console.log` (latest Tailscale lifecycle) | `5cd1a712846d9263949f166fed39e4d9e6f43332840976d12ebb84a5eae29659` |
| `qemu-probes-console.log` (native IPv4/IPv6 cleanup) | `e51144b67c91290de43b0a7f9a8c025dce4129a4453f97c8491a09d4ebacbe71` |
| `qemu-filen-connected-console.log` (final confined Filen probes) | `7a47e60dfeaea2aa52b86b77e587a9fa2a0af22599bf245fc90e6302f6383568` |

The guarded unittest suites were **not executed**; their isolation guard is
unchanged. Their added cases cover invalid libc probes, all-or-none service
enablement, numeric/symbolic owned route actions, rejection of foreign rules,
constructor stages/deadlines, descriptor closure, pinned termination uncertainty
and a queued handoff after child exit. These are unexecuted regression fixtures,
distinct from the native operations above. Independent agent startup failed
before work with an encrypted-context hydration error; no child findings or
validation results were counted.

### Final serialization and static consistency

The reviewed pure commands completed successfully:

```text
/usr/bin/make --no-print-directory build 'PYTHON=/usr/bin/python3 -I -S'
/usr/bin/make --no-print-directory inventory 'PYTHON=/usr/bin/python3 -S'
```

Only the three payload/preseed products and root `inventory.json` were
regenerated. No APT refresh occurred; `inventory-apt.json` is unchanged.
The last inventory pass reported 2 sources rescanned, 1,805 cached and 1,817
manifest members. Its facts were unchanged by the last two edits; the existing
generator intentionally retains older negative-discovery cache fingerprints
when inventory facts are unchanged. Those cache fingerprints are not runtime
acceptance evidence.

| Product | Bytes | SHA-256 |
| --- | ---: | --- |
| `d-i/forky/payload.tar.gz` | 26,560,828 | `8853a1062405ea74e3e551c9e2ec4d65440364b3ec22d805bf67a936d8284202` |
| `d-i/forky/payload.manifest` | 223,955 | `f4fd1799b56a2689ab6b50c3af675e7a058a134cc50626d5efa6666adb831a3e` |
| `d-i/forky/preseed.cfg` | 96,407 | `2d6a08b8376d2d54275c68e9f4728978669f5602527b1380b2edf92a865c9562` |
| `inventory.json` | 26,014,589 | `5b11e4a111b35abcb3dcf714b13fcf2c5d1178988c13d9188473805696eabe6c` |

Static data comparison verified all 1,817 archive members, their order, bytes,
source/manifest SHA-256 values and normalized tar metadata (UID/GID/mtime zero,
mode 0644 and empty owner/group names). The expanded payload is 34,696,270
bytes. The generated preseed's archive, manifest and bootstrap-source pins
match current bytes. Its only changes from HEAD are the archive and manifest
pins. The bootstrap source SHA-256 remains
`3483f03497725920fc33b14709674c8326b64ce37cac0271a022571b6d0734e2`.

The four changed Python files parsed as AST data, and `git diff --check` was
clean. A final rehash confirmed all 95 supplied logs are unchanged. Forty-one
non-test source paths selected by the Xwayland, Zoom, Discord, app-bwrap and
shared managed-app names are unchanged from HEAD; the final diff contains no
Xwayland implementation or configuration change. Serialization consistency
does not imply full installation, hardware or authenticated service acceptance.

## Remaining acceptance boundary

The native service construction/cleanup and confined Filen metadata/CLI startup
checks above passed at their stated boundaries. They cannot establish successful
installation or live account operation on the supplied machine. Cloud
authentication, real continuous sync, tailnet transport/SSH/DNS, full installer
boot, GUI launch/shutdown and hardware acceptance remain separate deployment
gates. The hardware/firmware diagnostics and remote console approval described
above are not claimed resolved by source serialization. No deployment or repair
of the running installed machine is claimed.
