# podbin wrapper guide

This guide is staged when the `podman` addon enables the managed `podbin`
workflow.

## What podbin manages

`/usr/local/sbin/podbin` sits on top of the installer-managed rootless Podman
layout. It has two distinct jobs:

1. create and maintain dedicated system Podman users below
   `/data/accounts/podman/users`
2. create and operate SSH-capable rootless containers for those users without
   turning them into normal login accounts

It also exposes a controlled bridge into the installer-managed `podsvc`
service account so the primary daily account can inspect the shared rootless
Podman service safely.

## Labwc desktop launcher

On managed Labwc desktops, press `Ctrl+Super+M`, then open **Container
Management** from **Computer Management** to reach the **Container
Management** Fuzzel launcher. It provides fixed menu actions for managed users,
container lifecycle, images, volumes, networks, pods, user systemd and journal
inspection, the shared `podsvc` service, pruning, and the destructive delete or
wipe flows.

The launcher always dispatches through `/usr/local/sbin/podbin` in
`labwc-terminal`. Passwordless sudo remains limited to the existing low-risk
start/connect and read-only service inspection commands; broader or destructive
actions prompt for the daily account's sudo password and retain Podbin's exact
confirmation tokens.

## Command summary

- `podbin --list-users`
- `podbin --create-user <username>`
- `podbin --import-user <username>`
- `podbin --diagnose-user <username>`
- `podbin --user-env <username>`
- `podbin --create-container <username> [container]`
- `podbin --import-containers <username> [container]`
- `podbin --list-containers <username>`
- `podbin --container-status <username> [container]`
- `podbin --start-container <username> [container]`
- `podbin --stop-container <username> [container]`
- `podbin --restart-container <username> [container]`
- `podbin --enable-container <username> [container]`
- `podbin --disable-container <username> [container]`
- `podbin --logs-container <username> [container]`
- `podbin --follow-logs <username> [container]`
- `podbin --inspect-container <username> [container]`
- `podbin --connect-container <username> [container]`
- `podbin --open-container <username> [container]`
- `podbin --delete-container <username> [container]`
- `podbin --list-images <username>`
- `podbin --list-volumes <username>`
- `podbin --list-networks <username>`
- `podbin --list-pods <username>`
- `podbin --prune-all <username>`
- `podbin --user-podman <username> <podman-args...>`
- `podbin --user-systemctl <username> <systemctl-user-args...>`
- `podbin --user-journalctl <username> <journalctl-user-args...>`
- `podbin --user-shell <username>`
- `podbin --wipe-all <username>`
- `podbin --service-env`
- `podbin --service-podman <podman-args...>`
- `podbin --service-systemctl <systemctl-user-args...>`
- `podbin --service-journalctl <journalctl-user-args...>`
- `podbin --service-shell`

## Root-admin lifecycle

Root or password-backed `sudo` is required for user and container creation,
deletion, and for opening an administrative shell inside the managed Podman
service account.

### Create a managed Podman user

```sh
sudo podbin --create-user alice
```

What this does:

- creates or validates a system account named `alice`
- keeps the shell locked to `/usr/sbin/nologin`
- stores managed config below `/data/config/podman/users/alice`
- stores rootless state below `/pool/podman/alice`
- keeps volatile `runroot` and libpod temporary state below `/run/user/<uid>`
- prepares the user manager and Quadlet layout needed for container services
- initializes Podman and verifies that no FUSE mount helper is active

Storage is selected from the backing filesystem. Podbin uses the native
`btrfs` containers/storage driver when `/pool/podman` is on Btrfs and native
kernel OverlayFS on supported non-Btrfs filesystems. It does not configure or
permit `fuse-overlayfs`.

The helper rejects normal login-style accounts, reserved names, login homes
under `/home`, and any account that would collide with the reserved `podsvc`
service account.

### Import an existing rootless Podman user

```sh
sudo podbin --import-user buildsvc
sudo podbin --import-containers buildsvc
```

Import is deliberately explicit. It accepts a locked system account
(`UID < UID_MIN`, primary group matching the account, and
`/usr/sbin/nologin`) whose home is outside `/home` and that already has a
rootless Podman state/config directory or a subordinate UID entry. The
account's existing home and container storage are not moved or replaced.
Podbin records the account as `imported` and operates its existing Podman
context directly. A user already under `/data/accounts/podman/users` is
repaired into the managed layout instead.

Imported containers are registered as `podman`-backend records. Their existing
Podman lifecycle, logs, inspection, deletion, and shell actions work from the
launcher; Quadlet enable/disable and the managed SSH connector are intentionally
not synthesized for containers whose original service contract is unknown.
Use `podbin --diagnose-user <username>` when an import or action reports a
missing user manager, subordinate ID range, or Podman runtime problem.

### Create a managed container

```sh
sudo podbin --create-container alice
```

When launched from Labwc **Container Management**, Fuzzel collects the
container name before opening the terminal-backed Podbin action. When the
optional name argument is omitted, the terminal-backed helper prompts for:

- image reference
- container SSH port
- host SSH port
- host bind address
- read-only root filesystem policy

Important defaults and constraints:

- default image: `localhost/podbin-runtime:trixie`
- default bind address: `127.0.0.1`
- default container SSH port: `2222`
- default runtime login user: `poduser`
- default runtime shell: `/bin/sh`
- default authorized keys path: `/home/poduser/.ssh`
- host ports must stay in the managed high-port range

When you keep the managed default image, `podbin` will build it on demand from
the staged templates if it is not already present.

The non-interactive name form is also available for scripts and the launcher:

```sh
sudo podbin --create-container alice devbox
```

### Inspect and operate containers

```sh
sudo podbin --list-containers alice
sudo podbin --container-status alice test
sudo podbin --start-container alice
sudo podbin --stop-container alice test
sudo podbin --restart-container alice test
sudo podbin --enable-container alice test
sudo podbin --disable-container alice test
sudo podbin --logs-container alice test
sudo podbin --inspect-container alice test
sudo podbin --connect-container alice
```

When a user has more than one managed container, omitting `[container]` opens
the interactive selector. Passing the container name makes the command
deterministic and suitable for operator scripts.

`--enable-container` enables and starts the generated user service at login or
linger startup. `--disable-container` disables and stops it.
`--start-container`, `--stop-container`, and `--restart-container` manage the
selected Quadlet-backed service. `--logs-container` shows the last 200 journal
records, while `--follow-logs` follows the service journal.
`--connect-container` starts the container if needed, then connects over SSH
with the managed podbin keypair and the dedicated known-hosts file.

### Open an interactive shell inside the container

```sh
sudo podbin --open-container alice
```

This does not enter as container root. The helper explicitly uses the managed
runtime UID/GID, so the session lands inside the container as `poduser`.

### Delete a container

```sh
sudo podbin --delete-container alice
```

Deletion is interactive on purpose. The helper asks for the exact confirmation
token `DELETE <user>/<container>` before it removes
the Quadlet unit, container, anonymous volumes, container data, and metadata.

### Inspect or prune user resources

```sh
sudo podbin --list-images alice
sudo podbin --list-volumes alice
sudo podbin --list-networks alice
sudo podbin --list-pods alice
sudo podbin --prune-all alice
sudo podbin --user-podman alice info
sudo podbin --user-systemctl alice status test.service
sudo podbin --user-journalctl alice -u test.service -n 200
```

`--prune-all` removes unused containers, pods, images, networks, volumes, and
abandoned build containers. It does not remove resources that are still in
use. The `--user-*` bridge commands run the requested tool inside the selected
locked rootless Podman account with its managed HOME, runtime directory, bus,
and temporary storage.

### Wipe all resources and delete a Podbin user

```sh
sudo podbin --wipe-all alice
```

This is intentionally destructive. The command requires the exact
confirmation token `WIPE alice`, stops and disables every managed Quadlet for
the account, runs `podman system reset --force`, terminates the user manager,
disables linger, removes the UID-specific Quadlet link, removes subordinate
UID/GID entries, deletes the system account and primary group, and removes the
validated per-user home, config, metadata, systemd, and storage trees.

The reserved installer-managed `podsvc` account is rejected and cannot be
removed through `--wipe-all`.

## Daily-account bridge to the managed podsvc service

The primary daily account can use `sudo` with `podbin --service-*` to inspect
or operate the installer-managed `podsvc` rootless Podman service without
logging in as `podsvc`.

Typical read-only inspection commands:

```sh
sudo podbin --service-env
sudo podbin --service-podman info
sudo podbin --service-podman ps --all
sudo podbin --service-podman images
sudo podbin --service-systemctl status podman.socket
sudo podbin --service-journalctl -u podman.service -n 200
```

For a deeper service-operations guide, read
`/data/docs/podbin-service-bridge.md`.

## Managed files and paths

- wrapper: `/usr/local/sbin/podbin`
- defaults: `/etc/default/podbin`
- per-user home root: `/data/accounts/podman/users`
- per-user config root: `/data/config/podman/users`
- per-user metadata root: `/data/config/podman/podbin/users`
- Podbin templates: `/data/config/podman/templates/podbin`
- rootless state root: `/pool/podman`
- per-user volatile runroot: `/run/user/<uid>/run`
- per-user volatile libpod temporary state: `/run/user/<uid>/libpod/tmp`
- Podbin SSH keypair: `/data/pki/ssh/podbin/podbin_ed25519`
- Podbin known hosts: `/data/config/podman/podbin/known_hosts`

## Security model

- the managed `podsvc` account stays locked and non-login
- the `podsvc` home and nested Podbin user-home root are mode `0711`, allowing
  traversal without directory listing, while service config and each workload
  home remain mode `0700`
- the managed runtime container user stays fixed to a non-root account
- reserved account names and low ports are rejected
- native `btrfs` or kernel `overlay` storage is enforced and FUSE mount helpers
  are rejected
- container metadata stays root-owned and mode `0600`
- the helper renders managed config from staged templates instead of ad-hoc
  heredocs
- SSH host keys for container connects are stored in the dedicated podbin
  known-hosts file, not in a caller's normal SSH profile

## Recommended quick start

```sh
sudo podbin --create-user alice
sudo podbin --create-container alice
sudo podbin --start-container alice
sudo podbin --connect-container alice
```

After that, the daily account can inspect the shared rootless Podman service
with `sudo podbin --service-*` commands while container creation and deletion
remain on the root-admin path.
