# podbin service bridge guide

This guide covers the `podbin --service-*` commands that bridge into the
installer-managed `podsvc` rootless Podman service user.

## Purpose

The `podsvc` account owns the shared rootless Podman service environment, but
it remains locked and non-login. `podbin` bridges into that account with the
correct `HOME`, `XDG_RUNTIME_DIR`, and user D-Bus session settings so you do
not need to `su` into it directly.

## Discover the service environment

```sh
sudo podbin --service-env
```

This prints the live service facts:

- `PODMAN_SERVICE_USER`
- `PODMAN_SERVICE_UID`
- `PODMAN_SERVICE_GID`
- `PODMAN_SERVICE_HOME`
- `PODMAN_RUNTIME_DIR`
- `PODMAN_DBUS_SESSION_BUS_ADDRESS`
- `PODMAN_SOCKET_URI`

Use this output when you need to confirm the rootless runtime directory or the
exact Podman socket path exported by the managed install.

## Read-only Podman inspection

```sh
sudo podbin --service-podman info
sudo podbin --service-podman ps --all
sudo podbin --service-podman images
sudo podbin --service-podman inspect <name>
sudo podbin --service-podman logs <name>
sudo podbin --service-podman stats --no-stream <name>
sudo podbin --service-podman network ls
sudo podbin --service-podman volume ls
```

The generated sudoers policy keeps common low-risk inspection commands
passwordless for the daily account. Write-capable Podman operations still
require ordinary password-backed `sudo`.

## Inspect systemd user units

```sh
sudo podbin --service-systemctl status podman.socket
sudo podbin --service-systemctl status podman.service
sudo podbin --service-systemctl list-units
sudo podbin --service-systemctl list-timers
sudo podbin --service-systemctl cat podman.socket
sudo podbin --service-systemctl show podman.service
```

These commands run `systemctl --user` as the managed service account with the
correct runtime bus and user-manager context.

## Read recent logs

```sh
sudo podbin --service-journalctl -u podman.service -n 200
sudo podbin --service-journalctl -u podman.socket -n 200
```

Use this first when a rootless API socket or Quadlet-backed workload behaves
unexpectedly.

## Open an administrative shell

```sh
sudo podbin --service-shell
```

This opens a login shell inside the `podsvc` user environment. It is intended
for admin troubleshooting and remains on the password-backed sudo path.

## Suggested aliases for the daily account

```sh
alias podsvc-podman='sudo /usr/local/sbin/podbin --service-podman'
alias podsvc-systemctl='sudo /usr/local/sbin/podbin --service-systemctl'
alias podsvc-journal='sudo /usr/local/sbin/podbin --service-journalctl'
```

## Troubleshooting checklist

1. run `sudo podbin --service-env`
2. check `sudo podbin --service-systemctl status podman.socket`
3. inspect `sudo podbin --service-journalctl -u podman.service -n 200`
4. verify the rootless API with `sudo podbin --service-podman info`
5. use `sudo podbin --service-shell` only when the read-only bridge is not
   enough

## Operational guardrails

- do not convert `podsvc` into a normal login account
- keep the managed rootless config below `/data/config/podman`
- keep rootless state below `/pool/podman`
- prefer `podbin --service-*` over ad-hoc `runuser` wrappers so the managed
  runtime environment stays consistent
