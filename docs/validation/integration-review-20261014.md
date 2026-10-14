# Follow-up integration review: key-manager and desktop CrowdSec

The subsequent [desktop logging and intrusion review](crowdsec-intrusion-20261014.md)
records the final kernel acquisition repair, rsyslog optimizations, additional
detection configuration and filename cleanup. Its artifact hashes supersede the
intermediate snapshot below. The GPG/TLS findings in this report remain applicable.

## Scope and completed source changes

Reviewed the accumulated key-manager, PKI, APT MOK, desktop Go and CrowdSec
changes through their callers, staging, renderer and generated payload paths.
The target remains the desktop-only Forky installation with systemd 262.
Existing pinentry-qt, fzf, SSH agent, PKI layout and private Xwayland policy are
preserved. No software was compiled and no installed system was changed.

### GPG identity expiry

The previous expiry action passed `*` to `--quick-set-expire`, which updates
subkeys while leaving the primary expiry unchanged. The action now:

1. Lists the selected primary's subkeys using GnuPG's colon format.
2. Validates full fingerprints and excludes revoked subkeys.
3. Updates the primary with the two-argument form.
4. Updates the remaining subkeys explicitly, including expired subkeys.

A primary without subkeys performs only its primary update. Invalid fingerprints
fail before mutation; a primary update failure stops the subsequent update.
GnuPG changes are sequential: if the subkey command fails, the primary may
already have changed. The command error propagates through the existing menu.
See the [GnuPG command contract](https://www.gnupg.org/documentation/manuals/gnupg/OpenPGP-Key-Management.html).

### Traditional RSA export

An imported RSA-2048 key was accepted for existing identities but rejected by
the traditional RSA/EC export's generation-size allowlist. Export now accepts
RSA types already validated by the certificate reader, including RSA-2048,
while retaining the existing EC types and rejecting EdDSA/PQC traditional
exports. New RSA generation still offers 3072/4096 bits. Export confirmation,
private staging, native conversion and mode-0600 publication are unchanged.
See [OpenSSL pkey output formats](https://docs.openssl.org/3.6/man1/openssl-pkey/).

### CrowdSec discovery and content acquisition

| Managed source | New-file discovery | Content acquisition |
| --- | --- | --- |
| qBittorrent file | Explicitly enabled every 30 seconds | `poll_without_inotify: false`; file notifications |
| auditd file | Discovery polling remains disabled | Explicit `poll_without_inotify: false` |
| nftables file | Discovery polling remains disabled | Explicit `poll_without_inotify: false` |
| Kernel file | Discovery polling remains disabled | Explicit `poll_without_inotify: false` |
| SSH and pkexec journals | No file-discovery timer | Filtered journal streams |

The qBittorrent interval changes from 10 to 30 seconds. The exact native log path,
account renderer and scenario remain. All four file acquisitions explicitly
disable stat-based content polling. `discovery_poll_interval` applies when
discovery is enabled; setting notification-based content acquisition does not
enable discovery. The audit and nftables files are pre-created by the existing
`75-auditd-storage.conf.tmpl` and `59-log-layout.conf.tmpl` tmpfiles policies.
The repository's qBittorrent launcher requires a mounted real directory at the
configured media path but does not restrict its filesystem type; no installed
volume or filesystem was inspected here.
See [CrowdSec file-source options](https://docs.crowdsec.net/docs/log_processor/data_sources/file/)
and [journal acquisition](https://docs.crowdsec.net/docs/log_processor/data_sources/journald/).

The seven desktop collections and six inputs remain. Their staging still uses
the logging renderer for audit/nftables placeholders and the resolved desktop
account for qBittorrent. The APT MOK error-propagation/TTY/AppArmor repair and
non-root Go provisioning/environment changes remain byte-identical to the
preceding combined payload.

### Automatic AppSec decision

AppSec is HTTP request inspection for hosted web applications. A compatible
web-server/reverse-proxy remediation component must forward requests to the
AppSec listener and apply its response. The current installer integration
installs an nftables IP bouncer and has no such HTTP forwarding component.
Automatic publication of an unused listener remains disabled. The unused
example stays in repository source, and no administrator configuration is
purged. A future hosted web workload needs its actual request path, compatible
HTTP bouncer, matching rules and acquisition wired together.
See [CrowdSec AppSec architecture and integration requirements](https://docs.crowdsec.net/docs/appsec/intro/).

## Exact paths changed in this pass

- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/key_manager/gpg.py`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/key_manager/tls.py`
- `d-i/forky/hooks/target/etc/crowdsec/acquis.d/21-auditd.yaml.tmpl`
- `d-i/forky/hooks/target/etc/crowdsec/acquis.d/22-nftables.yaml.tmpl`
- `d-i/forky/hooks/target/etc/crowdsec/acquis.d/24-qbittorrent.yaml.tmpl`
- `d-i/forky/tests/test_key_manager_lifecycle_20261014.py`
- `d-i/forky/tests/test_crowdsec_firstboot_retry.py`
- `docs/validation/crowdsec-desktop-relevance-20261014.md`
- This report.
- Generated `d-i/forky/payload.tar.gz`, `payload.manifest` and `preseed.cfg`.

## Evidence and verification boundary

`AGENTS.override.md` prohibits host tests and native validators. No prepared
disposable environment is available in this session. No repository test was run,
including mocks. No GnuPG/OpenSSL/CrowdSec helper, installed package query, host
service, policy loader or CPU measurement was executed. Three independent
read-only agent tasks failed initialization with encrypted-content hydration
errors; no child findings were used. The coordinator performed the review.

- Read the actual dirty diff, eight key-manager modules, command wrapper,
  shared filesystem module and affected installer/MOK/Go/CrowdSec contracts.
- `python3 -I -B` with standard-library AST parsing parsed 15 source files,
  without importing or executing repository code. The new test's isolation
  gate precedes its runtime imports. Native commands in its regressions are
  spies; fixture writes stay in an owned temporary directory.
- Added regression source for primary/subkey expiry, expired/revoked selection,
  primary-only keys, failure stopping and malformed fingerprints; TLS export
  covers RSA-2048, RSA-4096, EC and EdDSA rejection. **Not executed.**
- Updated CrowdSec regression source to require 30-second qBittorrent discovery
  and disabled content polling in all three file sources. **Not executed.**
- Static acquisition inspection confirmed six inputs, one pkexec acquisition,
  exactly seven unconditional collections, desktop audit staging and no automatic
  AppSec activation. No discovery polling was added to auditd/nftables.
- `git diff --check` completed without whitespace errors.
- Read the full Makefile/build/publication execution path before the permitted
  serialization command. Final `make build PYTHON=python3` completed with
  `built 1768 payload files` after the final acquisition settings changed.
- Standard-library archive/hash inspection compared all 1,768 regular entries
  against source bytes and manifest hashes, checked normalized mode 0644 and
  zero UID/GID/timestamp, private-input/test exclusions, and all three bootstrap
  hash pins. No member was extracted to disk or executed.
- Comparing the final archive with the combined payload at the start of this
  pass found exactly the five runtime source paths above changed. All other
  runtime member bytes, including MOK, Go and Xwayland, are unchanged. Checkout
  source modes remain 0600; installed command/module modes remain controlled by
  the existing staging rules.

### Snapshot before the logging and intrusion follow-up

These intermediate hashes include the key-manager, MOK, PKI and earlier desktop
CrowdSec changes. The subsequent logging and intrusion report supersedes them.

| Product | SHA256 |
| --- | --- |
| `payload.tar.gz` | `1b3d240f1be50bd4015996c07198b76b086ff5ba557d5b22316ab09665204558` |
| `payload.manifest` | `d93ed73a0d4b5c9b965d8bc20848619e2b96c9c21f18058e75334250dd4bbcc5` |
| `preseed.cfg` | `af47fec4e469f7e3cfd25d4652f908635c98901dbd0088d2956df4f0a5cfa030` |

## Deployment limits

Static review and serialization establish source/payload consistency. They do
not establish installed crypto acceptance, filesystem notifications, GUI prompts,
MOK unlocking, transient-service cancellation, ACME renewal or CrowdSec decisions.
The reported CPU usage was not measured or attributed to polling; no measured
CPU reduction is claimed.

This checkout does not deploy changes to an existing installation. Deploy the
updated managed modules/acquisitions through the existing deployment boundary.
Completed firstboot markers retain their behavior; rewriting a completed helper
alone does not reconcile previously installed Hub items. Preserve administrator
additions when updating that state.
