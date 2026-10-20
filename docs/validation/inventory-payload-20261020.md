# Payload inventory redesign — 20 October 2026

## Implemented contract

`make inventory` uses the Python standard library and the existing built
`d-i/forky/payload.tar.gz`. Discovery reads bounded regular archive members as
data, without extraction or installer execution. It reads no loose installer
sources and maintains no per-file hashes or scanner caches in either JSON.

Both schema 3 documents contain the same archive path, compressed size and
SHA-256. `inventory.json` also pins the exact `inventory-apt.json` bytes.
Matching documents take the fast path before member scanning or network work.
The Makefile suppresses its recipe echo, so the only output is:

```text
The generated inventory files are already up to date
```

Stale generation scans the archive once, acquires public APT metadata with
bounded Release/index worker pools, resolves dependency/provider unions through
indexed SQLite lookups, and prepares both complete candidates before writing.
Candidate objects occur only in the APT snapshot; discovery uses zero-based
candidate indices. Writers share a directory lock. Handled publication failures
restore prior bytes/modes/absence; uncertain restoration retains private recovery
material and blocks retries. Individual file replacement is not atomic publication
of the pair across power loss; the paired digest detects mixed generations.

Debian USB readers require schema 3 exclusively. Archive bytes bind the complete
frozen preparation source, including supplemental policy constants. Managed
package, private runtime/repository and security-feed adapters consume that
in-memory source binding. The Python dependency recipe resolves indexed
candidates through the validated APT snapshot. No legacy source-hash fallback
remains. Downstream receipt hashes of prepared files retain their existing role.

## Recorded working trees

- Producer base: `caed1a3b97f181e46b95ac328e68f14509935833` on `mcr/main`.
- Producer source/fixture fingerprint:
  `d24ddef8bb604d5b4d298ed5b2a3956b1dab20d93c5d7564c2794f40b06d086d`.
  It covers, in order, `Makefile`, `AGENTS.override.md`,
  `docs/test-isolation.md`, `docs/download-inventory.md`, `tools/inventory.py`,
  `tools/inventory_apt.py`, `tools/publication.py`, and
  `tools/tests/test_download_inventory.py`.
- Consumer base: `69293b3c665ac20e92c3523075e688f0a6dd5dc9` on `mcr/main`,
  in `/home/mcramer/Workspace/debian-usb-preview`, with pre-existing user work
  preserved.
- Consumer source/fixture fingerprint:
  `dcf8a95faa3c5e907d17cbf1836d25c0c527f9e77ba46d9cdd437818f9001d3c`.
  Its ordered scope is the eight source paths below, the seven fixture paths
  below, then `docs/offline-preparation.md`.

Each fingerprint is SHA-256 of compact, sorted-key JSON containing the ordered
`{path, sha256}` records for its declared scope. This report and generated
artifacts are excluded from the source fingerprints.

## Generation and data evidence

Actual commands, all exited successfully:

```sh
make --no-print-directory inventory PYTHON=/usr/bin/python3
/usr/bin/python3 -I -B tools/inventory.py --force
make --no-print-directory inventory PYTHON=/usr/bin/python3
```

The initial command performed real public HTTPS acquisition: 29 Release files,
98 acquired indexes, zero acquisition errors and 21,460 retained candidates.
The explicit offline regeneration applied the final discovery metadata wording
without refreshing or replacing the APT snapshot. Final unchanged generation
took 1.087 seconds as reported by the execution tool and printed the exact
single line above. An earlier fast-path observation took 0.770 seconds.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `inventory.json` | 2,373,429 | `2e72bca9b6739a65a6e99b8bf3a8e9d217d4f77a22bf6970701be2b315141e83` |
| `inventory-apt.json` | 19,268,669 | `63a110f0ea29c807e38ac7d7861247f26820a7102ff494c4ad61bae1fd68b1f1` |
| `d-i/forky/payload.tar.gz` | 26,571,974 | `29586036bd43389e8e34a6e4181c76e2e5a5e4dbb609f9fe38e4f7513f132527` |
| `d-i/forky/payload.manifest` | 224,172 | `0116be68e8b513738e5159d159ccf82fd5e7fa3d12f6f318dfa8f27b1673d344` |
| `d-i/forky/preseed.cfg` | 96,407 | `be82be255ff5a4a93bfeba12ad7dac3f8cd0f0d6993dd72a4ece644880519839` |

The prior committed `inventory.json` was 26,048,848 bytes; the new discovery
document is 90.89% smaller. Both JSON files retained byte hashes, inodes and
nanosecond mtimes across final unchanged generation. No `.inventory-*`
temporary/recovery directory remained after successful generation.

Read-only data inspection, using standard-library scripts without importing
repository modules, established:

- Both documents identify the actual payload and the paired APT digest matches.
- The archive has 1,819 members and 34,729,703 member bytes. All archive member
  bytes match their loose published source inputs; the manifest member set and
  all its digests match. Installer products did not require rebuilding.
- Discovery scanned 1,789 text members and retained 346 relevant sources:
  680 direct package requests, 118 external artifacts, eight Git repositories
  and 15 indirect recipes across 29 APT repositories.
- All 21,607 candidate references are in bounds. All 2,080 preferred candidate
  references match their candidate package, version, repository and URL.
- Repository-definition hashes and normalized package request sets agree.
- Discovery has no old per-file provenance/cache collections or duplicated
  candidate objects. The only source-code reference to those old provenance
  keys in Debian USB is their explicit rejection check.

Static AST parsing succeeded for the producer modules/fixture and all 15
affected consumer Python files. `git diff --check` succeeded for producer
changes and the affected tracked consumer paths. Searches, archive comparisons,
JSON/hash inspection and AST parsing executed no repository modules.

## Changed paths

Producer: `Makefile`, `tools/inventory.py`, `tools/inventory_apt.py`,
`tools/tests/test_download_inventory.py`, `inventory.json`, `inventory-apt.json`,
`docs/download-inventory.md`, `docs/test-isolation.md`, `AGENTS.override.md`,
and this report. `tools/publication.py` was inspected and remains unchanged.

Consumer source paths, in fingerprint order:

1. `src/python/debian_usb/offline_source_inventory.py`
2. `src/python/debian_usb/offline_inventory_apt.py`
3. `src/python/debian_usb/offline_upstream_inventory.py`
4. `src/python/debian_usb/offline_inventory_managed.py`
5. `src/python/debian_usb/offline_inventory_private.py`
6. `src/python/debian_usb/offline_inventory_security.py`
7. `src/python/debian_usb/offline_private_repository.py`
8. `src/python/debian_usb/offline_inventory_recipes.py`

Consumer fixtures, in fingerprint order:

1. `tests/python/test_offline_upstream.py`
2. `tests/python/test_offline_inventory_apt.py`
3. `tests/python/test_offline_upstream_inventory.py`
4. `tests/python/test_offline_inventory_managed.py`
5. `tests/python/test_offline_inventory_private.py`
6. `tests/python/test_offline_inventory_security.py`
7. `tests/python/test_offline_private_repository.py`

Consumer documentation: `docs/offline-preparation.md`.

## Verification limits and use

No fixture/test suite was run, at the user's explicit direction. The failure,
concurrency and recovery fixtures are updated source, not executed acceptance
evidence. No disposable target image/package versions or native integration
results are claimed. No Offline ISO was built, booted or deployed. Static
consumer contract review and generated-data checks do not establish a complete
offline installation result.

Use `make build` after installer source edits, then `make inventory`. To refresh
rolling upstream metadata with an unchanged payload, explicitly run
`python3 -I -B tools/inventory.py --refresh-apt --force`. Payload freshness has
no time-based expiry. OpenPGP verification remains outside this discovery
collector; Debian USB's authenticated index resolver remains authoritative for
package acquisition. Commit/publish the schema 3 pair and matching consumer
changes together; the new reader intentionally rejects legacy inventories.
