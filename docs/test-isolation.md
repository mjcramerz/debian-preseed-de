# Mandatory disposable test environment

Tests and validation commands must never run on the development host. This
includes direct unittest discovery, importing a test or fixture, `make test`,
the audit tools, build validation, and the Podman/Incus smoke probe.
`make build` is permitted: it only serializes the three installer products,
executes no validation or tests, and does not rewrite source files. Browser
policy generation is a separate explicit command. `make inventory` separately
serializes only root `inventory.json` from manifest-listed sources and the root
`inventory-apt.json` snapshot, without network access or installer code
execution. Neither serialization target invokes the other.

`AGENTS.override.md` defines the host-access prohibition. `tools/isolation.py`
enforces it before test imports. Makefile test/validation targets check it before
discovery. There is no environment flag, root/sudo fallback, or host execution
mode. A missing disposable image means **do not execute tests**.

## Environment contract

Native fixtures that read kernel-global procfs data or exercise privileged
kernel behavior require a disposable VM with its own kernel. Namespace checks
alone do not virtualize every procfs field. Prepare the rootless image described
below inside that VM; expose no host shares or host management sockets to the
suite. Review this boundary before any execution.

Provision an existing, approved Forky test image outside the test suite. Package
the source copy at `/opt/preseed-test-source`; exclude `.git`, `.build`, private
preseed inputs, SSH keys and credentials. The suite does not build an image,
compile dependencies, pull packages, or contact a host container daemon.

The image runtime must supply all of these boundaries:

- Rootless user namespace: namespace UID 0 maps to a nonzero outer UID.
- Private PID, network, IPC, mount, cgroup and UTS namespaces, all owned by the
  image's user namespace. Network has loopback only,
  with no external interfaces, host networking or forwarded host sockets.
- Read-only overlay image root; no host bind mounts, volumes, device passthrough,
  persistent writable mounts, `/etc/hosts`/resolver/hostname binds, or runtime
  sockets. Configuration belongs to the image.
- Private tmpfs mounts at `/workspace`, `/run`, `/tmp`, `/sys` and `/dev`, all
  `nosuid`. `/sys` contains no host sysfs or cgroup tree. Mount private procfs
  at `/proc` and private devpts if needed. Additional procfs mounts and procfs
  bind mounts are rejected. Use only private virtual devices needed by fixtures.
- No effective, permitted, inheritable or bounding process capabilities; set
  `no_new_privs`. Supply no host credentials or desktop/service environment.
- No installed `/usr/local` files or symlinks. Empty prefix directories are
  permitted. Distribution tools come from the image; managed helpers are
  explicitly copied or mocked in fixture trees.
- `/workspace` and its parents must be root-owned and not group/world-writable
  inside the user namespace. This preserves the APT helper's production path
  ownership checks. `/tmp` is private to this disposable environment.

The runtime must start `/usr/bin/python3 -I -B
/opt/preseed-test-source/tools/test-init.py STAGE` as its private PID 1. Supported
stages are `test`, `tools-test`, `check`, `build`, `audit`, and `validate`.
For the test stages, `--pattern test_NAME.py` selects a bounded suite.

The init checks the mount/user/capability boundary, names itself `preseed-tests`,
copies the image source into `/workspace/repository`, and runs an explicit
argument array with a minimal environment and private HOME. It forwards stop
signals to its own child process group and bounds each stage to one hour. All
fixture writes and generated artifacts stay inside the disposable environment.
No source or output directory from the host is mounted into the running suite.

An ordinary container's defaults may include host file binds, sysfs or cgroups;
those defaults do not satisfy this contract. The runtime's namespace and
network configuration and disposable VM boundary must also be reviewed before
execution. The guard is an
additional check, not a replacement for provisioning those boundaries.

## Reviewing without execution

On the development host, inspect source as data. Do not import repository
modules, source shell snippets, run test/validation Makefile recipes, execute syntax/audit
runners, use native policy parsers, or invoke installed management helpers.
Static AST parsing, source/diff inspection and archive/hash inspection must not
execute repository code. Report those activities as static inspection, not
passing tests or live acceptance.

After running a suite in an approved disposable environment, obtain logs and
artifacts through the environment's explicit export workflow after execution.
Record the image identity, stage, test count, skips and outcome. Do not infer a
successful host deployment or policy load from a fixture result.
