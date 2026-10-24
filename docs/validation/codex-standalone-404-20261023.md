# Codex standalone installer HTTP 404 correction — 2026-10-23

## Reported failure and public endpoint evidence

The user reported `codex-standalone-install` failing with curl exit 22 and
HTTP 404. The helper, its policy allowlist and all ten host profiles used
`https://chatgpt.com/codex/install.sh`. OpenAI's CLI documentation still named
that address during this investigation, but opening the actual script address
returned HTTP 404.

- Documentation: <https://learn.chatgpt.com/docs/codex/cli>
- Official source:
  <https://github.com/openai/codex/blob/89461ea6833832b0551ce24ee32205824d5c108d/scripts/install/install.sh>
- Replacement download:
  <https://raw.githubusercontent.com/openai/codex/89461ea6833832b0551ce24ee32205824d5c108d/scripts/install/install.sh>

A bounded read-only HTTPS acquisition of that immutable source returned HTTP
200 and 42,779 bytes. Its source revision is
`89461ea6833832b0551ce24ee32205824d5c108d`, dated
`2026-10-19T00:13:28Z`. Its SHA-256 is
`95d14ccaba915e52a3f0cc590638ca5ac510086ff6a23dc9ac9f77e957403a93`.
The script was read as data, not executed. The local digest pin establishes
consistency with those reviewed bytes; it is not a separate vendor signature.

Both official release catalogs also returned HTTP 200 and identified
`rust-v0.164.0`:

- <https://releases.openai.com/codex/channels/latest>
- <https://api.github.com/repos/openai/codex/releases/latest>

Read-only HEAD requests returned HTTP 200 for the selected Linux package and
its checksum file. The advertised lengths were 162,338,756 and 3,095 bytes:

- <https://releases.openai.com/codex/releases/0.164.0/codex-package-x86_64-unknown-linux-musl.tar.gz>
- <https://releases.openai.com/codex/releases/0.164.0/codex-package_SHA256SUMS>

These endpoint observations establish availability at investigation time. No
package binary was downloaded or executed, and future endpoint availability
is not established.

## Production changes and installation contract

- `d-i/forky/hooks/target/usr/local/bin/codex-standalone-install`: accept only
  the immutable official source above; check its pinned SHA-256 before
  execution. Disable curl configuration inheritance, retry acquisition errors
  up to three times, and replace the helper's fixed 300-second transfer clock
  with a 300-second low-speed window. HTTPS, bounded redirects and the existing
  one-MiB script size ceiling remain enforced.
- `d-i/forky/scripts/late/devops/policy-resolution.sh.tmpl`: use the same
  immutable source in the policy allowlist.
- `d-i/forky/scripts/late/codex-installer-session.py`: remove the default
  1,800-second supervisor clock. Explicit fixture deadlines remain supported;
  signal handling, the five-second stop budget and private-runtime cleanup
  are unchanged.
- `d-i/forky/hosts/profiles/`: update the URL in `btrfs-de.env`,
  `btrfs-de-duo.env`, `btrfs-de-p15s.env`, `btrfs-de-p15s-duo.env`,
  `btrfs-de-flex.env`, `btrfs-de-flex-duo.env`, `f2fs-de-hp14.env`,
  `f2fs-de-hp14-duo.env`, `f2fs-de-x360.env` and `f2fs-de-x360-duo.env`.

The reviewed upstream script accepts the existing `CODEX_NON_INTERACTIVE=1`,
private `HOME`, staging `CODEX_HOME` and `CODEX_INSTALL_DIR`. Its package tree
is still `packages/standalone/releases/<version>-<target>` with
`current/bin/codex`. The wrapper still normalizes the staged absolute current
link before relocating the package cache, validates publication, and runs as
the desktop account through the existing root supervisor. The separately
pinned managed custom Codex release remains an independent installation.

The upstream script retains its own OpenAI release metadata and asset request
timeouts and GitHub fallback. This change removes the two local total clocks;
it does not claim to remove every timeout inside upstream code. Binary
selection still follows the official latest channel without forcing
`CODEX_RELEASE` or changing the account's shell configuration.

## Fixture maintenance

`d-i/forky/tests/test_codex_installer_session.py` uses the replacement URL.
`d-i/forky/tests/test_codex_standalone_chroot.py` models the reviewed digest
with the fixture script's actual SHA-256 and includes a corruption case that
requires rejection before script execution or package publication. Its
fixture supplies `sha256sum` inside the chroot. Neither fixture was executed.

## Recorded validation

Base revision: `5926f21a0ac7c8ef331cc4011c3e7fc06c01cffa`, branch `mcr/main`.
The source fingerprint covers the thirteen production paths and two fixture
paths above, sorted as `path + NUL + bytes + NUL`:
`f0ea48ffae65c657a5be13646fa2e3d34ab411a237038ccb697d048e0f84b3d8`.

- `git diff --check`: completed without errors.
- Inline `/usr/bin/python3 -I -S -B -`: parsed the supervisor and two fixtures
  using standard-library `ast.parse`; tokenized the helper and policy template
  as data using `shlex`. No repository module was imported or executed.
  Tokenization is not a native shell syntax or runtime check.
- The same inspection confirmed all ten profile values match the helper and
  policy URL, the digest check precedes downloaded script execution, the
  helper has no fixed total transfer clock, and the supervisor's default
  timeout is `None` while its stop budget remains five seconds.
- `make build PYTHON=/usr/bin/python3`: completed, 1,829 payload files. Its
  Makefile recipe, complete builder and publication helper were inspected
  before execution. This command serializes the three products below.
- A separate bounded standard-library archive/hash inspection compared all
  1,829 members with current source bytes and manifest hashes: 34,861,268
  expanded bytes matched. Archive/manifest/bootstrap-source preseed pins
  match, and private input names are absent from the archive.

| Product | SHA-256 |
| --- | --- |
| `d-i/forky/payload.tar.gz` | `aaf4442fa57b894b34a0b3f93ec6efbc59d85d8ed02faa36e7890cf7925a3bc5` |
| `d-i/forky/payload.manifest` | `93b82ac3beb6cb35a8b7b10da9e24cda725b212ea8c5b3b9dc5b417c9c187f15` |
| `d-i/forky/preseed.cfg` | `191bf8b61e9637f38b8b52931fe4a6b8dc8577b011d2e68b4a50b887b145f88c` |

The declared target remains Debian Forky, Python 3.14 and systemd 262. No
installed target package versions were queried. No test suite, installer,
downloaded script, Codex binary, native shell/policy validator, host service
operation, credential operation or deployment was run. The attempted
independent sidecar could not initialize because of encrypted-content
hydration; no independent review is claimed. Root inventories remain separate,
stale generation products. Fresh target installation remains unverified.
