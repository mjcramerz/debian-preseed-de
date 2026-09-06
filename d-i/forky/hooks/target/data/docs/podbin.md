# Legacy Podbin interface retired

The privileged multi-account/SSH bridge is no longer installed. There is no
Podbin sudoers entry and no service-account login shell. Use `podman`, `docker`,
`docker compose`, or `labwc-podman-menu` as the desktop user without sudo.

See `podman-devops.md` for the shared rootless engine, trust boundary, paths,
Docker compatibility limits, and an explicit legacy-data migration checklist.
