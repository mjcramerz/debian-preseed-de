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

The repository fetch layer verifies TLS unless explicitly given
`allow_unauthenticated_ssl` (bare or a true value) or
`debian-installer/allow_unauthenticated_ssl=true`. False values retain verification;
invalid boolean values fail. This flag is not an APT signature bypass and does
not change third-party application download policy. Initial preseed retrieval is
owned by the installer image; its trust settings must be correct before this code
can execute.

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

## External vendor artifacts and CUDA authentication

External HTTPS data and pinned repository members are separate APIs. A missing
validated payload member still fails closed; it cannot silently fetch from a
moving repository. NVIDIA's public key is fetched through the external-data API,
which does not inherit the repository's optional TLS verification bypass.

The temporary CUDA Debian 12 repository uses `Signed-By` with a dedicated keyring
and the full fingerprint `EB693B3035CD5710E231E123A4B469963BF863CC`. It no longer
uses `trusted=yes`, `allow-insecure=yes` or `allow-weak=yes`. ASCII-armored public
key boundary/size checks are diagnostics, not cryptographic authentication; APT's
signature and full-fingerprint verification supply authentication.

Modern APT can reject this legacy key's SHA-1 self-certification. The installer
first attempts an ordinary strict update. Only a diagnostic naming this exact
fingerprint, SHA1 and the certificate binding/PositiveCertification failure can
trigger a second, single-source update with a temporary Sequoia policy. That
policy extends second-preimage acceptance only until **2027-02-01** and still
rejects SHA-1 data/Release signatures. It preserves the other baseline rules.
An unrecognized baseline or another failure does not trigger a broad retry.

This is an explicit, bounded cryptographic compatibility tradeoff, not a claim
that SHA-1 is generally safe. Prefer a corrected upstream certificate as soon as
available; do not extend the deadline without review. Neither the system policy
nor general Debian updates inherit the exception. TLS errors, wrong signing keys,
modified metadata and expired signatures still fail. The temporary source is
hidden during general updates and removed after legacy CUDA repair.

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
passing runtime test. Systemd checks are structural, not `systemd-analyze verify`
on a booted target.

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
- NVIDIA key identity: https://packages.nvidia.com/keys/
- Legacy certificate issue: https://github.com/NVIDIA/cuda-repo-management/issues/34
- APT verifier: https://raw.githubusercontent.com/Debian/apt/main/methods/sqv.cc
- Sequoia crypto policy: https://docs.rs/sequoia-policy-config/latest/index.html
- Chrome debug-profile boundary: https://developer.chrome.com/blog/remote-debugging-port
- uBOL managed settings: https://github.com/uBlockOrigin/uBOL-home/wiki/Managed-settings
- Privacy Badger managed schema: https://raw.githubusercontent.com/EFForg/privacybadger/master/src/data/schema.json
- Privacy Badger import merge: https://raw.githubusercontent.com/EFForg/privacybadger/master/src/js/storage.js
