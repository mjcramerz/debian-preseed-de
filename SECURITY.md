# Security and trust boundary

This repository is privileged installer code. Boot only a preseed source you
trust and use an isolated disposable machine when validating changes.

## Source integrity

The generated preseed pins the bootstrap transport, payload archive and manifest
with SHA-256. Archive names, regular-file types, duplicate members, archive/member
agreement and every file hash are checked before the snapshot becomes usable.
Local source files are also checked against the built manifest, so local edits
cannot accidentally run with an outdated snapshot.

These pins detect corruption and mixed publication revisions. They do **not**
authenticate a hostile replacement of the initial preseed itself. HTTP, a
compromised initial URL, or deliberate TLS verification bypass can compromise
the entire installer. Authenticate the initial source out of band or use trusted
media / correctly validated HTTPS. Prefer immutable Git commit URLs for releases.

The repository fetch layer requires HTTPS certificate verification. Explicit
legacy TLS bypass requests are rejected, not silently honored. An installer
wget without usable certificate validation also fails closed. The initial
preseed retrieval belongs to the installer image; validate its trust settings
before this code can execute.

Redirects are resolved from response headers. Non-HTTP(S) final sources, excessive
redirects and HTTPS downgrades are not accepted. Because wget follows redirects
internally, a rejected downgrade may already have caused a request, but its body
is never published as an accepted repository file. No URL credentials are
supported; do not put passwords or bearer tokens in query strings or boot args.

## Runtime handling

Runtime state and caches are under a private installer directory. Downloads use
private temporary files, atomic replacement, bounded connection timeouts/retries
and one cache keyed by the full normalized source. Once the snapshot is ready,
missing assets cannot fall back to a different moving remote revision. The
snapshot and transport are reusable within the same installation.

The initial preseed is intentionally fetched once more by the bootstrap resolver
to learn its effective redirect destination. Repository asset payloads are then
fetched as one archive plus one manifest, not repeatedly file by file. Cache
reuse does not extend across boots or across unrelated repositories.

Source path traversal, ambiguous file/url selections, unsafe local paths and
symlink escapes are rejected. The snapshot is regular-file-only. Full initial
URL schemes and absolute local filenames are required by this repository;
installer shorthand such as a bare hostname is not its source contract.

## External vendor artifacts and repository authentication

Payload members and external vendor data remain separate APIs. A missing pinned
payload member cannot fall back to a moving URL. Codex binary archives retain
their configured SHA-256 and size bounds; the repository revision is pinned.
Mullvad retains verification against its pinned code-signing key fingerprint.

### Explicit CUDA-legacy authentication exception (R4)

The `addon/cuda-legacy` class is architecture-limited to amd64 and uses exactly
NVIDIA's Debian 12 x86_64 CUDA archive. Selecting this class explicitly authorizes:

```text
deb [arch=amd64 trusted=yes allow-insecure=yes allow-weak=yes allow-downgrade-to-insecure=yes check-valid-until=no check-date=no] https://developer.download.nvidia.com/compute/cuda/repos/debian12/x86_64/ /
```

No key download, fingerprint pin, signature validation prerequisite or custom
Sequoia policy blocks this class. APT may still emit verifier diagnostics, but
SHA-1, unrecognized signing keys, unsigned metadata and stale metadata are not
acceptance gates for this source. This is **not** a cryptographic fix for SHA-1:
it intentionally bypasses archive authentication and freshness protection for
this one selected archive. A compromised origin, mirror or intercepted trusted
TLS endpoint could therefore supply malicious or replayed packages.

The exception is confined to the source entry, staged before pkgsel and restored
when late package repair needs it. The installer never enables a global
AllowInsecureRepositories, AllowUnauthenticated or TLS bypass and never changes
the system crypto policy. HTTPS certificate verification remains enabled.
APT still checks package bytes against index checksums, but an unauthenticated
index cannot establish trustworthy package provenance. Missing indexes, network
failures and package checksum mismatches still fail the operation.

Both early and late staging use the same renderer and atomic publisher. General
metadata refresh temporarily hides the CUDA source and keeps its cached lists;
cleanup removes it after package repair and at finish-install. Old managed CUDA
keyrings are cleanup-only state, never prerequisites. Normal CUDA, Debian and
other third-party sources retain their own authentication policy.

Real Debian APT fixtures exercise acceptance of SHA-1 certificates/signatures,
unsigned and expired metadata, and signed-to-unsigned transitions. Strict-source
controls reject those conditions; mixed-source tests demonstrate that another
unsigned or SHA-1 repository still fails. Corrupted package downloads still fail.
See `docs/CUDA-LEGACY-TRUST-R4.md` for scope and operational details.

The intentional Debian suite priorities remain Forky 900, Trixie 400, Sid 100 and
Experimental 1. Existing package-specific exceptions remain explicit in
`hooks/target/etc/apt/preferences.d/default/`; they are not a reproducible full
package lock. Repository availability, dependency resolution and package scripts
must be accepted against the particular deployment snapshot. Serve immutable
source snapshots and retain resolved package versions with deployment evidence.

## Terminal failures and privileged publication

`common/lifecycle.sh` is the single fatal-state implementation, embedded before
bootstrap network access. First-failure records are atomically linked once with
mode 0600 in a private runtime directory. Fatal supervisors never return to d-i:
they stop the actual main-menu ancestor and wait without customization or reboot.
An already-fatal or interrupted mandatory phase cannot automatically resume.
Signals stop the supervised child tree before the terminal hold; no host-wide
process kill or PID-1 action is used. Do not SIGCONT the menu after failure.

A failure before writable target storage exists can only be retained in initrd
RAM and on the console. After a mounted target exists, diagnostics are also
copied privately to `/var/log/installer`. Power loss can destroy RAM-only evidence;
serial-console capture is an external deployment responsibility. The terminal
hold does not automatically unmount filesystems or close encryption mappings;
it avoids unsafe cleanup against uncertain partial state. Stop all work, export
evidence, and recover from trusted rescue media before re-provisioning.

Codex components are privately staged and validated before atomic publication.
Existing state is compared without running Git or code from that existing tree.
Only defined runtime-owned files/directories and managed links are allowed to
differ. Ownership, modes, hardlinks, revision and immutable contents remain checked.
Rollback removes only paths created by that transaction, never unrelated data.
The release record is published last. An interrupted installer is still terminal;
component convergence is not authorization to restart destructive phases.

## Credentials and personalized browser data

`/preseed.env` is trusted executable shell configuration. Both installer and
runtime readers require a regular non-symlink file owned by the effective
installation account (root in d-i), with one hard link and safe parent directories.
Mode 0400 or 0600 is preferred. Extra group/other read bits (including 0644) are
reduced to 0600 before sourcing; group/other writes, executable/special modes,
untrusted owners, symlinks and unsafe parents are rejected. A failed chmod is
fatal, never an authentication bypass. The checks use d-i-supported numeric ls
rather than the absent stat applet. Tests use the invoking UID for isolated
non-root fixtures. Prior exposure cannot be undone by changing mode.

An initial BOM and CRLF endings are normalized in a private temporary copy;
source output and syntax diagnostics are suppressed to avoid secret disclosure.
This remains trusted shell code, NOT a safe importer for malicious data. Do not
deploy a file written by an untrusted party or run with xtrace. Missing root
credentials fail before early disk planning; a blank root_password parameter is
an explicit invalid override, not an instruction to fall back. See
`docs/INITRD-CREDENTIAL-FIX-2026-09-06.md` for precedence and deployment.

Normalized bookmarks, contextual site grants and coverage reports are private
information even after tracking histories and the NoScript instance UUID are
removed. Restrict access to the personalized repository and installation server.
Exports are staged through directory/file-descriptor based checks and atomic,
non-clobbering publication; no browser database is rewritten offline.

DevTools is allowed by policy but is not started automatically. The helper refuses
root, keeps the browser sandbox, binds loopback and uses a separate private
profile. An open CDP endpoint has broad unauthenticated control over that profile;
do not expose it to the LAN, untrusted local users or untrusted tooling. AppArmor
exceptions cover only each browser's dedicated debug-state directory. Live kernel
enforcement has not been tested here.

Privacy Badger's no-DNT setting also disables GPC in the inspected upstream
implementation. Browser-native DNT defaults are false for fresh seeded profiles.
Do not infer anonymity or immunity to fingerprinting from these settings.

## What this refactor does not prove

The changes above are reviewed corrections, not a complete formal or runtime
security certification. Other target policy is inherited from the supplied tree;
preservation is not an endorsement that every original package, network rule,
third-party downloader, AppArmor profile or kernel tuning suits your deployment.
Review account/env files before publishing. Do not commit real enrollment keys,
passwords, private keys, tokens or production network secrets to a public repo.

Perl syntax checking can execute BEGIN blocks. Run the test/audit tools only on
trusted code in a disposable Linux environment. The included audits report
missing Perl dependencies and unrendered templates separately; neither is a
passing runtime test. The general audit performs structural systemd checks; seven rendered container
units additionally pass isolated `systemd-analyze verify` with dependency fixtures.
Neither check activates services or proves installed-target startup.

Upstream references consulted (2026-09-06):
- Debian installer, Using preseeding:
  https://www.debian.org/releases/forky/amd64/apbs02.en.html
- Debian installer, Advanced options:
  https://www.debian.org/releases/forky/amd64/apbs05.en.html
- Debian preseed source-location contract:
  https://sources.debian.org/src/preseed/1.122/README.preseed_fetch/
- GNU Wget TLS verification options:
  https://www.gnu.org/software/wget/manual/html_node/HTTPS-_0028SSL_002fTLS_0029-Options.html

Additional primary implementation references (consulted 2026-09-06):
- APT source-local security options: https://manpages.debian.org/testing/apt/sources.list.5.en.html
- APT archive authentication: https://manpages.debian.org/testing/apt/apt-secure.8.en.html
- APT insecure acquisition implementation: https://raw.githubusercontent.com/Debian/apt/main/apt-pkg/acquire-item.cc
- systemd filesystem restrictions and AF_UNIX: https://manpages.debian.org/testing/systemd/systemd.exec.5.en.html
- Chrome debug-profile boundary: https://developer.chrome.com/blog/remote-debugging-port
- uBOL managed settings: https://github.com/uBlockOrigin/uBOL-home/wiki/Managed-settings
- Privacy Badger managed schema: https://raw.githubusercontent.com/EFForg/privacybadger/master/src/data/schema.json
- Privacy Badger import merge: https://raw.githubusercontent.com/EFForg/privacybadger/master/src/js/storage.js
