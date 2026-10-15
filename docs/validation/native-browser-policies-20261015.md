# Native browser policy ownership — 2026-10-15

## Requested change and preservation

Removed `browser-config/policies.json`, its now-empty directory, and
`tools/build_browser_config.py`. The native browser files under
`d-i/forky/hooks/target` are authoritative. This supersedes the generator
workflow described in earlier browser validation reports; those reports remain
historical evidence.

Before deletion, standard-library JSON/text inspection compared all seven
canonical sections with the 20 installed-path policy files for Vivaldi,
Chromium, Edge and Chrome. Every JSON value and serialized byte agreed,
including Edge's separate security/telemetry settings and Vivaldi's Proton VPN
removal entry. The generator's three profile preference outputs were also
compared with the existing native preference files.

All 23 native files retain their original bytes. Existing recommended defaults
remain recommended, and existing profile seeds remain native preference files.
There is no change to browser behavior, proxy configuration, Tor/Mullvad
policies, AppArmor, or private Xwayland in this refactor.

## Wiring

`tools/check_browser_policies.py` reads native policy JSON and proxy JSON
templates. It has no generation or write path. It preserves the existing
extension installation constraints and recommended-policy checks, and rejects
duplicate keys within files or across files in the same policy scope. Reads
are bounded; symbolic links, non-object JSON and missing required files fail.
This checks repository contracts, not every vendor's version-specific schema.

`tools/check_build.py` and `tools/validate.py` now call that checker. Existing
regressions read and mutate native fixture files instead of a separate
canonical input. They cover preserved settings, direct installer staging,
Vivaldi-only Proton removal, user-adjustable privacy extensions, independent
native edits, read-only validation, invalid JSON/UTF-8, duplicate definitions,
missing files, symlinks and the read bound. Repository-copy fixtures no longer
require the removed directory. README and BUILD-STATUS describe native editing.

## Completed static inspection

- Parsed seven changed Python files with standard-library AST only.
- Confirmed all 23 native policy/preference files match the pre-deletion hashes.
- Parsed 24 native policy JSON/template files and checked duplicate definitions
  within each browser's managed/recommended scope.
- Confirmed both checker callers and direct staging of all 23 preserved files.
- Found no active source, fixture, README or BUILD-STATUS references to the
  deleted directory or generator. Historical reports retain their old names.
- Inspected the checker AST for absence of generation/write calls.
- Restored the eight surviving pre-existing edited inputs' original modes;
  the new checker uses the removed generator's original source mode.
- `git --no-pager diff --check --no-ext-diff` completed without findings.

The independent sidecar failed during encrypted-context initialization, so no
child review result is claimed. No tests, validation entrypoint, native policy
parser, repository module, browser, installed helper or service manager was
executed. The mandatory disposable test environment is unavailable; updated
regression cases remain unexecuted.

## Installer artifacts

This refactor changes only repository tooling, documentation and excluded test
sources. Full archive/source/manifest comparison confirmed that the existing
1,783 payload members and 34,286,078 content bytes remain current. Member names,
regular-file types, normalized metadata, complete source inventory and all
preseed checksum pins agree. No artifact regeneration was necessary.

| File | SHA-256 |
| --- | --- |
| `d-i/forky/payload.tar.gz` | `2ebc08c6478e2fc82536c870237d44a031b277ca2d21872ef46f88491c576336` |
| `d-i/forky/payload.manifest` | `3721559c271a0ca4ec846c82f1d97a5dc16cf2cb09af9de7deb536cc930b85f2` |
| `d-i/forky/preseed.cfg` | `536d77c45db3f62b748429c5c9648416192ddb52abaa8670b63f7c67abd4a92e` |

No installed system was changed or deployed by this work. Browser runtime
acceptance remains separate from source preservation and archive parity.
