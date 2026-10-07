# Modular installer revision - validation and delivery record

Date: 2026-09-24. This record supersedes the generated-layout delivery. Its earlier
results remain in `docs/validation/history/20260924-generated-layout/`, not in the
current results. All paths below are relative to the repository unless specified.

## Source authority and scope

The root `src/` directory and `tools/generate_installer.py` are removed. The served
`d-i/forky/` tree contains the actual editable installer and installed-system code.
All 24 environment files, including the ten complete profiles, are administrator
inputs. A build validates and packages their exact bytes; it does not regenerate
or normalize them. Invalid settings cause a diagnostic rather than a rewritten
profile. Changing a valid profile does not alter another host's file.

The 46 executable modules live in `scripts/common/modules/`,
`scripts/runtime/modules/`, `scripts/desktop/components/`, and
`scripts/late/devops/` beneath `d-i/forky/`. They are sourced at runtime through
explicit dependency lists, not concatenated into generated installer mirrors.
The largest module has 725 lines.

| Entrypoint beneath d-i/forky | Previous lines | Current lines |
|---|---:|---:|
| `scripts/common/lib.sh` | 4,996 | 26 |
| `scripts/runtime/common.sh` | 1,148 | 13 |
| `scripts/desktop/components.sh` | 4,899 | 18 |
| `scripts/late/devops.sh.tmpl` | 4,999 | 34 |

Credential, debconf, APT-source and lifecycle functions use shared canonical
helpers. Only `source.sh` retains a lifecycle bootstrap embed, because that code
must execute before an authenticated payload is available. The existing helper
synchronizer verifies that one necessary copy. Build generation remains for the
payload, manifest, pinned preseed command and existing browser/bootstrap products,
not for environment files or monolithic application scripts.

The shared loader stages modules privately, rejects unsafe path metadata, and
uses the already authenticated payload for remote installs. Missing authenticated
members never fall back to moving sources or stale staged files. Common/runtime
modules use the low-level transport to avoid a circular logging-renderer bootstrap;
desktop and DevOps modules use the existing logging renderer. Phase operations run
after definitions load; `devops_main` is an explicit action entrypoint.

The publisher accepts immutable bytes, checks destinations, publishes by rename,
verifies owner/mode/hash, and restores the prior snapshot on handled errors.
Environment destinations are explicitly forbidden. It does not provide multi-file
power-loss atomicity: build/check a complete release and deploy it with an atomic
directory switch. Do not rebuild a live served directory or edit during publication.

## Preservation

All 1,292 checked environment, target, hardware,
and private-Xwayland files are byte-identical to the prior delivery. All target
assets and all 24 environment files are unchanged. Hardware tuning values and
selection mappings were not retuned or replaced. Xwayland remains in its existing
private Zoom/Discord arrangement; no new vendor compilation or source patch was
introduced. Previous rsyslog tmpfs and A01-A09 fixes remain in the runtime modules
or unchanged target assets. The architecture section of `docs/security-hardening.md`
now describes real runtime modules; its operational security gates still apply.

The original uploaded ZIP contained 1,740 files. Of their original paths, 1,735
remain present; four historical reports are relocated unchanged to
`docs/validation/history/`; the old desktop components template is represented by
its entrypoint and runtime modules. `original-accounting.json` records every file.
This accounts for files, not an assertion that every original file is unchanged.

Function-definition inventories from the four former large implementations remain
present. This is a structural completeness check, not a substitute for runtime
behavior testing. Source/test/product SHA-256 values were frozen before the final
run: all 1,799 files remained unchanged through validation.

## Final full validation

Command, from the repository root:

```sh
python3 -B tools/validate.py --output-dir .build/validation --test-timeout 1500
```

| Stage | Result | Seconds | Evidence in docs/validation/latest |
|---|---|---:|---|
| browser-check | PASS | 0.722 | `browser-check.log` |
| build-check | PASS | 6.190 | `build-check.log` |
| preseed-check | PASS | 0.974 | `preseed-check.log` |
| shell-check | PASS | 3.376 | `shell-check.log` |
| tests | PASS | 748.827 | `tests.log` |
| tools-tests | PASS | 46.126 | `tools-tests.log` |
| audit | PASS | 1.840 | `audit.log` |

Installer suite: **2,663 run; 2,609 passed;
54 skipped; no failures or errors**. Tooling suite:
**193 run; 193 passed; 0 skipped;
no failures or errors**. Skips are listed with reasons in `skipped-tests.json` and
the full verbose test log. Targeted reruns are not added to these totals.

Shell validation: **338 files and 687 parser/dependency checks**,
with no failures. Build freshness, browser configuration and preseed checks pass.

New regression coverage includes real dash/BusyBox-ash module loading, a fresh
cached-hook process, argument/global preservation, missing and symlinked cache
members, unsafe staging directories, hardlinked destinations, traversal and remote
loading before payload authentication. These tests do not replace the loader with
a mock. Older isolated function tests read real module definitions into temporary
test-only views; they do not generate production code. The offline credential
diagnostic now imports only its canonical credential helper and diagnostic probes.

The real build is exercised on a copied repository after editing every environment
file; build and check preserve the exact edited bytes and modes. Additional tests
cover per-host edit independence, input rejection without rewriting, module
inventory, publication idempotence, rollback and forbidden environment outputs.

### Hardware fixture checks

Nine generated integration checks pass: system and user systemd unit verification,
and AppArmor syntax parsing, for Intel-only, NVIDIA-only and combined selections.
These fixtures replace executable commands with `/usr/bin/true` and provide
placeholder dependencies; AppArmor parsing uses offline options and does not load
kernel policy. See `hardware-fixtures/generated-integration.json` and its logs.
These results demonstrate generated fixture wiring and parser acceptance, not
actual device operation or performance.

### Audit categories

| Audit outcome | Files |
|---|---:|
| blocked-dependency | 158 |
| blocked-tool | 11 |
| inventory-only | 582 |
| pass | 531 |
| structure-pass | 215 |
| template-needs-render | 11 |

Inventory-only, blocked-dependency, blocked-tool, template and structure-only
outcomes are **not successful runtime tests**. Details are in `audit.json`.

## Environment and acceptance limits

Validation host: Debian 13.3 (Trixie); Python 3.13.5;
systemd 257 (257.9-1~deb13u1). This is **not a booted Forky/systemd 261.2 deployment**.
No real installer partitioning, physical hardware tuning/benchmark, live nftables
coexistence, TPM/Secure Boot enrollment transition, enforcing target AppArmor
policy, GUI/GPU launch or full service-activation acceptance was performed.
Offline tests and preserved settings cannot establish those runtime properties.
Follow the target operating and release gates in `docs/security-hardening.md`.

## Archive verification

The external `debian-preseed-de-modular-20260924.tar.gz.verification.json` records
archive file counts, repeat-packaging reproducibility, fresh-extraction build
freshness, source bytes and all payload manifest member digests. The checksum file
uses the delivered tarball basename. No `.git`, `.build`, Python cache, or root
`src/` tree is included. The tarball contains the complete repository, not a patch.
Extract into a fresh directory: overlaying the previous tree does not remove its
obsolete `src/` or generator files and is not a clean migration.

```sh
sha256sum -c debian-preseed-de-modular-20260924.tar.gz.sha256
tar -xzf debian-preseed-de-modular-20260924.tar.gz
cd debian-preseed-de
python3 -B tools/build.py --check
```

After directly editing an environment file, run `python3 -B tools/build.py` and
`python3 -B tools/build.py --check` to refresh and verify distribution pins. The
edited environment files remain authoritative and are not overwritten.
