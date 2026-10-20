# Installation download inventory

`make inventory` generates the paired root `inventory.json` and
`inventory-apt.json` for the existing `d-i/forky/payload.tar.gz`. It does not run `make build`.
`make build` writes only the three installer products and never runs inventory
generation. Run `make build` after editing installer inputs, then `make inventory`.
`tools/inventory.py` uses only the Python standard library. Download discovery
reads regular archive members as data, without extraction, installer execution,
loose-source reads or manifest pins as freshness evidence. Unbuilt source edits
deliberately do not change inventory.

## Payload freshness and performance

Both schema 3 documents contain the same `payload` object: `path`, compressed
byte `size`, and `sha256`. The generator hashes this one archive and checks the
existing documents' schema, payload identity and paired APT snapshot digest.
When they match it prints exactly:

```text
The generated inventory files are already up to date
```

That path performs no member scan, variable expansion, APT refresh or writes.
It does not open or hash individual source files. There is no `source_hashes`,
`_scan_cache` or `_discovery_hashes` collection. A missing, corrupt or mismatched
pair regenerates. The archive is scanned once, then public APT metadata is
acquired and both output candidates are assembled before publication. Release
and package-index acquisition use bounded worker pools; dependency lookup uses
indexed name/provider queries. Binary members, documentation and inactive backups
do not enter source discovery. Cross-file variable expansion uses declarations
from that same payload snapshot.

To refresh rolling repository metadata even when the payload has not changed:

```sh
python3 -I -B tools/inventory.py --refresh-apt --force
```

Payload freshness does not mean that an upstream rolling repository is unchanged.
The normal command intentionally has no time-based expiry. `--force` also permits
an explicit rescan after a generator implementation change; format or scanner
contract changes must advance the schema or `GENERATOR_VERSION`.

The JSON has no wall-clock generation timestamp. If its bytes are unchanged,
the serializer does not open it for writing or replace it; its inode and mtime
remain unchanged. Publication uses a private file and atomic replacement.
Inputs and outputs must not be symlinks. Private installer input basenames,
links, devices, duplicate/traversal archive paths and oversized members are
rejected. Expanded bytes and member counts are bounded while reading.
Credential values are not inventory inputs.

`scope.network_during_scan` describes archive discovery only. Public HTTPS APT
acquisition is the separate, explicitly requested `--refresh-apt` phase.

Writers share an exclusive directory lock, with no persistent lock file.
Handled publication failures restore previous bytes, modes or absence. An
uncertain restoration retains private `.inventory-recovery-*` evidence and
blocks retries. The files are replaced individually, not as a power-loss-atomic
pair; `apt_metadata_sha256` detects interrupted or mixed publication. Publish
the complete repository generation together for consumers.

## Consumer fields

| Field | Contents |
| --- | --- |
| `payload` | Archive path, compressed size and SHA-256, identical in both documents. |
| `scope` | Archive scan input, manifest location for installation, supported architectures and union-of-selections scope. |
| `schema` | Stable format name, version, and deterministic ordering contract. |
| `apt.repositories` | Configured base URLs, suites, components, class contexts, signing key URLs and index locations. |
| `apt.pin_rules` | Package selectors, Release/origin/version matches, priorities and their exact source locations. |
| `apt.packages` | Direct package/udeb/kernel requests, selection contexts, `candidate_indices` and preferred candidate summaries. |
| `apt.dependency_candidate_indices` | Indices into the paired APT snapshot for dependency/provider and bootstrap candidates. |
| `apt.metadata` | Reference to the paired snapshot, candidate count, scope match and signature-verification status. |
| `external_artifacts` | Archive/model/download endpoints with configured versions, digests and architecture where declared. |
| `git_repositories` | Git URLs, branches, commits when declared and authentication requirements. |
| `indirect_downloads` | Packer plugins, Rust toolchains/components, npm and Python dependencies, Discord distributions and CrowdSec collection discovery. |
| `classes` | Class requirements, exclusions and conditional APT preferences. |
| `repository_transfers` | Repository-relative files fetched by bootstrap, installer hooks and runtime module loaders. Literal paths are listed directly; helper expressions remain explicit as dynamic records. |
| `download_operations` | Source evidence for downloader and package-manager operations, including dynamic arguments. |
| `url_references` | URL references from active/configuration source text, schemas and runtime APIs; documentation-only and comment-only links are intentionally excluded, and these are not all installation downloads. |
| `coverage` | Deterministic counts for source files, repositories, requests, candidates, direct artifacts, Git repositories, indirect recipes and transfer evidence, plus known limits. |

The inventory includes the repository bootstrap transfers that precede normal
payload execution. `payload.manifest` and `payload.tar.gz` are listed as
generated bootstrap artifacts with their source locations; their generated
product hashes remain owned by `tools/build.py` and are not inferred from the
manifest digest column.

Candidate records appear once, in `inventory-apt.json` at `candidates.records`.
Every `candidate_indices` integer and preferred summary's `candidate_index`
addresses that zero-based array. The array belongs to the exact bytes identified
by `inventory.json`'s `apt_metadata_sha256`; indices must never be reused with a
different snapshot. No duplicate candidate objects or internal scanner cache is
embedded in `inventory.json`.

The readers in `debian-usb-preview` accept this schema 3 contract exclusively.
They validate the paired digest, payload hash, repository/request scope and
candidate references, then bind frozen preparation source to archive member
bytes before using declarations. Legacy inventories must be regenerated.

The union describes everything configured across classes and profiles; it is
not a package transaction for a particular machine. Mutually exclusive classes
remain separate selections. Private Git branches require the operator's normal
SSH identity; this tool does not connect to them or export private keys.

## Full APT package URLs

APT package filenames cannot be derived reliably from binary package names.
The archive's `Packages` entry supplies `Filename`, `Version`, `Architecture`,
size and checksums. A candidate's `url` is the configured archive URL joined to
that exact filename. Udebs use the `debian-installer/binary-ARCH/Packages` index.
See the [Debian repository format](https://wiki.debian.org/DebianRepository/Format).

One command acquires the metadata and generates both root JSON files, separately
from `make build`:

```sh
make inventory
```

The refresh reads public HTTPS `Release` and advertised compressed `Packages`
indexes. It does not execute APT, read host package lists, import installer
helpers, install packages or execute downloaded code. It writes the compact
metadata snapshot `inventory-apt.json` at the repository root. Private
temporary files are removed after acquisition. `make inventory` invokes
`tools/inventory.py --refresh-apt`; its payload fast path runs before acquisition.
A refresh failure returns an error and preserves
the existing outputs. To regenerate only `inventory.json` offline using the
existing APT snapshot, run `python3 -I -B tools/inventory.py` directly. This offline
mode writes only `inventory.json`; a mismatched/missing snapshot still needs
`make inventory` before the pair can be consumed. It cannot claim to refresh APT.

The APT snapshot uses its own structured schema. `request_set.packages` is the
requested `(name, type)` set, `release_files` records each Release file,
`package_indexes` records the advertised index and its byte/hash provenance,
and `candidates.records` contains the validated package and udeb archive rows.
`candidates.record_count` is a consistency check, not a solver result.

`Release` SHA-256 entries authenticate index **byte consistency** with the
fetched Release file. The collector does not verify OpenPGP signatures. The
record says so explicitly. A future downloader must verify the signed Release
against the configured archive keys before trusting its files. HTTPS transport,
content hashes, vendor signatures and local repository signing are separate
trust claims.

Repository snapshots are time-dependent. A refresh reports index/Release
acquisition failures and preserves the previous snapshot; an unavailable package
never gets an invented URL.
Refresh metadata before preparing a new mirror. Candidates contain dependency
relationships and virtual providers; the collector retains all alternatives
and essential/required/important bootstrap packages rather than claiming an
APT solver result. The machine's architecture, selected classes, pin rules,
explicit suite/version selectors and actual dependency constraints still apply.

`pin_priority` is calculated from the global APT preference set; a package
record's `priority` is its Debian classification (for example, `required` or
`optional`). Repositories include class-dependent priority overrides.
`source_selection` records preferred indexed candidates for each requesting
class and architecture, assuming the selected class's hardware requirements are
met. Hardware gates, such as the conditional NVIDIA opt-in deny policy, remain
explicit `activation` conditions on the original pin rules. No hardware probe,
APT dependency solver or installation is executed. Pin matching follows
[APT preference record order](https://manpages.debian.org/testing/apt/apt_preferences.5.en.html).
Virtual requests link to real provider packages with real archive URLs.

Rolling endpoints and indirect package managers are represented by typed
discovery recipes, with their configured versions, selections and source
locations. Resolve the relevant manifest, checksums, package dependencies or
collection index when preparing a download set. Nightly toolchains, vendor
`latest` endpoints and unlocked npm dependencies do not name a fixed set of
bytes for all future installations.

## Verification boundary

The ordinary offline generator and the metadata-acquiring `make inventory`
command are permitted checkout generation actions. Neither executes installer
code or host package-management helpers. Regression fixtures belong in the
[mandatory disposable environment](test-isolation.md), using the `tools-test`
stage and pattern `test_download_inventory.py`. Never execute that suite, test
discovery, host APT or installer helpers on the development host.
