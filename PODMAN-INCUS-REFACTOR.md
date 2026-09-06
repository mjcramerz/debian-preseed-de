# Podman / Incus refactor - 2026-09-06

> Historical revision report. CUDA authentication descriptions and any prior
> test counts are superseded by the [second-pass report](docs/CUDA-LEGACY-SECOND-PASS-2026-09-06.md).
> Current evidence is `validation/summary.json`; the second pass also corrects
> the Podman bootstrap sandbox and client global-option handling.

## Delivery and scope

This tree is the complete refactored unattended-installation source, not just a
patch. Changes are restricted to Podman, Incus, their installer integration,
security policies, configuration, tests and documentation. The generated
`d-i/forky/payload.tar.gz`, `payload.manifest` and `preseed.cfg` have been rebuilt
and checked. Unrelated desktop, boot, storage-design and application features
were not redesigned.

Read the detailed operating guide at
`d-i/forky/hooks/target/data/docs/podman-devops.md` (installed as
`/data/docs/podman-devops.md`). The machine-readable before/after file ledger is
`validation/podman-incus/changes.json`.

## Podman architecture

The old privileged `podbin` broker and `podsvc` provisioning have been removed.
The installer creates a locked system account named `devops` with primary group
`devops`, `/usr/sbin/nologin`, no supplementary groups and explicit SSH denial.
Its fixed home is `/data/accounts/devops`. The home/configuration/unit directories
are root-owned; only necessary mutable leaves are owned by the service account.

A lingering systemd user manager owns the rootless engine, Unix socket and
boot/shutdown restart service. The socket is
`/data/accounts/devops/run/podman.sock`, owned by devops:devops with mode 0660.
The selected desktop user joins the existing devops group. `/usr/local/bin/podman`,
`docker` and `docker-compose` are unprivileged native-client wrappers; they never
use sudo, change the caller's UID, borrow the service session bus or silently fall
back to a different store. `docker compose` uses the packaged Compose plugin.

The shell integration is in the requested file:
`d-i/forky/hooks/target/etc/skel/.profile.d/71-devops-de.sh`. Native client variables,
fixed socket selection, aliases and clearly identified path metadata are provided.
The desktop HOME, XDG_RUNTIME_DIR and session bus stay unchanged. Engine-native
storage variables belong to the service, not the remote desktop client.

Persistent images/layers, named volumes, network definitions, engine metadata and
build temporary files are under `/pool/podman`. The shared bind-mount/build
workspace is `/pool/podman/workspace` (devops:devops 2770); private engine stores
remain 0700. Namespace handles, runtime locks and the session bus remain on
volatile `/run`, not durable pool storage. `/pool` gains sticky-bit protection
without removing its existing group access.

Native OverlayFS is the auto choice on approved local filesystems; explicit
Btrfs is supported only on Btrfs. Runtime startup verifies the actual driver,
rootless mode, cgroup v2, paths and Netavark. There is no rootful or vfs fallback.
Resource accounting and limits cover the entire service-user slice, including
container scopes: configurable CPU/IO weights, task and memory limits. The default
engine uses crun, Netavark/pasta, capped container log files and journal events.

## Security boundary and compatibility

Membership in devops grants full authority over this shared engine, including
arbitrary code execution as the devops UID. It is a trusted operator group, not
multi-tenant isolation. No-login prevents password/shell/SSH account logins; it
cannot prevent the code execution intentionally provided by container APIs.
Other existing devops-group resources are within that account's group authority.
There is no TCP API listener or new container-management sudo entitlement.

Docker support means the genuine Docker CLI and Compose using Podman's
Docker-compatible API. It does not mean dockerd, Swarm, Buildx/BuildKit feature
parity or a privileged Docker socket. Rootful Podman and Docker units are masked.
Direct Buildah, unshare, local mount operations and direct service-user
systemd/Quadlet administration are not disguised as remote API functionality.
Normal build, run, image, container, volume, network and Compose workflows are
provided through the shared API.

Podman >= 5.8.6 is enforced. The managed restart service follows upstream's
`should-start-on-boot=true` and native `stop --service` semantics, preserving
manually stopped unless-stopped containers. Forky's package page was checked as
5.8.6+ds1-2 on 2026-09-06; repository contents can subsequently change. This is
not an untested compatibility claim for Bookworm or Trixie's older Podman.

Bind-mount sources are resolved by the server account, not the desktop client.
Use the shared workspace or named volumes; do not make private desktop homes
world-readable. Native registry credentials stay client-owned.

## Reliability and Fuzzel

Root-managed setup uses bounded non-unlinked flock locks, no-follow path checks,
strict ownership and subordinate-ID validation, atomic same-directory replace,
fsync and changed-only writes. Existing mappings and store identity are retained.
There is no recursive chown of container data. Installer setup never starts a
service in the chroot. Boot reconciliation and a root-owned user-manager preflight
reject configuration/storage drift before normal activation, including linger
activation that happens independently of the bootstrap service.

API restart and workload shutdown are separate; API restarts preserve container
scopes. Subprocess timeouts/signals clean up process groups, including orphaned
pipe-holding descendants. Services have bounded attempts, spaced retries and
journal diagnostics. Integrity is checked at setup/start, not continuously.

The rewritten Fuzzel menu uses structured arguments, validated object IDs/names,
explicit destructive-action confirmation, bounded queries, a private runtime
lock and visible terminals for long/interactive work. It supports container,
image, volume and network management, builds, pulls, runs, Compose, logs and stats.
No menu text is evaluated as a shell program; there is no blanket prune action.

## Incus

Incus remains a distinct privileged host daemon with existing restricted desktop
access through group `incus`, not `incus-admin`. The service account is not given
Incus administrative membership. Existing package-source selection, Web UI and
`/pool/incus` dir storage remain in place.

The rewritten host bootstrap parses strict scalar configuration instead of
sourcing shell code, uses bounded Unix-socket HTTP, validates daemon/socket
contracts, and reconciles the pool, bridge and default unprivileged profile
separately. An existing pool no longer skips missing network/profile setup.
Only HTTP 404 means missing. Concurrent-create conflicts are reread and verified;
ETag/If-Match protects profile updates with bounded retry. Conflicting state fails
without data reset. Remote HTTPS API exposure is not silently adopted.
`--prepare-install` never activates Incus in a chroot; `--validate-config` is
read-only and makes no daemon calls.

## Validation actually performed

The original tree passed 305 tests. The final modified implementation passed
**382 tests, zero skipped**, including **77 new focused Podman/Incus tests**.
`python3 -B tools/validate.py` returned success for browser-check, build-check,
preseed-check, tests and audit. Logs and exact product hashes are in
`validation/summary.json` and `validation/tests.log`.

Focused checks include malformed configuration, UID/GID overlap, atomic-write
failure, symlinks/hardlinks, runtime socket identity, preservation of desktop
identity, Fuzzel injection/cancellation, interrupted child cleanup, partial Incus
initialization, HTTP/ETag handling and an actual local AF_UNIX test HTTP server.

Both modified AppArmor policy files compile with `apparmor_parser -Q -K`, using
the target policy include directory and installed Debian abstractions. No policy
was loaded into the running kernel. The parser's missing-cache-interface warning
is retained in the logs; this is not proof of runtime policy acceptance.

Seven rendered Podman/Incus/user-manager units pass `systemd-analyze verify` in an
isolated root. Vendor dependencies and executables are test fixtures, not running
services. This check validates rendered unit syntax and dependency construction;
it does not activate logind, Podman or Incus. The reproducible fixture checker is
`validation/podman-incus/verify-rendered-units.py`.

The general audit reports 154 blocked-dependency checks, 475 inventory-only
checks, 404 passes, 113 structure passes and 2 templates needing rendering. Those
non-pass categories are not converted into runtime passes; see the original audit
JSON. The additional rendered-unit check is separately recorded.

**Not performed:** a real Debian unattended install, target boot, rootless kernel
namespace/storage/network operation, container lifecycle on Podman/Incus, actual
cgroup enforcement, AppArmor enforcement, graphical Fuzzel interaction or reboot
recovery. These remain installed-target acceptance gates. This package is not
represented as production-certified or fully runtime-tested.

## Installed-target acceptance and migration

After installing an isolated test target, run as the authorized desktop user:

```sh
python3 tools/podman-incus-smoke.py --require-incus
```

Omit `--require-incus` when the Incus addon is not selected. This default probe is
read-only. A separate explicit `--exercise --image` mode accepts an approved,
fully qualified, digest-pinned image containing /bin/sh and basic tools; it creates
uniquely named test resources for build/run/volume/network/Compose checks and
cleans its own resources. It intentionally retains the pulled base image. See
`--help` and the operating guide. Reboot, installed AppArmor, DNS/port behavior and
full Incus VM/container lifecycle require the documented manual checks as well.

Legacy podsvc accounts or nonempty unmanaged stores are refused rather than
renamed, remapped or overwritten. Existing deployments require an explicit,
application-consistent backup/export and migration into the new engine. Read the
migration section before replacing an already deployed host. No live destructive
migration was attempted.
