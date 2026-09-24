# Debian Forky unattended desktop installation

Preseed sources, target configuration and deployment helpers for the labwc
Wayland desktop. The deployment target is Debian Forky with systemd 261.2.
Review the selected host profile, disk identifiers and credentials before use;
installation repartitions the selected disks.

## Source layout

- `d-i/forky/repo.env`: repository role, path contract and default selections.
- `d-i/forky/classes/`: package selections, class metadata and hardware assets.
- `d-i/forky/hosts/installer/`: shared settings, including `btrfs.env` and `f2fs.env`.
- `d-i/forky/hosts/profiles/`: ten host profiles; review these for your hardware.
- `d-i/forky/hooks/installer/`: installer hooks and pre-pkgsel APT policy.
- `d-i/forky/hooks/target/`: target-side files and renderable configuration.
- `d-i/forky/scripts/`: installer, first-boot and desktop deployment logic.
- `d-i/forky/tests/` and `tools/`: executable regression tests and build checks.
- `browser-config/`: private browser configuration inputs.

Custom launchers are sourced from
`hooks/target/usr/local/share/applications/`. Package-owned launchers remain in
`/usr/share/applications`; synchronization reads local overrides first. Dynamic
DevOps configuration templates are under
`hooks/target/usr/local/share/devops/templates/` and are rendered into their
configured state directories, not installed as unresolved templates.

Application tuning uses systemd dash-prefix drop-ins:
`labwc-native-.service.d/`, `labwc-wayland-.service.d/`,
`labwc-electron-.service.d/` and `labwc-devops-.service.d/`.
These are prefix directories, not literal wildcard names. `labwc-session.target`
owns the desktop lifecycle and is bound to the compositor. Session clients
require an already-active target and stop with it rather than starting a new
compositor themselves. Private Xwayland remains limited to Zoom and Discord.
Firefox, Blender and Kdenlive are excluded by the pre-pkgsel APT policy.

## Build and verify

Run from the repository root with Python 3 and the standard Debian tools:

```sh
make build
make check
make test
make audit
make validate
```

The builder regenerates `d-i/forky/preseed.cfg`, `payload.manifest` and
`payload.tar.gz` together. Do not hand-edit these generated files. The validation
runner records results under `.build/validation/` by default. Parser checks
need the corresponding tools and Perl modules; missing dependencies must be
reported as blocked or skipped, not treated as successful execution.

Optional root-only, offline hardware-policy fixture checks:

```sh
python3 -B tools/check_hardware_tuning.py
```

These checks never start target units or load AppArmor policy into the kernel.
They do not replace an unattended VM install, boot/logout tests, enforcement
checks or testing on the intended GPU and storage hardware.

## Publish

Publish the complete rebuilt snapshot atomically. Prefer validated HTTPS or
trusted local installation media. This example is only for an isolated,
trusted lab network:

```sh
python3 -m http.server --bind 0.0.0.0 8000 --directory .
```

Point the installer at `/d-i/forky/preseed.cfg` on that server and supply the
appropriate class selection and deployment-specific credentials. Plain HTTP
does not authenticate the initial preseed: checksums embedded in it do not
repair that trust boundary. Restrict access to the repository and browser
inputs. Read `SECURITY.md` before deployment, especially the retained,
source-specific legacy CUDA authentication exception.
