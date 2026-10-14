# Desktop log collection, intrusion detection and configuration names

## Final scope

This change targets Forky desktops with systemd 262. It completes the logging
follow-up, retains qBittorrent discovery at 30 seconds, and excludes HTTP AppSec
installation/activation as requested. Seven desktop Hub collections remain:
linux, sshd, auditd, iptables, whitelist-good-actors, linux-lpe and qBittorrent.

The user's final naming clarification limits cleanup to filenames and names
inside configuration. Python/Perl packages, module names, functions and imports
retain their names. Source references to renamed configuration files are updated.
Required native browser policy directories and NetworkManager keys remain, per
the user's explicit answer. The broader module-renaming plan was a dry run only.
Historical JSON validation records and supplied diagnostic logs are preserved.

## Rsyslog collection and overhead

`etc/rsyslog.d/30-apparmor.conf.tmpl` now uses `imfile` with `mode="inotify"`.
The former two-second polling scan is removed. One fixed audit file supplies the
AppArmor mirror, and auditd retains native rename/create rotation ownership.

Cursor persistence changes from every record to every 64 records, with
`persistStateAfterSubmission="on"` for an additional submission checkpoint.
`MaxSubmitAtOnce="64"` remains below the 1,000-record queue capacity. The mirror
retains one worker, native record-type checks, the original line content,
protected output permissions, desktop signals and size-based retention.
Cursor persistence does not make the in-memory queue crash-durable; the native
audit file remains authoritative. Rotation during collector downtime can leave
unread records in an old file. No zero-loss or measured CPU claim is made.

The existing input split remains appropriate: `imuxsock` accepts local Unix
socket messages; `imklog` reads the kernel stream with journald `ReadKMsg=no`.
There is no added journal database reader, network receiver or duplicate kernel
collector. The firewall route now additionally requires `$inputname == "imklog"`,
so an application-supplied kern facility/tag alone does not select that route.

These choices follow the native [imfile monitoring mode](https://docs.rsyslog.com/doc/reference/parameters/imfile-mode.html),
[cursor interval](https://docs.rsyslog.com/doc/reference/parameters/imfile-persiststateinterval.html),
[submission checkpoint](https://docs.rsyslog.com/doc/reference/parameters/imfile-persiststateaftersubmission.html),
[rotation contract](https://docs.rsyslog.com/doc/configuration/modules/imfile.html),
[Unix socket input](https://docs.rsyslog.com/doc/configuration/modules/imuxsock.html)
and [kernel input](https://docs.rsyslog.com/doc/configuration/modules/imklog.html).

## Acquisition wiring

| Source | Acquisition | Discovery timer | Content polling |
| --- | --- | --- | --- |
| SSH | Filtered `ssh.service` journal | None | Journal stream |
| auditd | Existing native audit file | Disabled; file pre-created | `poll_without_inotify: false` |
| nftables | Existing dedicated packet log | Disabled; file pre-created | `poll_without_inotify: false` |
| kernel | Existing dedicated kernel file | Disabled; file pre-created | `poll_without_inotify: false` |
| pkexec | `_COMM=pkexec` journal | None | Journal stream |
| qBittorrent | Exact native desktop account log | 30 seconds | `poll_without_inotify: false` |

The previous kernel-journal proposal was incorrect for `ReadKMsg=no`. Acquisition
23 now reads `__INSTALLER_LOG_KERNEL_FILE__`; the existing rsyslog kernel fallback
uses `RSYSLOG_FileFormat`. Firewall packets are routed to their separate file
before that fallback, avoiding deliberate double ingestion. The pkexec document
remains separate because authpriv records are excluded from the general log.

Discovery and content monitoring are independent. Audit, nftables and kernel
files are pre-created by existing tmpfiles policies, so no discovery timer was
added to them. qBittorrent discovery handles its late-created or mounted log.
The retained qBittorrent scenario covers WebUI authentication failures if that
WebUI is enabled; it does not inspect torrent peers. The normal desktop config
continues to disable the WebUI. See the [CrowdSec file-source contract](https://docs.crowdsec.net/docs/log_processor/data_sources/file/).

## Added intrusion configuration

Five JSON documents, valid YAML, are staged root-owned at mode 0644 by
`scripts/late/crowdsec.sh`. Their names are:

| Configuration | Contract |
| --- | --- |
| `parsers/s01-parse/00-nftables-nondrop.yaml` | Excludes this producer's lowercase accept/audit prefixes before the upstream drop parser |
| `parsers/s02-enrich/00-audit-security.yaml` | Normalizes supported exec ABIs and authoritative AppArmor denials |
| `scenarios/nftables-tcp-scan.yaml` | Distinct dropped host-port probes per source IP; eligible for IP remediation |
| `scenarios/nftables-udp-scan.yaml` | Distinct dropped host-port probes; alert only because datagrams are spoofable |
| `scenarios/apparmor-denial-burst.yaml` | Repeated enforced denials grouped by profile/PID; alert only, PID scope |

The firewall producer uses `5/minute burst 10 packets` in the desktop profile.
The upstream TCP scenario's capacity 15 and five-second leak cannot be reached
through that single sampled input budget. The local TCP/UDP buckets use capacity
7 and a 60-second leak, with a five-minute blackhole. A burst of eight distinct
dropped input ports can overflow them; slow events leak away. Logging volume is
unchanged. Competing traffic, packet sampling and source spoofing still limit
what this signal proves. These rules are not complete packet inspection.

The local audit parser retains upstream metadata and handles x86-64 syscall
59/322, i386 11/358, AArch64 221/281 and ARM compatibility 11/387. Login AUID must
be present and not unset. A separate `audit_security_pid_progname` cache holds
at most 100 entries for one minute and hydrates parent names across these ABIs;
it does not redeclare the upstream cache. Existing root/user audit rules and
their event volume are unchanged.

The AppArmor node accepts native AVC/1400/APPARMOR_DENIED records with an actual
DENIED value, profile and PID. It does not treat quoted EXECVE arguments as
denials. Its bucket has capacity 9 and a ten-second leak. Repeated denials can
also indicate a policy mismatch; this produces an alert and does not terminate
processes or generate an IP ban.

The native [iptables parser](https://github.com/crowdsecurity/hub/blob/master/parsers/s01-parse/crowdsecurity/iptables-logs.yaml),
[TCP scan scenario](https://github.com/crowdsecurity/hub/blob/master/scenarios/crowdsecurity/iptables-scan-multi_ports.yaml),
[audit parser](https://github.com/crowdsecurity/hub/blob/master/parsers/s01-parse/crowdsecurity/auditd-logs.yaml)
and [scenario format](https://docs.crowdsec.net/docs/log_processor/scenarios/format/)
were reviewed as primary sources. Native syscall tables are available for
[x86-64](https://github.com/torvalds/linux/blob/master/arch/x86/entry/syscalls/syscall_64.tbl),
[i386](https://github.com/torvalds/linux/blob/master/arch/x86/entry/syscalls/syscall_32.tbl),
[AArch64/generic](https://github.com/torvalds/linux/blob/v6.12/include/uapi/asm-generic/unistd.h)
and [ARM](https://github.com/torvalds/linux/blob/v6.12/arch/arm/tools/syscall.tbl).

## Filename and configuration-name cleanup

All 15 installer-owned configuration filenames with the unwanted prefix are
renamed. Their new paths below are relative to `hooks/target/etc`:

- `qbittorrent/qBittorrent.conf.d/10-security.conf.tmpl`
- `fail2ban/fail2ban.d/10-security.local`
- `NetworkManager/system-connections/wifi.nmconnection.tmpl`
- `NetworkManager/conf.d/90-network-external.conf.tmpl`
- `systemd/system/wifi-firstboot.service`
- `apparmor.d/abstractions/app-config`
- `apparmor.d/abstractions/workflow-auth`
- `apparmor.d/abstractions/base.d/process-monitor`
- `crowdsec/parsers/s00-raw/podman-logs.yaml` (inactive example remains inactive)
- `crowdsec/parsers/s01-parse/00-auditd-daemon.yaml`
- The five detection files listed above.

Rsyslog action/template/ruleset identifiers, CrowdSec parser/scenario IDs,
acquisition labels, metadata and cache references use the same cleaned names.
There are 40 distinct rsyslog configuration identifiers and no unresolved local
ruleset references. Wi-Fi uses `id=Wi-Fi`; its keyfile, lock and private temporary
filenames are updated together with the unit, helper, validator and AppArmor
grants. Native NetworkManager configuration keys retain their required spelling.

The installer shell module is now `scripts/desktop/components/apps.sh`; its
functions and Python package it publishes retain their names. Two documentation
filenames are also cleaned: `objectives-20261006.md` and `gitops-20261007.md`.
Thus 18 filenames were renamed. Caller, staging, verifier, permission policy,
fixture and documentation references were updated without changing Python or
Perl symbol/import/argument names. Source file modes are preserved.

## Verification actually performed

`AGENTS.override.md` requires a prepared disposable environment for repository
tests and native validators. None was available. No tests, including mocked
tests, were executed; no host CrowdSec, rsyslog, systemd, AppArmor, nftables,
auditd or crypto command was invoked. No CPU benchmark or installed deployment
was performed. Independent read-only sidecars failed initialization with
encrypted-content hydration errors; no child findings were used.

Completed checks were source-as-data inspection and permitted serialization:

- Standard-library AST parsing of 406 Python source/helper/test files, without
  importing or executing repository modules.
- JSON parsing of all five new detection documents and explicit inspection of
  their staging, filter, scope, cache, counter and remediation contracts.
- Static rsyslog identifier uniqueness and local ruleset-reference checks.
- Static kernel producer/acquisition, pre-created file, inotify/discovery,
  configuration filename/reference and Python/Perl symbol-preservation checks.
- Source hashes confirmed 45 crypto, workflow, desktop runtime, MOK and Go
  provisioning/environment assets unchanged from the previous combined review.
- `git diff --check`, with no whitespace errors.
- Full Makefile/build/publication inspection, followed by permitted
  `make build PYTHON=python3`: **built 1773 payload files**.
- Standard-library tar/hash inspection verified all 1,773 entries against
  source bytes and manifest hashes, normalized mode 0644, zero UID/GID/time,
  private-input/test exclusions and current bootstrap pins. No archive member
  was extracted or executed.

Regression source covers the producer-specific firewall guard, kernel file
acquisition, ABI normalization, alert/remediation separation, installed asset
names/modes, configuration failure handling and inotify/cursor settings.
Existing filename-contract regressions were updated. These tests were not run.
Firstboot retains its required native `crowdsec -t` gate before service restart;
rsyslog retains its installed native configuration preflight.

## Current combined generated snapshot

These hashes supersede all earlier intermediate 2026-10-14 integration hashes.

| Product | SHA256 |
| --- | --- |
| `payload.tar.gz` | `7ba84a26593079555155137be426df65751e57ed29d448414634ca18b1da59e5` |
| `payload.manifest` | `613f92da5b5be5a468b37f9fb235eae2a64f891ac5da59647f85b0861dec491d` |
| `preseed.cfg` | `8a8a213142d01aa20ac4222e89b75a514aab466e47e4cbba2ab55bc3873d6296` |

## Deployment limits

Source consistency does not establish native expression/schema acceptance,
inotify rotation behavior on an installed filesystem, live detection decisions,
GUI/MOK prompts or measured CPU reduction. Those remain integration checks for
an isolated Forky image. The existing firstboot/native preflight gates are kept.

The artifacts install the new names on fresh hosts. Updating an existing host
requires deploying each renamed configuration together with its callers and
permission-policy references; copying one renamed file alone is insufficient.
Completed firstboot markers do not reconcile old Hub state automatically.
No existing installation was changed and no administrator additions were purged.
