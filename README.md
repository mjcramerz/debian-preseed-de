# Debian Forky unattended desktop installation

Preseed sources, target configuration and deployment helpers for the labwc
Wayland desktop. The deployment target is Debian Forky with systemd 261.2.
Review the selected host profile, disk identifiers and credentials before use;
installation repartitions the selected disks.

The [2026-09-26 firstboot and AppArmor repair](docs/validation/firstboot-audit-20260926/README.md)
records the reproduced audit delivery failure, focused fixes, validation results,
and remaining installed-host checks for this snapshot.

The [2026-09-24 logging repair](docs/validation/history/LOGGING-REPAIR-20260924.md) documents the
shared tmpfiles prerequisite fix, unified `apps.log`, 2 MiB writer-driven rotation,
and current validation limits. It supersedes older logging descriptions.

The current [security repair and operating gates](docs/security-hardening.md)
cover A01-A09, rsyslog tmpfs, and the installer module/loading contract. Run `python3 -B tools/build.py`
after editing sources; run `python3 -B tools/build.py --check` before publishing.

## Source layout

- `d-i/forky/repo.env`: repository role, path contract and default selections.
- `d-i/forky/classes/`: package selections, class metadata and hardware assets.
- `d-i/forky/hosts/installer/`: shared settings, including `btrfs.env` and `f2fs.env`.
- `d-i/forky/hosts/profiles/`: ten directly editable host environments; the builder never overwrites them.
- `d-i/forky/hooks/installer/`: installer hooks and pre-pkgsel APT policy.
- `d-i/forky/hooks/target/`: target-side files and renderable configuration.
- `d-i/forky/scripts/`: small installer entrypoints and shared runtime modules, detailed below.
- `d-i/forky/tests/` and `tools/`: executable regression tests and build checks.
- `browser-config/`: private browser configuration inputs.

### Installer implementation

All executable installer sources live in `d-i/forky/`; there is no parallel
root authoring tree or profile generator. Edit the `.env` files where they are.
Shared paths, filesystem and logging policy remain in `hosts/installer/` and
`hosts/logging/`; per-host choices remain in `hosts/profiles/`.

```text
scripts/common/bootstrap.sh      shared, snapshot-backed module loader
scripts/common/lib.sh            ordered common entrypoint
scripts/common/modules/          paths, logging, profiles and class resolution
scripts/runtime/common.sh        shared storage-runtime entrypoint
scripts/runtime/modules/         arithmetic, identity, crypto and recipe helpers
scripts/desktop/components.sh    ordered desktop component entrypoint
scripts/desktop/components/      application, session and service definitions
scripts/late/devops.sh.tmpl       DevOps entrypoint and explicit main invocation
scripts/late/devops/             validation, toolchain and publication modules
```

Modules are actual runtime dependencies in the pinned payload, not fragments
concatenated back into large generated scripts. The explicit entrypoints define
load order. Missing dependencies fail closed; templates use the existing logging
renderer. The credential and debconf helpers are shared by the common and storage
runtimes instead of being embedded into both.

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

### Archive menu and Packer plugins

Run `compz` as the desktop user from the directory containing the files or
archives. Its menu selects compression, extraction, verification or listing;
extraction creates a folder named for each archive, resolves split volumes and
can unpack nested archives. It keeps source files and refuses to replace an
existing destination. Compression uses a tar container, with an optional GPG
AES-256 envelope. `compz --check` reports missing managed prerequisites, which
prevent the interactive menu from starting. RAR creation is offered
only where Debian provides the `rar` archiver; RAR extraction remains available
on arm64. The archive worker requires its AppArmor profile and an active systemd
user manager.

The DevOps installer authenticates the exact Packer plugin releases, installs
their binaries into the account's private plugin directory, then checks local
checksums and the managed HCL constraints. The installation does not invoke
`packer init`, which would repeat remote plugin discovery.

## Build and verify

Run from the repository root with Python 3 and the standard Debian tools:

```sh
make build
make check
make test
make audit
make validate
```

The builder refreshes `d-i/forky/preseed.cfg`, `payload.manifest` and
`payload.tar.gz`, checks module references, and refreshes the existing browser
artifacts and self-contained lifecycle bootstrap. **It never generates, repairs
or overwrites environment files or runtime modules.** Editing an environment
requires rebuilding the payload/pins before publishing; rebuilding packages your
edited bytes, it does not replace them with defaults. Do not hand-edit the three
snapshot products. The validation
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
