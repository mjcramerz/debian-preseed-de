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

## External vendor artifacts and the CUDA-legacy trust exception

External HTTPS data and checksum-pinned repository members are separate APIs.
A missing validated payload member still fails closed; it cannot silently fetch
from a moving repository. External-data fetches do not inherit the optional
repository transport TLS bypass. These APIs remain unchanged in this pass.

Explicit `addon/cuda-legacy` selection authorizes a different policy for exactly
`https://developer.download.nvidia.com/compute/cuda/repos/debian12/x86_64/`, suite
`/`, architecture `amd64`. Its temporary source has `trusted=yes`,
`allow-insecure=yes`, `allow-weak=yes`, `allow-downgrade-to-insecure=yes`,
`check-valid-until=no` and `check-date=no`. It has no Signed-By restriction, key
fetch, default-policy probe or Sequoia policy-file prerequisite. The legacy
strict-first/fingerprint/self-certification fallback and its deadline are removed.
APT may emit a verification warning, but repository authentication is not a
prerequisite for accepting that source or downloading its packages unattended.

**This removes archive authentication and metadata freshness protection for that
source.** Missing, weak or rejected signatures are intentionally tolerated.
HTTPS certificate validation and available package checksums are still enabled,
and missing indexes, transport failures and corrupt package bytes still fail.
Checksums from unauthenticated metadata are not proof of publisher identity;
HTTPS alone is not equivalent to signed archive verification. A compromised
origin or trusted TLS interception can supply executable packages to the target.
This is the operator-requested compatibility tradeoff, not a secure SHA-1 upgrade.

The exception is in one source entry, not system-wide APT options or Sequoia
policy. The source renderer rejects other origins/suites/components. The hook
stages it only when the class is selected; explicit selection does not require
NVIDIA hardware detection. Updates for this source are isolated from other
sources. General late-command updates temporarily hide it while retaining its
cached package indexes. The source and obsolete dedicated key are removed after
package repair; finish-install also removes legacy source remnants before source
modernization. No permanent insecure NVIDIA source is installed by this change.
An administrator intentionally re-enabling it later must review the same risk.

See `docs/CUDA-LEGACY-SECOND-PASS-2026-09-06.md` and the real-APT regression fixtures
for scope, behavior and limitations. Ordinary signed sources still reject the
wrong key; an ordinary unsigned source fails even alongside the trusted fixture.

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
