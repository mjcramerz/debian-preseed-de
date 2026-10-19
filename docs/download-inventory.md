# Installation download inventory

`make inventory` refreshes root `inventory-apt.json`, then generates root
`inventory.json` from that snapshot. It does not run `make build`.
`make build` writes only the three installer products and never runs inventory
generation. Rebuild the payload separately when its manifest needs updating.
`tools/inventory.py` is a Python standard-library serializer. It reads the paths
in `d-i/forky/payload.manifest`; it does not use the manifest's digest column to
decide whether source files changed. It hashes their current bytes itself.
Installer code is never executed.

## Incremental generation

The first JSON field, `source_hashes`, maps download-relevant payload text paths
to SHA-256 hashes.
`_scan_cache` stores the corresponding per-file declarations. Every run hashes
the current files, scans changed/new files, reuses unchanged declarations and
removes deleted relevant manifest members. Binary assets are excluded. A
separate negative discovery cache avoids repeatedly parsing unchanged unrelated
text. Updating that optimization alone never replaces the inventory.
Cross-file variable expansion and repository aggregation are recomputed from
those declarations, so changing a version in one profile also changes URLs
declared in another file. A generator change invalidates the scan cache.

The JSON has no wall-clock generation timestamp. If its bytes are unchanged,
the serializer does not open it for writing or replace it; its inode and mtime
remain unchanged. Publication uses a private file and atomic replacement.
Sources, the manifest and the output must not be symlinks. Private installer
input basenames are rejected; credential values are not inventory inputs.

## Consumer fields

| Field | Contents |
| --- | --- |
| `scope` | Manifest, supported architectures, and union-of-selections scope. |
| `schema` | Stable format name, version, and deterministic ordering contract. |
| `apt.repositories` | Configured base URLs, suites, components, class contexts, signing key URLs and index locations. |
| `apt.pin_rules` | Package selectors, Release/origin/version matches, priorities and their exact source locations. |
| `apt.packages` | Direct package/udeb/kernel requests, selection contexts and indexed download candidates. |
| `apt.dependency_candidates` | The dependency/provider and bootstrap package union from acquired metadata. |
| `apt.metadata` | Index and Release hashes, acquisition failures and provenance. |
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
`tools/inventory.py --refresh-apt`, then consumes the refreshed snapshot when
generating `inventory.json`. A refresh failure returns an error and preserves
the existing outputs. To regenerate only `inventory.json` offline using the
existing APT snapshot, run `python3 -I -B tools/inventory.py` directly.

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
