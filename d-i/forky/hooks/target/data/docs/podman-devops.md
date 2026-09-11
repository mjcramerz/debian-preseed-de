# Managed rootless Podman and Docker clients

## Authority and scope

This is one shared, rootless Podman engine, not a rootful daemon and not a
privileged command broker. Its operating-system identity is `devops:devops`.
The installer creates the system account with a locked password,
`/usr/sbin/nologin`, no supplementary groups, and no SSH access (`DenyUsers`).
It does not create `podsvc`, install container SSH keys, or grant container
management through sudo. Existing desktop administrator rights are unchanged.

Every member of the existing `devops` group can fully control this engine via
its Unix socket. This is intentionally a **trusted operator group**, not
read-only access or multi-tenant isolation. The API can execute arbitrary code
as the service UID, read files that UID can access, and control all shared
containers and secrets. Because the service's primary group is `devops`, this
also includes existing group-shared DevOps files. No-login prevents account
logins; it cannot prevent code execution intentionally provided by the API.
Do not expose the socket to untrusted containers or users. Rootless operation
reduces host privilege; it is not protection against kernel vulnerabilities.

The NSS home field is `/nonexistent`, and that path must not exist.
`useradd --system --no-create-home` copies no skeleton. The former
`/data/accounts/devops` layout is rejected rather than retained as a disguised
home. A linger record, `user@<uid>.service`, runtime user bus, and systemd-user
runtime state are forbidden. PID 1 starts the API directly as `User=devops`;
there is no devops login or PAM session. Immutable configuration is root-owned
under `/etc`; only explicit runtime and pool-storage leaves belong to devops.
Direct systemd/Quadlet administration remains an administrator operation.

## Layout and native configuration

| Path | Purpose | Owner / mode |
| --- | --- | --- |
| `/nonexistent` | Passwd home sentinel; it must not exist | absent |
| `/etc/podman-devops/server/containers` | Authoritative engine, storage and registry config | root:devops 0750; files 0640 |
| `/run/podman-devops` | Volatile system-service runtime; never `/run/user/<uid>` | devops:devops 0710 |
| `/run/podman-devops/podman.sock` | Native Libpod and Docker-compatible API | devops:devops 0660 |
| `/pool/podman` | Protected persistent root | root:root 0711 |
| `/pool/podman/storage` | Images and writable container layers | devops:devops 0700 |
| `/pool/podman/volumes` | Named volume data | devops:devops 0700 |
| `/pool/podman/networks` | Persistent Netavark network definitions | devops:devops 0700 |
| `/pool/podman/libpod` | Persistent engine metadata | devops:devops 0700 |
| `/pool/podman/tmp` | Image/build temporary data on pool storage | devops:devops 0700 |
| `/pool/podman/xdg-data` | Explicit non-home XDG data | devops:devops 0700 |
| `/pool/podman/xdg-cache` | Explicit non-home XDG cache | devops:devops 0700 |
| `/pool/podman/workspace` | Operator-shared build and bind-mount workspace | devops:devops 2770 |
| `/etc/podman-devops` | Client config, server config and layout manifest | root:devops 0750 |

`/pool` retains its existing group access but gains the sticky bit (3775),
preventing group members from replacing root-owned Podman/Incus pool roots.
The installer never recursively chowns container layers or volume contents.
Subordinate UID/GID mappings are allocated through shadow-utils, checked for
collisions with other ranges and real accounts, recorded, and checked at boot.
Do not change those mappings after storing container data.

Volatile namespace handles, the ephemeral registry-policy copy, and runtime
locks intentionally stay under `/run`; putting those objects on durable pool
storage would be incorrect. Registry credentials stay in each client's own
home. The only pool-shared files meant
for direct desktop manipulation are in `workspace`.

PID 1 delegates the API service cgroup; rootless Podman manages its child
cgroups through `cgroupfs` on unified cgroup v2. The engine also uses crun,
Netavark and pasta. `auto`
selects native OverlayFS on approved local filesystems (ext4, XFS, Btrfs, F2FS);
explicit `btrfs` requires Btrfs. Actual rootless storage initialization must
succeed at boot; there is no silent switch to vfs, another path, or rootful
execution. Remote/network filesystems are rejected. XFS must support d_type;
the runtime probe, not filesystem naming alone, decides actual compatibility.
Published non-privileged ports remain subject to the existing host firewall;
no host bridge forwarding exception or low-port sysctl relaxation is added.
Registry TLS verification and the packaged security defaults remain enabled.
Use fully qualified image names; no ambiguous search-registry fallback is set.

## Packages and minimum version

The addon installs `podman`, `docker-cli`, `docker-compose`,
`golang-github-containers-common`, `conmon`, `crun`, `uidmap`, `netavark`,
`aardvark-dns`, `passt`, `catatonit`, and `python3`.
Podman **5.8.6 or newer** is checked explicitly: the managed restart unit uses
upstream's boot-state filter and native `stop --service` behavior. Debian Forky
currently provides that version family. This is not a backport for Bookworm or
Trixie's older Podman. Package versions are resolved by the existing installer;
this change does not add a new container package repository.

Docker support means the genuine Debian Docker CLI and Compose plugin talking
to Podman's Docker-compatible API. It does **not** install dockerd, Docker
Swarm, a privileged Docker socket, or claim complete Docker/BuildKit API parity.
BuildKit/Bake defaults are disabled for ordinary compatible build paths.
Buildx-specific workflows, plugins and Docker-only extensions require separate
compatibility review. Direct Buildah, `podman unshare`, local mounts and other
non-remote Podman operations cannot be proxied by this API; they are deliberately
not disguised with sudo aliases.

## Installation and boot lifecycle

The late hook stages root-owned assets and runs `podman-devops-host setup` in
the offline target. The desktop account must already exist. The hook adds that
account to `devops` and refreshes its shell assets, even when only addon/podman
is selected. No service is started inside the installer chroot.

At boot, `podman-devops-bootstrap.service` verifies the manifest, locked
system account, subordinate mappings, permissions and storage identity, starts
the system-level `podman-devops.socket`, and queries the actual API for rootless
mode, delegated cgroupfs on cgroup v2, storage paths/driver, and Netavark. The
API service has a root-only `ExecStartPre` that repeats the read-only invariant
check before PID 1 drops directly to `User=devops`. No linger or user manager is
created.

The system socket activates the API without any desktop login. API restarts use
`KillMode=process` so unrelated container scopes are not killed. The boot/shutdown
unit restores `always` containers and eligible `unless-stopped` containers;
manually stopped `unless-stopped` containers remain stopped. Shutdown uses the
native service stop mode so it does not mark every workload manually stopped.
The rootful `podman.service/socket` and `docker.service/socket` are masked.
They are not an error fallback. Do not unmask them to repair a client problem.

Account/configuration/storage failures are fatal and logged, not swallowed.
Bootstrap retries are spaced 30 seconds apart; subprocess and service deadlines
bound a single attempt. API crash restarts have a start-rate limit. This is
reconciliation on boot/service start, not a continuous integrity monitor.
The root helpers use non-unlinked flock files, no-follow file access, safe
parent checks, atomic replace+fsync for managed files, and explicit child
cleanup. Setup requires a quiescent target, without unrelated concurrent account
provisioning. Existing conflicting identities or stores require migration.

Resource accounting/limits are on the delegated `podman-devops.service`
cgroup, including its rootless container children, not a service-user slice or
user manager. Defaults: CPUWeight 100,
IOWeight 100, TasksMax 8192, MemoryHigh 70%, MemoryMax 85%. Weight is relative,
not a fixed CPU/IO cap. Memory percentages refer to host RAM, not free RAM;
set smaller values in the host profile for shared/low-memory machines. Per
container defaults include a 2048 PID limit and 16 MiB capped k8s-file logs.
Operators can set tighter workload-specific limits. Journal events and service
logs are available; this is not fine-grained per-operator API auditing.

Do not add `NoNewPrivileges`, empty capability sets, `PrivateUsers`, or similar
blanket restrictions to the engine system service: subordinate-ID helpers need
their normal setuid behavior. The root bootstrap has its own restrictive
systemd sandbox. Container isolation remains the engine/runtime's job.

## Ordinary desktop commands (no sudo)

Open a new desktop session after group membership changes. The shell fragment
`/etc/skel-desktop/.profile.d/71-devops-de.sh` exports the client-native variables
`CONTAINER_HOST`, `DOCKER_HOST`, `CONTAINERS_CONF`, `PODMAN_COMPOSE_PROVIDER`,
`REGISTRY_AUTH_FILE`, `DOCKER_CONFIG`, `DOCKER_BUILDKIT`, and `COMPOSE_BAKE`.
It leaves the desktop HOME, XDG_RUNTIME_DIR and D-Bus address intact. Its
`PODMAN_*_ROOT` and `PODMAN_SERVICE_*` values are documented path metadata, not
invented native engine configuration variables. Server-side
`CONTAINERS_STORAGE_CONF` and storage overrides are not exported to clients.

The `/usr/local/bin` wrappers also configure GUI/non-login callers themselves.
They exec native binaries, preserving stdin/stdout, signals and exit status.
Common conflicting engine selectors are cleared, endpoint overrides are
rejected at the managed entry point, and an unavailable or incorrectly owned
socket produces a clear failure rather than starting a personal/rootful store.
An intentional separate engine requires an explicit `/usr/bin/...` invocation.

```sh
podman info
podman ps --all
podman build -t localhost/myapp:dev .
podman volume create app-data
podman network create app-net
podman run -d --name app --restart=unless-stopped   --network app-net --volume app-data:/var/lib/app localhost/myapp:dev
podman logs --tail 100 --follow app
podman stop app
podman start app

docker version
docker ps -a
docker build -t localhost/myapp:dev .
docker compose up -d
docker-compose ps
podman compose ps
labwc-podman-menu
```

Local build contexts are sent through the API. **Bind-mount source paths are
resolved by the service account on the host**, not magically made readable
because the desktop client can read them. For shared source mounts:

```sh
umask 0002
mkdir -p /pool/podman/workspace/myapp
cd /pool/podman/workspace/myapp
# Put source and the Compose file here; use group-readable/writable permissions.
# Never chmod the entire desktop home or expose the service user's bus.
```

Named volumes are preferable for container-owned persistent data. Root in a
rootless container maps to devops; other container IDs map into its subordinate
ranges. `--userns=keep-id` refers to the engine identity, not the desktop UID.
Registry authentication remains client-owned: use `podman login` / `docker login`
with a password prompt or `--password-stdin`, not credentials in argv. The two
clients may keep separate native credential files. Do not mount those files or
the API socket into untrusted containers.

Aliases include `pps`, `pimages`, `pvolumes`, `pnetworks`, `pbuild`, `plogs`,
`pstats`, `pcompose`, `pinfo`, and `pcontainers`, in addition to the three client
names. They are conveniences; scripts should use the installed client wrappers.

## Fuzzel

`labwc-podman-menu` manages containers, images, volumes and networks; it offers
pull, run, local builds, Compose deployment, logs, inspection, stats and events.
Selections are mapped to validated IDs/names. Free-form text never becomes a
shell program. Destructive actions require explicit confirmation and never
implicitly force-delete running containers or prune all storage. Long-running
or interactive actions use a visible terminal. Errors are shown and exit codes
are retained. A private runtime flock prevents duplicate menus.

## Incus remains a separate trust boundary

The existing Zabbly package source, `/pool/incus` dir storage, packaged Web UI,
and confined per-user `incus` access remain in place. This refactor does not add
the desktop or devops service account to `incus-admin`. Incus is a privileged
host daemon, **not** the rootless Podman engine. The desktop uses its existing
`incus` group and `unix.socket.user`; bootstrap alone uses the admin socket.

The rewritten `incus-host-managed` parses a strict scalar configuration schema
rather than sourcing shell or constructing YAML. It checks package/socket
contracts, prepares only top-level storage, serializes bootstrap with flock,
then reconciles the storage pool, managed bridge and unprivileged default
profile separately. An existing pool no longer hides a missing bridge/profile.
Mismatched drivers, sources, network settings and privileged defaults fail
without resetting data. ETag-protected profile updates preserve unrelated
settings. Only 404 means missing; 409 is re-read and verified; 412 triggers a
bounded re-read/retry. API calls, asynchronous operations and readiness have
deadlines. Remote HTTPS API exposure is not silently adopted.

`--validate-config` is read-only and does not call the daemon.
`--prepare-install` prepares storage but never starts Incus in a chroot.
The restricted broker remains ordered after successful bootstrap. A failure
is visible through `incus-host-managed.service`, with spaced retries.

## Diagnostics, maintenance and migration

Ordinary users can inspect their engine with `podman info`, `podman events`,
`podman system df`, and `systemctl status podman-devops-bootstrap.service`.
An administrator can inspect detailed service logs and perform repairs:

```sh
journalctl -b -u podman-devops-bootstrap.service
journalctl -b -u podman-devops.service -u podman-devops-restart.service
systemctl status podman-devops.socket podman-devops.service podman-devops-restart.service
/usr/local/libexec/podman-devops-host check
systemctl restart podman-devops-bootstrap.service
journalctl -b -u incus-host-managed.service
/usr/local/libexec/incus-host-managed --validate-config
```

Those maintenance commands are root operations where necessary, **not** part
of daily container management. Do not directly edit hashed server config and
expect bootstrap to accept it. Change the source templates/profile, stop the
engine's workloads and system units in an approved maintenance window, and
rerun offline `setup` with the intended resource options. Runtime/mount ordering
and the immutable storage identity are verified again before activation.

Legacy `podsvc` installations or nonempty unmanaged stores are intentionally
refused. There is no in-place account rename, destructive store reset, automatic
UID remapping or recursive chown. Before moving an existing host, export image
artifacts and declarative deployment definitions, make application-consistent
volume backups, record secrets/networks and stop workloads. Restore into a
fresh devops engine with the new mappings and test ownership and application
recovery. A host administrator must explicitly retire the old account, bridge,
sudo grants and units after backups; simply unpacking this repository is not a
live-host migration. Keep the old environment available until recovery passes.

## Acceptance on an installed target

Repository tests do not replace a real Forky installation. Run the included
`tools/podman-incus-smoke.py` as the desktop user after first boot. By default
it only reads live state. `--exercise --image REGISTRY/IMAGE@sha256:DIGEST`
explicitly permits temporary build/run/volume/network/Compose fixtures. Use an
approved image containing `/bin/sh`; the script never prunes unrelated objects.
Review its cleanup failures rather than treating them as success.

Also verify a cold reboot without a desktop login, preservation of running
`unless-stopped` workloads and non-revival of manually stopped ones, API restart
without workload loss, inaccessible sockets from an unrelated account, actual
AppArmor denials, cgroup resource accounting, storage on the intended mounted
pool, and restricted Incus launch/network behavior. Test each supported
filesystem, architecture and host profile before fleet rollout.

## Upstream references (checked 2026-09-06)

- Podman API/socket security and Docker compatibility: https://docs.podman.io/en/latest/markdown/podman-system-service.1.html
- Native configuration: https://github.com/containers/common/blob/main/docs/containers.conf.5.md
- Storage configuration: https://github.com/containers/storage/blob/main/docs/containers-storage.conf.5.md
- Boot/shutdown behavior: https://github.com/containers/podman/blob/v5.8.6/contrib/systemd/system/podman-restart.service.in
- Service stop flag: https://github.com/containers/podman/blob/v5.8.6/cmd/podman/containers/stop.go
- Client-side login credentials: https://github.com/containers/podman/blob/v5.8.6/cmd/podman/login.go
- Incus Unix-socket authorization: https://linuxcontainers.org/incus/docs/main/authorization/
- Forky Podman package: https://packages.debian.org/forky/podman
- Standalone Docker client: https://packages.debian.org/forky/docker-cli
- Compose package: https://packages.debian.org/forky/docker-compose

## System-service correction (2026-09-10)

The locked `devops` UID intentionally has no `systemd --user` manager. The
bootstrap does not call `loginctl`, create linger state, connect to a user bus,
invoke a PAM user-switch helper, or stage anything under `.config/systemd`.
Rootless Podman runs in the dedicated
PID-1 unit `podman-devops.service` with a system socket under
`/run/podman-devops`; therefore system-wide desktop user units such as PipeWire
and WirePlumber are never loaded for this service account. Its clean remote API
probe runs as root and therefore cannot open a devops PAM session. The bootstrap
retains `ProtectSystem=strict`, `ProtectHome=yes`, `NoNewPrivileges=yes`,
and narrow `/run` write exceptions. Real installed-target startup/reboot
acceptance remains required.

Managed CLI dispatch now accounts for separate-valued global options before
checking common endpoint overrides. For example, `podman --log-level debug ps`
works without treating `debug` as the subcommand; appending `--url=...` before
`ps` is rejected. Docker's `--config DIR` and Compose's `-f FILE` are handled in
the same way. Arguments after the subcommand are passed through unchanged.
The wrapper is an operator-safety guard, not an authorization boundary against
users who can directly execute the native binaries. Inherited `DOCKER_TLS` is
cleared for the fixed local Unix socket, along with the existing context/TLS
selectors. Registry credentials and desktop identity remain client-owned.
