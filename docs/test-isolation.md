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

## Permitted work

Inspect source and supplied reports as data. Static AST parsing, source/diff
inspection and archive/hash comparison must not import or execute repository
modules, source shell snippets or invoke installed management helpers. Fixture
cases may be authored and reviewed as source, but remain unexecuted.

The two explicitly permitted generation commands remain separate:

- `make build` only serializes `d-i/forky/payload.tar.gz`,
  `d-i/forky/payload.manifest` and `d-i/forky/preseed.cfg`. It must not execute
  tests, validators, shell snippets, policy parsers or management helpers, or
  rewrite source inputs.
- `make inventory` checks both root JSON inventories against the payload hash.
  When regeneration is needed, it reads archive members as data, acquires
  public HTTPS APT metadata and generates only `inventory-apt.json` and
  `inventory.json`. It must not use host package state or package-management
  helpers. Direct invocation without `--refresh-apt` remains offline and writes
  only `inventory.json`.

Inspect the chosen recipe and its full execution path before generation.
Neither generation target invokes the other.

## Guards and evidence

Retain `tools/isolation.py`, `tools/test-init.py` and the Makefile guards.
Their presence is not authorization to prepare an image or execute a suite.
Do not weaken a guard or run its discovery/import path on the host.

Report exact static checks, changed paths and generated artifact hashes. State
that fixtures and native checks were not run. Static inspection and serialization
consistency do not prove runtime behavior, loaded policy, boot, networking,
application launches, hardware performance, thermal stability or deployment.
