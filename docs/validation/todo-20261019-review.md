# October 19 log review and manual sharing toggles

## Evidence and scope

This review starts from clean revision
`1db0a9bf356dd1df2e1650bac14f40547a08ec33`. The supplied `todo/` snapshot
contains 52 regular files, 8,826,357 bytes, including the older October 13
`todo/.~`. [The inventory](todo-20261019-inventory.json) records every file's
size, line count and SHA-256, plus failed audit syscall counts. Logs were read
as data and left unchanged. Earlier reports describe earlier snapshots.

No test, managed-module import, native syntax check, service operation, mount,
package operation or security-policy change was performed against the development
host. Pure `make build` and `make inventory` serialization are the checkout's
explicit exceptions. Native checks use an owned QEMU fixture without a network
interface, shared directories, host services/sockets or device passthrough.

## Repairs and requested behavior

### Filen warning

`todo/filen:1-2` and `todo/journalctl:634-642` report Perl's unreachable-statement
warning. `FilenSync/Daemon.pm` had unconditional list-form `exec` followed by
`POSIX::_exit(127)`. Its exec-failure exit is now the right-hand side of `or`,
matching the shared `Managed::Process` convention. Successful exec still
replaces the child; failed exec still exits 127. Warnings remain enabled.

### Manual Filen synchronization

`todo/journalctl:557-558` shows both instances starting during boot. The
installer enabled them and the template had `WantedBy=multi-user.target`.
Both activation paths are removed. Target Perl/libc checks remain mandatory;
the renamed `validate_services` does not enable/start a service or contact a
running manager. The template is static. This is fresh-install source behavior,
not a live repair of already-enabled target units.

The new `/usr/local/bin/filenmnt` delegates to the existing unprivileged
`labwc-network-sharing` helper:

| Command | Selection and operation |
| --- | --- |
| `filenmnt` | Toggle each configured private/offsec account independently. |
| `filenmnt --private` | Toggle only private. |
| `filenmnt --offsec` | Toggle only offsec. |
| `filenmnt --help` | Usage only, without configuration or manager access. |

Inactive/failed instances start; active instances and automatic-retry waits
stop. Deactivation is rejected as transitional. The helper validates every
selected root-owned public config and unit identity before the first operation,
then verifies each result. Missing default accounts are skipped; explicitly
selecting an absent account fails. Authorization/cancellation/failed or skipped
operations return nonzero and stop the sequence. Earlier completed operations
remain in effect and are reported; no uncertain operation is automatically
retried by the wrapper.

Filen continues to use the existing systemd service, account-separated UIDs,
credentials, AppArmor profiles, bounded cgroup stop and failure retries. No
credentials/private service state enter the desktop helper. The wrapper does
not claim completed authentication or sync merely because a service starts.
Stopping synchronization leaves existing local files accessible; these are not
FUSE mounts.

### NFS toggle

`nfsmnt` now requests `--toggle`, preserving explicit menu Connect/Disconnect
semantics. A disconnected client uses the existing fstab/profile/unit checks,
bounded TCP probe and authorized source start. A mounted client skips the
server probe, requests only the configured source stop, and verifies inactive
state. Busy/failed/skipped unmounts return failure. No force/lazy unmount or
unrelated root/home mount operation is introduced; existing mount propagation
continues to update the home view.

Both terminal toggles hold the same per-user private runtime lock before
observing state. The file is opened without following symlinks and checked for
owner, regular type, one link and mode 0600. Contention fails promptly. The lock
is closed on all paths and never unlinked. This serializes these terminal
commands; separately authorized administrator/menu operations retain systemd's
own job serialization.

### Installation and policy integration

The desktop asset staging installs `filenmnt` mode 0755, even when accounts are
excluded by profile policy, consistently with `nfsmnt`. Existing offline and
firstboot executable/ownership verification lists include it. The
`network-sharing` AppArmor attachment covers the wrapper, only the two public
account configs, and the private runtime lock. Existing Polkit and systemctl
child policy remain the authorization boundary. No passwordless rule, new root
helper or policy access to service credentials was added.

### Browser validation contract

During correlation of the Vivaldi error, source history showed that commit
`05d62b4` deliberately removed Proton VPN from native Vivaldi policy, but
`tools/check_browser_policies.py` and two guarded suites still required the old
removal entry. They now validate the actual three-extension policy and reject
an extra Proton entry. Native browser configuration bytes remain unchanged.
This repairs validation drift; it does not claim a vendor UI repair.

## Complete log disposition

| Evidence | Observed result and disposition |
| --- | --- |
| `filen`, `journalctl:634-649` | Perl warning repaired; service boot activation changed as requested. Both earlier workers reached `sync-initializing` at `journalctl:1064,1067`; that is not proof of completed synchronization. |
| `managed/security/apparmor/apparmor.log` and all audit rotations | No AppArmor DENIED event in the current snapshot. Failed syscalls comprise ENOENT exec/unlink probes and ENOTEMPTY rmdir attempts; no EACCES/EPERM syscall failures are present. Profile-load records are status events. No speculative permission grant was added. |
| `journalctl:859-861,881,892,1048,1053,1060-1063` | Upstream legacy iptables/ip6tables cleanup lookup and pre-creation link lookup remain diagnostic messages. The daemon explicitly selects nftables, reports `firewallmode="nft-forced"`, a STUN endpoint, `udp=true`, Running and completed bootstrap. Legacy binary execution remains denied by existing policy. The prior IPv4 link-local transport defect is absent here. |
| `journalctl:945` | Upstream generic `netfilter=off` warning uses iptables wording. The repository owns nftables policy; changing rule ownership or installing iptables is not a repair. No log filter hides the message. |
| `journalctl:1355-1357` | Control stream EOF is followed one second later by a new dial plan. No failed Tailscale unit or repeated former send-error/rebind loop is recorded in this boot. |
| `managed/security/crowdsec/crowdsec.log:273,292`; `journalctl:1294-1296` | Console synchronization errors occur before/while enrollment awaits external approval. Bootstrap explicitly reports pending-approval, not remote approval. The nftables bouncer is valid and adds 15,000 decisions. No token reset, repeat enrollment or false claim of console approval was made. Remote console acceptance remains external. |
| CrowdSec duplicate grok warnings and absent qBittorrent log | Upstream parser registration notices do not stop the engine. The external app volume/log does not exist before launch; the exact-path acquisition already enables 30-second file-discovery polling. No empty log file or mount directory is manufactured, and named collections remain intact. Native discovery after that external volume appears is not established by the supplied logs. |
| `managed/apps/apps.log:159-162`; `journalctl:1379-1382` | Vivaldi's internal UI requests absent Proton VPN and a NoScript icon not exposed by that extension's manifest. Current native policy manages only uBlock Origin Lite, NoScript and Privacy Badger. No vendor source build, user-profile rewrite, unwanted VPN installation, or extension-security relaxation is justified. Vendor UI behavior remains unresolved. |
| `journalctl:1208-1209` and apps log | Global Labwc Xwayland startup cannot find the binary and continues. Existing task/repository policy excludes Xwayland implementation changes and retains only private Zoom/Discord eligibility. Those files remain unchanged; global Xwayland startup messages are not claimed repaired. |
| `managed/system/usb/usb.log:51-54` | Native USB-C UCSI GET_PDOS errors (-5 / unknown 88) remain a hardware/firmware/kernel investigation. The snapshot establishes no safe source configuration repair. No controller/driver was disabled or speculative firmware change applied. |
| `journalctl:345,350` | Missing first-boot Bluetooth identity is followed by successful IRK generation. No identity file or key was replaced. |
| Foot HUP, netavark idle timeout, fail2ban database creation, skipped conditions and XFS logging policy notices | Expected terminal closure, idle shutdown, first-run initialization or explicit condition/policy behavior; no failed managed operation is shown. |
| nftables accept/drop logs, veth leases, auth sessions, initramfs, timeshift, zram and other nonempty system logs | No new failed rule load, managed veth operation, authentication service, initramfs stage, snapshot or zram operation is recorded. Drops alone do not justify opening ports. |
| Empty scanner/model/storage/fwupd logs | No failure evidence and no claim that the associated check ran or passed. |
| Older `todo/.~` | October 13 Tailscale NeedsMachineAuth requires remote approval; current October 19 bootstrap succeeds. Historical Waypaper falls back to All; current managed configuration uses All/native swaybg and no current recurrence is supplied. Historical global Xwayland messages have the same excluded boundary above. |

## Validation

The final disposable run completed successfully; exact results and fingerprints
are recorded below.
The guarded repository suites are updated but have not been run: the prepared
native VM does not constitute the separate rootless suite image required by
`docs/test-isolation.md`. No guard or test discovery hook was bypassed.

The first QEMU run was interrupted through its owned QMP socket during redundant
package reinstallation. It did not reach acceptance and is not a passing result.
The second run uses the packages already present in the prepared target image.
It passed the 25 isolated fixture cases, native policy parsing, Perl compilation
and static/inactive service checks, but its readiness assertion queried a journal
that the minimal boot had not started. It exited with fixture status 1 and is
not full native acceptance. The final fixture captures service output in each
account's private state directory. This is fixture-only output routing; the
production unit keeps its normal journal behavior.

Remaining deployment gates include actual administrator authentication for these
terminal commands, a real NFS export/unmount and busy-server case, authenticated
Filen synchronization, full installer/boot/desktop regression, external CrowdSec
console approval, vendor browser UI fixes and the recorded USB-C hardware fault.
Native Zoom/Discord private-Xwayland regression is unexecuted and its source
configuration is preserved.

## Generated artifacts and static evidence

Both permitted serialization commands completed successfully:

```text
make --no-print-directory build 'PYTHON=/usr/bin/python3 -I -S'
make --no-print-directory inventory 'PYTHON=/usr/bin/python3 -S'
```

The build contains 1,818 members / 34,705,858 expanded bytes. Every archive
member equals its current source bytes and manifest hash; normalized metadata
and both preseed pins agree. Seven changed Python sources were AST-parsed as
data only. `git diff --check` is clean. The APT metadata snapshot is unchanged.

| Product | SHA-256 |
| --- | --- |
| `d-i/forky/payload.tar.gz` | `a2c01a68a0be63900ec7051499eec62ac9182c9bcf212a4a0686669c415e8952` |
| `d-i/forky/payload.manifest` | `86ad874ecd35273c2630815448feac3143942199ffe481365b205efb93b31590` |
| `d-i/forky/preseed.cfg` | `d76cdb284f29eb0fc6bc044dba7032f3153843af5c5eee0ad0a200ade7d1a009` |
| `inventory.json` | `b6144037e25ab7b98d8fc701e2197e2a218a78c189272653eaac638d01779e9c` |
| `inventory-apt.json` | `96314d9227e24e04aaf8577258cbc7c8bc575fe36cb855b49dda89c9ffc83318` |

Final source-set fingerprint (2,103 installer/runtime/tool/test files):

`42c39581b84ef3579e656af9a94928d7a384640cb480bc10c987180f88c846d5`.

The final QEMU source copy includes the browser-checker corrections. The
previous source copy had fingerprint
`16864e3f61ef179eb80e27cc8f54f756454b21218516d0f0c0fdf0e808622268`; only the
browser checker and its two guarded test files changed between copies, and all
1,818 installation inputs remained byte-identical.

Independent sidecars failed during encrypted-context initialization. Their
proposed reviews are not counted as completed review or validation.

## Completed disposable native run

The final `qemu3-console.log` contains every required marker, QEMU exit was zero,
the guest powered off, and the owning process was reaped. Native source copying
and post-run inspection match all 2,103 final source hashes, not only the files
exercised by the fixture.

| Check | Observed result |
| --- | --- |
| Isolated source-level fixtures | 25 cases pass: account/default/flag/mixed-state choices, prevalidation, disabled accounts, authorization failure, auto-restart stop, NFS mount/unmount/failed/skipped/transitional state, no TCP on disconnect, lock contention/release/unsafe mode/symlink, and wrapper help/invalid args. Service/TCP replies and desktop identity are mocked in these cases. |
| Native policy/parser | Packaged AppArmor parser accepts the updated Network Sharing policy. Both actual Filen account policies load in enforce mode in the guest. |
| Native target Perl | Final wrapper compiles under both actual non-root service UIDs with no unreachable-statement warning. The actual installer `validate_services` runs both target Perl and ELF getconf checks and creates no boot enablement links. |
| Native static/manual lifecycle | Both instances report static/inactive before use. The actual supervisor, systemd credentials, source Service hardening and loaded profiles run both accounts concurrently and reach the fixture initializing message. Six actual manager start/stop operations exercise both, individual selection and mixed-state toggling. Both final stops report Result=success. |
| Native audit output | Full final kernel/console evidence contains zero AppArmor DENIED records and no reported Perl warning. |

The guest is the previously prepared Debian Forky generic-amd64 daily image
`20261018-2635`, kernel `7.2.11+deb14-amd64` / package `7.2.11-1`, systemd
`262-1`, AppArmor `4.1.8-2`, Python `3.14.7-3`, Perl `5.42.3-1`, Moo
`2.005005-1`, and MooX::StrictConstructor `0.013-1`. The retained vendor-image
SHA-512 record is
`4c076e27b5da2d90dc64ec3ac398cc7703c6cc2bcd07e068c291b832153bb260f4712abb4a440b5d62b545db9be4e4a1de7289726d493643b87800f1ce431687`.
Its original cloud image was checked in the earlier image-preparation work;
this run reuses that owned image with a disposable snapshot overlay.

The native harness replaces only unrelated boot Unit dependencies and output
routing, supplies fake cloud/TOTP programs and fake credentials inside the VM,
and mocks the desktop identity while root invokes the real guest manager.
Production Polkit prompts, real NFS operations and real Filen cloud/TOTP
acceptance are **not** established. The complete source Service section's
security/lifecycle settings are retained. No network interface, host filesystem
share, host manager socket or host device is exposed to the guest.

Private fixture/evidence directory:
`/tmp/preseed-filen-toggle-20261019-h8hnlk8h/`. The script runs as
`/usr/bin/python3 -I -B /mnt/preseed-fixture/native-toggle.py` inside that VM.
QEMU argv and evidence metadata are retained there.

| Evidence | SHA-256 |
| --- | --- |
| `bundle/native-toggle.py` | `5955f3d0e780578d2df275cebe47b487c2d40de03dadbf4e987c146fa648c70a` |
| `bundle/guest-bootstrap2.sh` | `1614a3d9806888909423ee2a5b4d9fbac40f5e7e51b2b1fb1c79d15da2a7e3e6` |
| `bundle/source.tar` | `ab47df6cbc74912ee1b2cd8ce0742d0e1b925b1ca3d9f47154f7bd908e49b123` |
| `fixture3.iso` | `dca571d30599c2d097278bd47fa1b941764a01bd3dc89a61bb39b4cb34be462f` |
| `qemu-console.log` | `1048553d167179bb50d7bcd9f878840c4827ac60c9e2d6e75b549df611377d41` |
| `qemu2-console.log` | `c45f2de4a4883fe55eeb1932287da288a7920c087ff4f97fc92b73213b1bfc6c` |
| `qemu3-console.log` | `79ccd0ac8722d5f836581b96e0fbd2244ac71c66e21eeb97b8bb1e503e1622b4` |
| `qemu3-argv.json` | `37e8ad2ca39838b8ab2f8aad8f04fd88011c641773cc61f33c50bd94f4e93e5e` |

## Exact changed paths

```text
d-i/forky/hooks/target/etc/apparmor.d/network-sharing
d-i/forky/hooks/target/etc/systemd/system/filen-sync@.service.tmpl
d-i/forky/hooks/target/usr/local/bin/filenmnt
d-i/forky/hooks/target/usr/local/bin/labwc-network-sharing
d-i/forky/hooks/target/usr/local/bin/nfsmnt
d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/filen/FilenSync/Daemon.pm
d-i/forky/payload.manifest
d-i/forky/payload.tar.gz
d-i/forky/preseed.cfg
d-i/forky/scripts/desktop/components/target-assets.sh
d-i/forky/scripts/desktop/filen-install.py
d-i/forky/scripts/desktop/verify.sh.tmpl
d-i/forky/scripts/firstboot/04-validation.sh.tmpl
d-i/forky/tests/test_browser_repository.py
d-i/forky/tests/test_filen_sync_20261017.py
d-i/forky/tests/test_network_sharing.py
d-i/forky/tests/test_security_refactor.py
docs/network-sharing.md
docs/sharing-filen.md
docs/validation/todo-20261019-inventory.json
docs/validation/todo-20261019-review.md
inventory.json
tools/check_browser_policies.py
```

Final static mode inspection caught the three new files inheriting mode 0600.
Only those owned source/document files were set to repository mode 0644; all
source/product/log hashes still agree. Payload metadata was already normalized
to 0644, and installed wrapper staging remains 0755.
