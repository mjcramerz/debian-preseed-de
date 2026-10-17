# Comprehensive audit implementation review — 17 October 2026

## Release status

This is the current implementation ledger for
`debian-preseed-de-comprehensive-audit.md`. Every numbered work package was read
and compared with its implementation and relevant callers. **This is not release
approval and does not close all 22 acceptance gates.** Source repairs, authored
fixtures, serialization and native acceptance are separate evidence categories.

The target remains Debian Forky with systemd 262. No prepared disposable image or
installed target was supplied. Following `AGENTS.override.md` and
`docs/test-isolation.md`, no tests, test discovery, repository imports, Perl BEGIN
blocks, shell syntax runners, native policy validators, package probes or host
management helpers were executed. Only source/diff inspection, standard-library
parsing as data and the reviewed pure serialization path are permitted here.

The user's exclusions take precedence over audit recommendations: retain the
current private Xwayland implementation and exactly the Zoom/Discord eligibility
boundary; leave NVIDIA legacy and CUDA legacy unchanged. The user's later MOK
instruction also supersedes section 3's certificate-specific deletion proposal:
every installation checks for enrolled MOK certificates and attempts a full reset
only if a certificate is reported. Query/reset failure warns and continues
installation. The requested
`ntfs_drivers=ntfs,ntfs3` ordering is preserved. The earlier audit file's deletion
was already present when this continuation started and was not reversed.

## Repairs in this continuation

Paths below are relative to `d-i/forky` unless stated otherwise.

| Contract | Implementation and integration |
|---|---|
| Kernel publication | `hooks/target/usr/libexec/install-tools/secure-boot-tool.tmpl` verifies against the configured MOK, signs a private candidate, verifies that candidate, synchronizes a sibling replacement, then renames it over the live kernel. Signer display names no longer bypass signing. Initramfs sidecars are verified and published through a sibling replacement too. A failed directory synchronization reports uncertainty and retains the kernel's private previous copy. |
| Module expansion | `hooks/target/usr/libexec/install-tools/verify-module-signature.py --decompress` pins the compressed input descriptor, limits input and expanded output to 512 MiB, uses fixed packaged decompressors, and bounds execution and final reaping. A pidfd is required before any process-specific signal. Unknown termination returns 3; the shell retains the workspace. The existing cryptographic verifier remains a separate operation. |
| Installation MOK reset | Every installation first performs bounded `mokutil --list-enrolled`; only a reported certificate triggers bounded `mokutil --reset`. The certificate fingerprint marker distinguishes certificates from an empty, diagnostic-only or hash-only listing; it is not compared with the new key. With no reported certificates the helper skips reset and password lookup successfully. Both Btrfs and F2FS routes retain their nonfatal query/reset-failure handling. The attempt runs in a subshell so even explicit bridge/preflight exits cannot abort installation. Failed/uncertain requests warn and continue without automatic retry. Physical confirmation of a queued reset and enrollment of the new public certificate remain required and untested. |
| AppArmor ownership | New `hooks/target/usr/local/lib/perl5/site_perl/runtime/Managed/PolicyLock.pm` shares the existing root-private policy lock across desktop changes, mode reconciliation, rule generation and ChatGPT policy servicing. It validates lock inode ownership, type, link count and mode. Nested calls use a verified inherited descriptor; descriptors remain close-on-exec except for an explicit handoff. `scripts/late/security.sh` stages the module before the first mode invocation; installed verification and AppArmor permissions include it. |
| ChatGPT previous state | `APTRepoLocal/Servicing/ChatGPT.pm` records actual previous bytes, modes, ownership, absence, links and diversion ownership before preparation changes anything. The private synchronized recovery snapshot precedes publication. Preparation, finalization and installed-package verification share the transaction. Failed recovery or uncertain mode-helper execution retains the snapshot and blocks another managed transaction. Runtime recovery cannot claim success when the previous loaded policy cannot be verified. |
| Package handoff | `Servicing/CLI.pm`, `Servicing/Deb.pm` and `usr/local/libexec/apt-repo-local-vendor` preserve the outer policy owner through APT's documented `APT::Keep-Fds` option and explicit environment assignments. A package maintainer bridge verifies that inherited lock and prepared guards before deferring finalization to the outer owner. A standalone bridge owns its own transaction. Native APT/dpkg descriptor propagation is an outstanding acceptance gate. |
| Private updater lock | `Servicing/State.pm` uses `/var/lib/software/.update-owner/update.lock`, validates the private directory and opened regular inode, and rejects symlinks, hardlinks and unsafe ownership/modes. The same existing updater entrypoints use it; AppArmor paths were updated. No live migration or host lock was changed. |
| Vendor capture adapters | ChatGPT, Debian-package inspection, repository queries, Discord, Postman and Ledger capture adapters reuse `Managed::Process`, with explicit byte and time limits. They retain raw wait status internally and compare raw zero at their existing result boundary. The shared API's timeout `124 << 8` and signal bits were not changed. This does not bound every remaining vendor mutation or extraction path. |
| Hardware and Whisper | The hardware broker has a finite cleanup budget, cancels its owned async readers/waiters, and blocks further helper operations after an unknown outcome. It cannot launch a competing restoration. Whisper has a finite post-KILL reap interval and retains recording/state on an unknown result. Hardware ownership and restoration still require native acceptance. |
| Codex teardown | `hooks/target/data/codex/lib/codex.tmpl` waits for the pinned namespace identity to exit before releasing network/control ownership. Unknown cleanup retains control state, prevents an automatic second teardown attempt and propagates exit 76. Intentional interactive waits are preserved. |
| Codex credentials | The launched wrapper reads `CREDENTIALS_DIRECTORY/codex-mcp.env` after exec, validates a bounded direct regular credential and an explicit name allowlist, and supplies no ambient-secret fallback. One-line literal assignments and enclosing quotes are supported; multiline/control values and unknown/duplicate names fail. The service no longer uses `EnvironmentFile=-%d/...`. Installer assertions, non-secret policy comments, AppArmor access and fixtures follow that contract. |
| Installer SSH | `scripts/late/ssh/ssh-install.py` bounds streaming, input/output, command completion and reaping. It holds the direct leader unreaped until group signaling is complete. Unknown cleanup returns 76 and records a private marker. `scripts/common/ssh.sh` retains staging and owned runtime mounts for reconciliation instead of deleting evidence after that result. |
| Diagnostic boot writer | `usr/local/libexec/debugsys.py.tmpl` retains its child leader through cancellation, uses a durable pending-hook receipt, and refuses a competing rollback/retry after an unknown writer outcome. Durable writes synchronize parent directories. `debugsys-initramfs` bounds the whole capture to 30 seconds plus finite kill escalation and bounds individual reads; diagnostics do not stop boot. |
| Installer transport | `scripts/common/source.sh` disables internal redirects, validates each next URL and its approved authority before contact, rejects HTTPS downgrade, and shares one monotonic deadline across hops/retries. A native file-size limit bounds response and header files. BusyBox wget without redirect control is unavailable; the installer first attempts bounded installation of packaged `wget-udeb`, and fails before a repository request if it remains unavailable. No TLS bypass was added. |
| Model admission | `AICopilots/ModelInstallRoot.pm` serializes managed model download admission across families while retaining per-model ownership locks for readers and cleanup. It checks the full advertised model size plus 1 GiB of filesystem headroom, bounds lock acquisition and curl supervision, and records a durable pending writer. Unknown work retains the partial file and blocks both retry and prune. This coordinates managed downloads; it is not a filesystem quota or protection against unrelated writers. |
| Volatile cleanup | `scripts/late/volatile-storage.sh` checks canonical roots and a bounded target mount inventory before recursive removal. Mounted roots and descendants, including same-filesystem binds, are rejected. No mount was inspected or changed on the development host. |
| Unchanged repository refresh | `usr/local/libexec/apt-repo-local` reconciles its managed source even when package comparison/publishing is a no-op, so an interrupted source write remains repairable. This is separate from the normalizer's still-open complete-source-set recovery requirement. |
| Reported 17 October AVCs | `desktop-wrappers.tmpl` grants read access to the root-owned `/etc/labwc/plans.conf` inside **labwc-plans**; the existing grant in **telbot** did not authorize this reader. The renderer retains root/account-group ownership and mode 0640. `scripts/firstboot/assets/etc/apparmor.d/firstboot.tmpl` additionally grants `rw` on `/run/secondboot-initramfs-status.??????`, covering creation, status read and unlink of the six-character private status temporary. The existing `secondboot-initramfs.*` rule only covered the listing file. No running host policy or service was changed. |

## Coverage of all audit work packages

“Present” means source implementation exists. “Open” includes source work,
operational decisions or unexecuted acceptance, as specified in each row. The
earlier `docs/audit-remediation-20261017.md` and
`docs/tracked-changes-review-20261017.md` retain their recorded snapshot evidence;
their hashes do not identify this continuation.

| # | Current source coverage | Remaining gate or implementation |
|---|---|---|
| 1 | Embedded verification helper and quoting repairs are present. | Execute complete rendered shell boundaries, exact package arguments and forbidden-path rejection in the disposable target. |
| 2 | Complete F2FS slot/disk handoff, reused EFI preservation, encrypted-handler registration and disk/mapping checks are present. | Installer-native layout matrix, physical replacement, geometry/partition identity and recognizable preserved EFI files. A pathname recheck does not pin a native tool's later device open. |
| 3 | Public-only removable export, full installation MOK reset per the user's override, cryptographic module/kernel checks, bounded expansion and staged replacements are present. | Firmware confirmation, full-reset/new-enrollment sequence, distribution boot-chain validation, same-name replacement certificates, encrypted private-backup procedure and key retirement. Reset-request failure is deliberately nonfatal. Newly generated initramfs bodies remain owned by the native update-initramfs transaction. |
| 4 | Existing stronger pins/signatures and the user's legacy CUDA exception are preserved. | Moving release paths need an approved retained artifact set or the explicit moving-release maintenance contract below. No independent upstream authentication was invented. |
| 5 | Desktop recovery evidence and uncertainty handling, owned-table boundaries and resolved unrestricted-prefix guard are present; the LAN IPv6 policy is preserved. | Native nftables/systemd failure injection and semantic loaded-rule verification. Comment presence alone is insufficient evidence of the intended rules. |
| 6 | ntfy defaults off; authentication/reader acknowledgement and send-time policy/backlog cancellation are present; Telegram stays independent. | Execute queue races/restarts and prove endpoint reader restrictions with fixture credentials. |
| 7 | Additional hardware, Whisper, Codex, installer SSH, vendor capture and diagnostic cleanup paths are repaired. | Complete mutation/delegation deadlines, all language-bridge unknown-result propagation and cgroup/native failure injection remain open. A foreground process group does not own deliberately detached jobs. |
| 8 | Streaming capture, Platform-Tools ZIP limits, module expansion, selected listings and managed model admission have bounds. | Other archive/header/directory/provider and extraction disk/inode limits remain open. Watchdogs and a free-space check are not quotas. |
| 9 | Shared AppArmor ownership, nested handoff and true pre-preparation ChatGPT recovery are present; key-bundle attempted-publication fixes remain present. | Execute concurrency, partial publication, diversion, interrupted recovery, fsync failure and loaded-state failure cases. Verify APT handoff with the actual target packages. |
| 10 | Discord receipt recovery, optional D-Bus cleanup, validated updater lock and unchanged-release source convergence are present. | Transactional normalization of a complete intended source set, retained-reader/pruner coordination and signing-key overlap still need implementation/acceptance. |
| 11 | Bootstrap per-hop enforcement and existing stronger Perl HTTP enforcement are present. | Stable upload snapshots, authenticated initial boot/preseed distribution and atomic deployment of immutable installer generations remain external/source work. Tool acquisition must be accepted on each supported installer architecture. |
| 12 | Hook failure propagation, APT continuation, durable secondboot marking and diagnostic pending-writer handling are present. | Native kernel/initramfs failure/reboot matrix and coherent recovery of the complete boot generation. |
| 13 | Managed graceful native lifetime, menu routing and independent root terminal-power reservation are present. | Save/flush, duplicate/two-account handoff and force-after-grace behavior on the target. |
| 14 | Capture/ADB result checks, no-overwrite ExifTool/OCR publication, unavailable unsupported DOCX mutation and PDF disclosure are present. | Native collision, failed repair, cancellation and final-artifact tests. |
| 15 | Trusted authentication producers, rejected-message labelling, alert-only TCP scan handling and bounded early diagnostics are present. | Producer/parser/bouncer/rotation chain, CAPI outage behavior, audit coverage and recorded maintenance ownership. |
| 16 | Authoritative zram scan admission, busy lifecycle status and mount-descendant cleanup are present. | Telemetry freshness, backing identity, writeback endurance scope, device replacement and competing-controller restoration. |
| 17 | Existing veth, DNS, shared rootless engine, privileged Incus, NFS and authorization contracts are preserved. | Installed IPv4/IPv6/VPN/DHCP/DNS, service-cgroup and account/authorization acceptance. |
| 18 | OBS origin/metadata checks, Aptly exact signed operation receipts and Codex execution-side credential delivery are present. | Native publication/reconciliation, shared ancestry trust, secret-generation rotation and cold-start/restart delivery. |
| 19 | Existing restricted builder, pins and private runtime layout are preserved. | Retained dependency closure, authenticated repinning, exact target interpreter/modules and supported upgrade/backup scope. No source build was introduced. |
| 20 | Greeter bounds, renderer operand checks, renderer-aware shortcuts, truthful Bluetooth results and requested NTFS order are present. | Portal capabilities, debugging/proxy connectivity, qBittorrent bus requirements, appearance rollback and native login/display acceptance. |
| 21 | Existing conservative Git/firmware behavior, credential-index exclusions and additional model admission are present. | Complete queue/evidence count-byte-age limits, history-versus-reuse semantics, custom export exclusions, account/deployment identity and device/policy-learning acceptance. |
| 22 | Validation isolation, validator lifecycle, inventory classification and generated-product consistency paths remain present. | Execute fixtures and a separately provisioned disposable installed-target workflow. Record image and exact Forky/systemd 262/native package versions; no host fallback. |

## Operational contracts for release ownership

- The release maintainer owns the accepted vendor version, source URL, digest,
  verification method and dependency closure for each published installer
  generation. A digest collected after an HTTPS download is a receipt, not an
  independent vendor attestation. A moving upstream endpoint is not a
  reproducible installer pin; acceptance must state that choice explicitly.
- Review retained artifacts and security advisories before publishing each
  generation. Packages deliberately excluded from automatic updates, private
  runtimes and disabled self-updaters require that same named release owner.
  This document assigns a role; it does not claim that a human owner or an
  automated maintenance service has been configured.
- Boot trust belongs to the deployment owner. Payload hashes authenticate byte
  consistency relative to the supplied preseed; they do not authenticate a
  replaceable preseed. Publish a complete checked generation and switch the
  served directory atomically. No server, repository, credential or advertised
  deployment target was changed by this task.
- Rootless engine socket users share that engine's authority. Incus root
  operations, host INPUT, private-veth forwarding/DNAT and router forwarding are
  separate boundaries. A generated policy does not prove active routing.
- AI memory/context reuse and retained prompt history are separate. Model and
  runtime pins are separate. Local root snapshots do not cover separate home,
  data, encryption recovery material and current boot artifacts automatically.
- Preserve pending recovery directories and receipts. Do not unlink a pending
  ChatGPT/model/boot receipt to force a retry. Reconcile the owning process or
  service and the recorded source/disk/live state first. If restoration cannot
  be positively verified, the result remains unknown.

## Acceptance evidence

The exact current source/fixture fingerprints, generated artifact hashes,
serialization write inventory and static parse counts are recorded in the final
evidence section after generation. Authored fixtures are **not executed tests**.
The new failure specifications cover full MOK reset and nonfatal installation
continuation, kernel publication, module expansion, shared policy lock handoff,
hardlink/foreign-inode rejection, installer cleanup identity/signal failures and
true previous ChatGPT state. Existing focused fixtures were extended for Codex
credentials and unknown teardown (including denied signaling), cross-authority
redirects, and diagnostic boot writer refusal.

Native image identity, systemd 262 package build, interpreter/module versions,
firmware, hardware and actual test results are **not available**. The project
must retain these as open acceptance gates rather than infer them from source.

Primary contracts consulted: [systemd 262 execution and credentials](https://github.com/systemd/systemd/blob/v262/man/systemd.exec.xml),
[APT descriptor preservation](https://github.com/Debian/apt/blob/main/doc/examples/configure-index),
[Forky wget-udeb](https://packages.debian.org/forky/amd64/wget-udeb),
[GNU Wget redirect limits](https://www.gnu.org/software/wget/manual/html_node/HTTP-Options.html),
and [mokutil full reset and firmware confirmation](https://github.com/lcp/mokutil/blob/master/man/mokutil.1).
The target package builds must be retained with eventual native acceptance.

## Earlier snapshot evidence (before the Mako/import follow-up)

- Base revision: `16282bfcfc771fbb0fed81135f4b276886766d9c` plus the
  current working tree; no commit was created.
- Earlier source fingerprint: `5fb623216697b69e8819a78ba856975a60607f4541a26a985fbf6607ce882cf7`.
  This hashes 2,310 sorted existing regular tracked/untracked files as
  `four-digit-octal-mode SPACE sha256 SPACE relative-path LF`. It excludes the
  three generated installer products and this report,
  `docs/audit-remediation-20261017.md` and
  `docs/tracked-changes-review-20261017.md`, avoiding evidence self-reference.
- Fixture fingerprint: `e5513643f1cbd2e10196d2f7c74bec2c97593dfed872e1c2e1a25a6f501fe8da`;
  the same record format over the 257 source-fingerprint records whose paths
  contain `/tests/`. This identifies fixture bytes, not executed results.
- Standard-library AST parsing succeeded for 47 changed/new Python or
  Python-shebang sources. Repository modules were not imported or executed.
  This does not validate rendered Perl, shell, AppArmor or service behavior.
- Thirteen protected implementation/configuration paths, including the
  existing private Xwayland helper and two-app eligibility declarations and
  NVIDIA/CUDA legacy assets, were byte-identical to HEAD. Relevant shared-file
  diffs were also reviewed; the Xwayland implementation was not edited.
- The reviewed pure build completed with exit 0 and reported 1,798 payload
  files. Archive inspection without extraction matched every member byte to
  its current input and manifest hash: 34,552,185 total uncompressed source
  bytes. Member sets match exactly; metadata is regular-file mode 0644,
  uid/gid/mtime zero and empty owner/group names. Preseed archive, manifest and
  bootstrap-source pins match the current bytes.
- A before/after inventory of 2,430 checkout file entries showed that the build
  changed exactly the three generated products below. It did not rewrite
  source inputs. This report was updated separately after generation.
- `git diff --check` completed successfully. No test suite, test discovery,
  native syntax/policy validation, host service/firmware operation or live
  installed-target check was run. Independent sidecar review was attempted,
  but agent initialization failed; it supplied no review evidence.

Pure serialization command:

```sh
/usr/bin/env -i PATH=/usr/bin:/bin LC_ALL=C.UTF-8 /usr/bin/make build 'PYTHON=/usr/bin/python3 -I' SHELL=/bin/sh
```

| Earlier generated product | Bytes | SHA-256 |
|---|---:|---|
| `d-i/forky/payload.tar.gz` | 26,520,992 | `eced8e078d54b3285115efd1186a5b3f4e69ad819643076125544d566cbfedd4` |
| `d-i/forky/payload.manifest` | 221,645 | `e21a6e8c9a84a3372fb8c735ad461981ecdfbdfb8a8225c1f93c134a53ae43c2` |
| `d-i/forky/preseed.cfg` | 95,579 | `822596f4885ae4d4f3f22508729c4738690ca2014bf859054ac770aa60f3cfde` |

Detailed source/file inventories and static archive observations from this
review are in `/tmp/preseed-comprehensive-final-gdk6v85g`. These are local
inspection receipts, not target release acceptance. The table of 22 work
packages above explicitly retains both unimplemented source requirements and
unexecuted native acceptance gates.

## Mako and installer import follow-up

The later request changes Mako's canonical skeleton template to `layer=top`.
The generated payload must contain that exact source; no running desktop
configuration or service is changed by this checkout update.

The reported installation failure is inside `software_enable_chatgpt_integration`
in `scripts/late/software.sh.tmpl`, before desktop startup. The user confirms
AppArmor is inactive at this point. `run_in_target` propagates the updater's
failure, and the Perl bootstrap abort produces status 255. That outer status
does not identify the underlying importer error. Source tracing confirms that
the shared Perl runtime modules and canonical ChatGPT assets are staged before
this bootstrap call in the normal late-dispatch sequence.

The repository capture adapter incorrectly used the 120-second query deadline
for imports that validate the original archive, rewrite the policy-controlled
payload, validate the replacement and sign the repository generation. Individual
native payload phases allow 240 seconds. Imports now have a separate bounded
1,200-second deadline; catalogue and package queries retain 120 seconds. The
adapter preserves the shared raw wait-status contract and reports timeout,
signal or exit status together with the importer's bounded managed diagnostic.
URLs are redacted, control characters replaced and unmanaged child output is
excluded. A timeout explicitly states that the import outcome may be unknown.
Bootstrap errors now distinguish repository import, download and validation.

The installed updater profile additionally declares read access to the shared
`Managed/Process.pm` module and paired TERM/KILL/CHLD permissions for its existing
transition to `apt-repo-local`. These keep the bounded capture/cleanup contract
wired on an installed system; they are not an explanation for this unconfined
installation failure. No policy was loaded or reloaded.

Read-only inspection of the official moving download endpoint returned HTTP 200
on 17 October 2026. The archive was 502,087,434 bytes, SHA-256
`3ca59e7f9a6641b9e2fb9ad680683784b5ab8026ff7418fb212a0ebe5df3a1d7`,
with package `chatgpt`, version `26.1013.40934`, architecture `amd64`.
Standard-library archive inspection read 4,145 data members containing
1,691,423,659 bytes, including the required ChatGPT/Codex executables and launcher
symlink. No package was installed, extracted to target paths, executed, imported
through repository code or recompressed as a benchmark. This moving-endpoint
receipt is not a vendor-signature verification or a reproducible release pin.

Four additional isolated fixture specifications cover an import exceeding the
query deadline, exact returned pool paths, managed diagnostic/URL filtering,
raw timeout/signal decoding and correct bootstrap failure-stage reporting.
They have not been executed. No prepared disposable target image is available.
The actual failed installation's underlying importer output was unavailable;
the deadline defect is established from source, but attributing that specific
failure to it and accepting a complete Forky installation remain native gates.
The original 22-package acceptance ledger above remains open as recorded.

### Mako/import snapshot serialization and static evidence

- Base revision remains `16282bfcfc771fbb0fed81135f4b276886766d9c` with the
  existing working tree; no commit or deployment was made.
- Source fingerprint: `c5080723443c358998a940983640ad00fb53faf7a36412aaaf311249fa4f0f5d`
  over 2,310 source records, using the same mode/hash/path format and report/product
  exclusions as the earlier snapshot.
- Fixture fingerprint: `09d05eaeb3c77c1f443eaa0cd31d798f86aa0d3f34fb88d53fc432db88c8ca50`
  over 257 fixture records. Fixture execution remains unavailable.
- Standard-library AST parsing succeeded for 46 changed/new `.py` or
  Python-shebang files. This is source parsing without repository imports,
  rendered shell/Perl compilation or native policy checks.
- The reviewed pure serialization command shown above exited 0 and produced
  1,798 members containing 34,554,239 uncompressed source bytes. Data-only
  inspection matched every member byte, manifest hash and source input;
  metadata and source/member sets matched. The Mako member contains `layer=top`.
- Archive, manifest and bootstrap-source pins in `preseed.cfg` match current
  bytes. A before/after inventory of 2,430 checkout entries confirmed that
  serialization changed exactly the three products below and no source inputs.
- `git diff --check` succeeded. No test runner, native validator, package install,
  target helper, host manager or policy reload was executed. The read-only
  sidecar review attempt failed during agent initialization and supplied no
  independent evidence.

| Mako/import snapshot product | Bytes | SHA-256 |
|---|---:|---|
| `d-i/forky/payload.tar.gz` | 26,521,840 | `924939adef1eab0e5aebb8f9ccb6545aae9c780541397d587b2f62486e43024c` |
| `d-i/forky/payload.manifest` | 221,645 | `93395a2aa745fd90b7d93a81cb6b9a33128c3877adcfde5de0112bb2db8e7b60` |
| `d-i/forky/preseed.cfg` | 95,579 | `6994cd43183f4641ecbd6de9da20d860c4e374269b6ec5460b0d58738f5ab59a` |

Detailed follow-up receipts are in `/tmp/preseed-import-followup-cmmbe4hf`;
the public vendor archive inspection is in
`/tmp/preseed-chatgpt-inspection-nh31jjd3`. These identify inspected bytes and
serialization outcomes, not a successful installation or closed native gates.

## Conditional MOK reset and installed-log follow-up

The subsequent MOK guard queries the complete enrolled list under `LC_ALL=C`
with a 15-second timeout and a separate two-second kill interval. It queues the
existing full reset only when that successful listing reports an X.509
certificate fingerprint. Empty, message-only and hash-only lists skip reset and
password lookup. A failed or timed-out query cannot authorize a reset, including
when partial certificate output was captured. Both storage installation routes
retain the nonfatal reset wrapper; inability to query or queue deletion does
not abort installation. Queued firmware changes still require MokManager
confirmation. No firmware operation was performed during this review.

The isolated MOK specifications now include one/multiple enrolled certificates,
empty/message/hash-only lists, partial-output query failures, query timeout,
reset failure, timeout-setting failure and installer continuation after both
returned failures and explicit exits. These are authored, unexecuted fixtures.

The later `todo/**` request is covered in
[Installed failures, 17 October](installed-failures-20261017.md), including all
52 supplied files, four source repairs, preserved security boundaries and
remaining native/hardware/external-approval gates. Its final serialization
receipt supersedes the earlier product snapshots above. Earlier snapshots and
the original 22-package acceptance ledger retain their historical scope.
