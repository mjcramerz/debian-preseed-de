# Desktop CrowdSec relevance and ingestion repair

The subsequent [logging and intrusion review](crowdsec-intrusion-20261014.md)
records the final source state and artifact hashes. Verification and snapshot
sections below describe the earlier intermediate build.

## Scope and final desktop policy

This repository installs Debian Forky desktops. CrowdSec setup now stages the
resolved desktop identity, desktop audit rules and qBittorrent source without a
host-variant branch. Firstboot installs the following seven maintained Hub
collections in one command; collection dependencies supply their native parsers.

| Collection | Relevant input / purpose |
| --- | --- |
| `crowdsecurity/linux` | Syslog/date/IP foundations and Linux protection dependencies |
| `crowdsecurity/sshd` | Dedicated `ssh.service` journal; SSH brute-force and related SSH signals |
| `crowdsecurity/auditd` | Dedicated native audit log; post-exploitation and abnormal-execution signals |
| `crowdsecurity/iptables` | Dedicated managed nftables packet log; multi-port scan detection |
| `crowdsecurity/whitelist-good-actors` | Maintained known-good-actor exclusions |
| `crowdsecurity/linux-lpe` | Kernel file and pkexec journal records; maintained local-exploit signatures |
| `gilbsgilbs/qbittorrent` | Exact native qBittorrent log; WebUI authentication brute-force scenario |

The explicitly requested qBittorrent file discovery is retained at its identical
native path. The follow-up review changed `discovery_poll_interval` from `10s` to
`30s` and explicitly keeps `poll_without_inotify: false`. Discovery rescans for a
late-mounted/new log; existing content uses file notifications. Audit and nftables
file sources explicitly set `poll_without_inotify: false` and keep
notification-based tailing with no added discovery polling;
Kernel content also follows its pre-created file with inotify; SSH and pkexec
sources stream filtered journals. The standard
installation still disables its WebUI. This Hub scenario detects WebUI failed
authentication when a WebUI is deliberately enabled; it does not inspect torrent
peer traffic. There is one pkexec acquisition, moved out of the qBittorrent
document into the dedicated security document.

### Removed automatic pipeline work

- `crowdsecurity/base-http-scenarios` and its HTTP CVE dependencies: no managed
  HTTP access-log producer is wired into this desktop acquisition pipeline.
- `crowdsecurity/appsec-virtual-patching` and automatic publication of its
  localhost listener: no HTTP/AppSec bouncer integration is configured. The
  nftables bouncer applies IP decisions and is not an HTTP request inspector.
- Standalone `crowdsecurity/nginx-logs` / `crowdsecurity/docker-logs` installation
  and staging of the managed Podman raw parser: no matching acquired web or
  container log is configured.
- Broad system-service and veth file ingestion: ordinary lifecycle records do
  not supply the retained LPE scenarios. Kernel records come from the existing
  kernel file, because this repository sets journald `ReadKMsg=no`. The earlier
  proposed kernel-journal source was corrected in the subsequent review. The
  second document acquires `_COMM=pkexec`.

Five acquisition files provide six inputs: SSH journal, audit file, firewall
file, kernel file, pkexec journal and qBittorrent file. No repeated
pkexec ingestion is configured. Console/CAPI communication, blocklist pulls,
bouncer identity, retry behavior and root/user audit exec rules are preserved.
There is no CPU quota, detection sampling or blanket audit suppression.

## Exact changed paths

- `d-i/forky/hooks/target/etc/crowdsec/acquis.d/21-auditd.yaml.tmpl` and
  `22-nftables.yaml.tmpl`: follow-up review explicitly disables stat-based
  content polling; discovery polling remains disabled.
- `d-i/forky/scripts/late/crowdsec.sh`: desktop-only staging; retained qBittorrent;
  stopped staging unused AppSec acquisition and Podman parser; fixed desktop
  audit source and firstboot metadata.
- `d-i/forky/scripts/firstboot/assets/var/lib/firstboot/bin/crowdsec-firstboot.tmpl`:
  one seven-collection install; removed extra HTTP/container parser installation,
  AppSec activation function/call and its now-unused publication rollback.
- `d-i/forky/hooks/target/etc/crowdsec/acquis.d/23-system-syslog.yaml.tmpl`:
  kernel file and pkexec journal replace the broad system/veth file sources.
- `d-i/forky/hooks/target/etc/crowdsec/acquis.d/24-qbittorrent.yaml.tmpl`:
  removed the relocated pkexec document; the follow-up review changes discovery
  to 30 seconds while keeping content tailing notification-based.
- `d-i/forky/tests/test_crowdsec_firstboot_retry.py`: adapted installed-source
  assertions and fixtures, removed tests for the removed AppSec publisher, and
  added exact collection arguments/config-failure handling checks that preserve
  an existing administrator AppSec fixture. **These tests were not run.**
- This report and links recording subsequent snapshot history in the earlier
  PKI/MOK/key-manager reports.
- Regenerated `d-i/forky/payload.tar.gz`, `payload.manifest` and `preseed.cfg`.

Unused web integration examples remain repository source material; the installer
does not stage/activate them. Adding a future web workload requires its actual
log source, matching collection and HTTP remediation integration to be wired
explicitly. No administrator Hub items or acquisitions are purged by this
fresh-install change.

## Verification actually completed

`AGENTS.override.md` prohibits development-host tests and native validators.
No prepared disposable environment is available. No CrowdSec daemon, cscli,
journalctl, auditctl, nftables, host manager, native policy parser or test runner
was executed. No installed configuration, metrics, credentials or package state
was read. No CPU measurement or live remediation was performed. Independent
read-only sidecar attempts failed before work with encrypted-content hydration
failure; no child review findings were used.

- Source/diff review traced acquisition -> maintained Hub parser/scenario ->
  existing bouncer, plus late-stage identity and native logging/template fetch.
- Checked current primary Hub files and CrowdSec data-source documentation.
  Checked systemd 262 journalctl documentation and argument handling: grep and
  follow coexist; grep does not imply reverse when follow is selected.
- `python3 -I -B` standard-library AST parsing of both repaired PKI modules and
  changed filesystem/CrowdSec tests, without repository imports/execution.
- Source-as-data comparison confirmed seven unconditional collection arguments,
  no installation-variant branch, desktop audit source, exactly one pkexec
  acquisition, and byte-identical qBittorrent file polling settings.
- Compared the preceding PKI snapshot: exactly the four CrowdSec runtime source
  files changed. All PKI, MOK, Xwayland and unrelated payload content is preserved.
- `git diff --check` completed without whitespace errors.
- Reviewed `Makefile`, `tools/build.py` and `tools/publication.py`; the permitted
  serialization-only `make build PYTHON=python3` produced **1,768 payload files**.
- Standard-library archive/hash inspection found every regular normalized entry
  identical to source bytes and manifest SHA256, required repaired assets
  present, private inputs/tests excluded, and all three bootstrap pins current.

### Combined snapshot before the follow-up review

This includes the key-manager integration, MOK repair, PKI traversal repair and
CrowdSec changes before the subsequent 30-second discovery and GPG/TLS lifecycle
corrections. The [follow-up integration review](integration-review-20261014.md)
records the current combined snapshot and supersedes these hashes.

| Product | SHA256 |
| --- | --- |
| `payload.tar.gz` | `af069c02d9c520feccf70406adcdc180ed44d59ff1cbd2cfb769dfde793e9238` |
| `payload.manifest` | `78b1a9d4ac8779c519f8b5b88d88de06daa69a0bf56afdb55b77809c38c91ad9` |
| `preseed.cfg` | `1c8aa7acf3f56bab3fa2027691625a65419708cb1a37ffedf7f96e84c3637e20` |

## Runtime and deployment limits

These changes remove demonstrated unused dependencies and irrelevant ingestion.
The reported constant 2% CPU was not reproduced or attributed to a specific
component. Its reduction is unmeasured. The retained audit execution stream and
qBittorrent polling still have processing costs. Native parsing, decisions,
filtered journal following and bouncer acceptance require disposable Forky
integration and installed-version verification; Hub dependencies can change.

The subsequent local audit normalization adds execve/execveat handling for the
supported x86-64, i386, AArch64 and ARM compatibility ABIs. Native acceptance has
not been exercised. Local exploit signatures are signals, not kernel exploit
prevention, and some produce local-account/executable alerts rather than IP bans.

This repository generation does not alter a running installed system. Updating
an already completed firstboot helper alone does not reconcile its prior Hub
state: completed markers intentionally prevent repeated bootstrap. Existing
deployments need their managed acquisitions and selected Hub items updated
through the deployment boundary, preserving administrator additions. The PKI
permission repair separately requires its two changed Python modules together;
PKI directory permissions do not need widening.

## Primary references

- [Linux collection](https://github.com/crowdsecurity/hub/blob/master/collections/crowdsecurity/linux.yaml),
  [SSHD collection](https://github.com/crowdsecurity/hub/blob/master/collections/crowdsecurity/sshd.yaml),
  [auditd collection](https://github.com/crowdsecurity/hub/blob/master/collections/crowdsecurity/auditd.yaml),
  [iptables collection](https://github.com/crowdsecurity/hub/blob/master/collections/crowdsecurity/iptables.yaml),
  [Linux LPE collection](https://github.com/crowdsecurity/hub/blob/master/collections/crowdsecurity/linux-lpe.yaml).
- [qBittorrent scenario](https://github.com/crowdsecurity/hub/blob/master/scenarios/gilbsgilbs/qbittorrent-bf.yaml)
  and [segfault parser](https://github.com/crowdsecurity/hub/blob/master/parsers/s01-parse/crowdsecurity/segfault-logs.yaml).
- [HTTP collection](https://github.com/crowdsecurity/hub/blob/master/collections/crowdsecurity/base-http-scenarios.yaml)
  and [AppSec collection](https://github.com/crowdsecurity/hub/blob/master/collections/crowdsecurity/appsec-virtual-patching.yaml).
- [CrowdSec journal acquisition](https://docs.crowdsec.net/docs/log_processor/data_sources/journald/)
  and [file discovery/polling](https://docs.crowdsec.net/docs/log_processor/data_sources/file/).
- [AppSec request inspection and required web integration](https://docs.crowdsec.net/docs/appsec/intro/).
- [systemd 262 journalctl reference](https://github.com/systemd/systemd/blob/v262/man/journalctl.xml)
  and [argument handling](https://github.com/systemd/systemd/blob/v262/src/journal/journalctl.c).
