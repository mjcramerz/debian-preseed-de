# Static inspection only

`AGENTS.override.md` permanently prohibits creating, provisioning, launching,
requesting or using disposable VMs, containers, chroots, sandbox images or
other disposable execution environments for work in this repository. Do not
propose an environment as a next step. Earlier image/VM instructions are
superseded by that prohibition.

Tests and validation commands must also never run on the development host.
This includes unittest discovery, importing a test or fixture, `make test`,
`make check`, `make validate`, audit tools, native syntax checks, AppArmor or
systemd validators, benchmarks and container smoke probes. No environment flag,
root/sudo fallback, namespace wrapper or alternate tool may bypass this rule.

The user-authorized offline AppArmor parser exception in `AGENTS.override.md`
permits `apparmor_parser -Q -K` with an explicit private configuration, staged
include tree and package feature/ABI data, a bounded timeout and one compile
job. It must not load kernel policy, read local host policy/configuration or
kernel features, write caches, install packages, or execute package scripts.
Staging policy support files as data is not an execution environment. Record
parser/support versions and any relocated ABI path. All other native checks
and test/fixture execution remain prohibited.

## Permitted work

Inspect source and supplied reports as data. Static AST parsing, source/diff
inspection and archive/hash comparison must not import or execute repository
modules, source shell snippets or invoke installed management helpers. Fixture
cases may be authored and reviewed as source, but remain unexecuted.

The permitted generation and static-audit paths remain separate:

- `make build` only serializes `d-i/forky/payload.tar.gz`,
  `d-i/forky/payload.manifest` and `d-i/forky/preseed.cfg`. It must not execute
  tests, validators, shell snippets, policy parsers or management helpers, or
  rewrite source inputs.
- `python3 -B tools/post_change_check.py` is the required changed-file static
  audit after edits and again after payload regeneration. It must not import
  repository modules, execute fixtures or contact host services.

`make inventory`, `tools/inventory.py` and `tools/inventory_apt.py` are manual
developer utilities only. Coding agents must not execute or integrate them
into builds, tests, installers, CI, hooks or runtime flows. The current manual
inventory product is only root `inventory.json`; `inventory-apt.json` is a
legacy artifact and must not be generated, read as a cache or required.

Inspect the chosen recipe and its full execution path before generation.
`make build` must not invoke inventory generation.

## Guards and evidence

Retain `tools/isolation.py`, `tools/test-init.py` and the Makefile guards.
Their presence is not authorization to prepare an image or execute a suite.
Do not weaken a guard or run its discovery/import path on the host.

Report exact static checks, changed paths and generated artifact hashes. State
which permitted offline parser checks ran and that fixtures and other native
checks were not run. Static inspection, offline compilation and serialization
consistency do not prove runtime behavior, loaded policy, boot, networking,
application launches, hardware performance, thermal stability or deployment.
