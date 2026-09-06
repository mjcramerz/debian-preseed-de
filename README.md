# debian-preseed-de

Debian unattended-install repository for **desktop systems**, refactored on
2026-09-06. It retains the supplied desktop layout and all 13 original hardware
profiles, while correcting CUDA transport/authentication, DKMS handling and
browser policy/export deployment. It is not a generic disk-safe installer.

Start with **[the refactor report](docs/REFACTOR-2026-09-06.md)** and
**[validation evidence and remaining acceptance work](docs/VALIDATION.md)**.
The complete validation pipeline passed 271 tests, with no skipped tests. This
is not a claim that a real installer boot or every bookmarked site was tested.

**Private build:** browser configuration and coverage data contain personal
bookmarks. Do not publish this personalized tree to a public repository or an
unrestricted web server. No reusable credentials are supplied by this refactor.

The Labwc desktop, desktop application classes, workstation developer tools, and their user units stay here. GitLab Runner, server-suite, web/database service classes and server-only profiles are not included. SSH, Podman, CrowdSec and workstation Aptly publishing remain where the original desktop used them.

## Build before publishing

The supplied snapshot is already built. After changing **any** runtime file,
profile, class, installer script or target asset, run from this repository root:

```sh
python3 -B tools/build.py
python3 -B tools/validate.py
```

Builds require Python 3.11 or newer and a POSIX shell on the publishing host.
The installer transport itself does not require Python or curl.

Commit or deploy the entire repository, including these generated files:

```text
d-i/forky/preseed.cfg
d-i/forky/payload.manifest
d-i/forky/payload.tar.gz
```

The generated preseed pins the bootstrap transport and complete payload with
SHA-256 hashes. Publish them together; do not deploy individual edited files over
a running installation, omit the payload, or replace the payload with a Git LFS
pointer. `python3 -B tools/build.py --check` detects stale generated files.
The complete pinned snapshot is fetched and validated before partitioning. Later
phases read its local cache instead of repeatedly downloading repository files.
The browser generator runs as part of this build. Its editable inputs are in
`browser-config/`; generated policies and exports live under `hooks/target/`.
This revision also changes security-sensitive target policy: review the report
before deploying. The temporary CUDA certificate compatibility exception expires
on **2027-02-01**, and is not a global APT authentication bypass.

## Repository layout

```text
.
|-- README.md
|-- SECURITY.md
|-- Makefile
|-- browser-config/            # private normalized bookmark and export inputs
|-- tools/                     # deterministic build and validation
|-- docs/                      # migration ledger, architecture and validation notes
|-- validation/                # actual offline test and audit results
`-- d-i/forky/
    |-- repo.env               # role, defaults and repository path contract
    |-- preseed.cfg            # generated entry point; do not edit directly
    |-- payload.manifest       # generated per-file SHA-256 inventory
    |-- payload.tar.gz         # generated immutable runtime source snapshot
    |-- common.cfg
    |-- fragments/
    |-- classes/
    |   `-- configs/target-assets.tsv
    |-- hosts/
    |   |-- installer/         # shared identity, runtime, account, layout and boot envs
    |   `-- profiles/          # all profile .env files, without family subdirectories
    |-- hooks/
    |   |-- installer/
    |   |   |-- apt-setup/
    |   |   |-- base-stage.d/
    |   |   |-- d-i/
    |   |   |-- finish-install.d/
    |   |   |-- partman/
    |   |   |-- pre-pkgsel.d/
    |   |   `-- late_command.sh
    |   `-- target/            # shared + this role + hardware payloads
    |-- scripts/               # common, preseed, early, partman, late, runtime, firstboot
    `-- tests/
```

Desktop build/install helpers additionally live in `scripts/desktop/`.

## Serve over a trusted lab network

Prefer validated HTTPS on a private installation network, or trusted local media.
The following HTTP example is only for an isolated, trusted lab. It authenticates
neither the initial preseed nor its replacement by a network attacker; SHA-256
pins inside that preseed cannot repair that trust boundary. Restrict access to
installation clients and publish one complete snapshot atomically.

```sh
python3 -m http.server --bind 0.0.0.0 8000 --directory .
```

For the example lab server, the source portion of the installer boot arguments is:

```text
auto=true priority=critical url=http://192.168.50.122:8000/d-i/forky/preseed.cfg
```

Add the appropriate original class selection and deployment-specific account,
network and storage configuration. These source examples are not a claim that an
arbitrary host can safely use a fixed-disk profile. The current role default is:

```text
classes=prod;desktop;standard;static;software;timeshift;podman;crowdsec;whisper;btrfs-de
```

An explicit minimal role selection suitable for a bootstrap smoke test is:

```text
classes=prod;desktop;standard;dhcp;ssh
```

Hardware detection and profile constraints still apply. Enter boot arguments in
the bootloader, not as an unquoted shell command containing semicolons.

## Local media (`file=`)

Copy the **whole tree**, not just `preseed.cfg`, onto the mounted media:

```text
auto=true priority=critical file=/hd-media/debian-preseed-de/d-i/forky/preseed.cfg
```

`preseed/file=` is also supported. `file=` names an absolute preseed file, not a
directory. Repository-relative includes are staged as absolute `file:///...`
locations. Local profile edits without rebuilding fail early instead of silently
installing an old snapshot. Use local paths without spaces or shell metacharacters.

## Required private deployment configuration

Review `d-i/forky/hosts/installer/` and the selected disk profile before booting.
The original desktop integrations still require deployment-specific credentials,
including the account password, primary GPG passphrase, Fruux username/password
and Telegram token/chat ID when that desktop setup runs. This refactor does not
invent credentials, remove integration requirements, or make late desktop checks
happen before partitioning.

Supply trusted shell assignments through `/preseed.env` in a private initrd,
owned by root and mode **0400 or 0600**. The installer rejects other owners/modes
before sourcing it. Recognized names include `PRESEED_ROOT_PASSWORD`,
`PRESEED_PRIMARY_PASSWORD`, `PRESEED_PRIMARY_GPG_PASSPHRASE`,
`PRESEED_FRUUX_USERNAME`, `PRESEED_FRUUX_PASSWORD`, `PRESEED_TELEGRAM_API_KEY`
and `PRESEED_TELEGRAM_CHAT_ID`. Optional integrations have additional fields;
consult `installer_cmdline_value` in `scripts/common/lib.sh` for the complete
mapping. Use single-quoted shell assignments with proper escaping; this is a
trusted shell file, not an untrusted data import. Keep secrets out of source
control, public URLs, command lines and the distributable payload.

After installation, the three extension exports, `bookmark-coverage.json` and
`BROWSER-IMPORTS.md` are staged as user-owned, mode-0600 files in the configured
account's Downloads directory. Import the three exports through the extensions'
own interfaces. See `d-i/forky/hooks/target/usr/local/share/browser-imports/`.
Use `browser-devtools vivaldi --port 9222` as the ordinary user for an isolated,
loopback-only debug profile; Chromium, Edge and Chrome are also supported.

## GitHub raw URLs and redirects

For a sanitized, non-personalized build, a public raw URL can point to a matching
repository snapshot; the
full path prefix, including slash-containing refs, is retained. For example:

```text
url=https://raw.githubusercontent.com/mjcramerz/debian-preseed-de/refs/heads/mcr/main/d-i/forky/preseed.cfg
```

This is a URL-shape example, not a verified live deployment. Standard HTTP
redirect links are supported: the effective final **preseed file** URL determines
the sibling asset base, not the shortener's domain. For example:

```text
url=https://tinyurl.com/fdsgdf5
```

The short link must actually redirect to the published generated preseed; HTML
preview, JavaScript, login or CAPTCHA pages are not installer sources. Redirect
loops, non-HTTP(S) destinations and HTTPS-to-HTTP downgrades are rejected before
fetched content is accepted. Initial network setup and the first preseed download
are performed by the Debian installer image, before repository code can run.

TLS verification is enabled by default. When deliberately required for your lab,
this repository's fetch layer recognizes:

```text
allow_unauthenticated_ssl=true
```

It also recognizes the bare flag and
`debian-installer/allow_unauthenticated_ssl=true`. Configure the initial image's
native downloader separately as required by that image; repository code cannot
change a TLS decision made before the first preseed is loaded. Prefer valid CA
trust and a correct clock over bypassing verification. See `SECURITY.md`.

## Profiles

All existing values, including sizing and hardware policy variables, remain in:

```text
d-i/forky/hosts/profiles/btrfs-de-dual-flex.env
d-i/forky/hosts/profiles/btrfs-de-dual-main.env
d-i/forky/hosts/profiles/btrfs-de-dual.env
d-i/forky/hosts/profiles/btrfs-de-flex.env
d-i/forky/hosts/profiles/btrfs-de-main.env
d-i/forky/hosts/profiles/btrfs-de.env
d-i/forky/hosts/profiles/btrfs-desktop.env
d-i/forky/hosts/profiles/f2fs-de-cbook.env
d-i/forky/hosts/profiles/f2fs-de-dual-cbook.env
d-i/forky/hosts/profiles/f2fs-de-dual.env
d-i/forky/hosts/profiles/f2fs-de.env
d-i/forky/hosts/profiles/f2fs-desktop.env
d-i/forky/hosts/profiles/vm-desktop.env
```

The logical `override-<name>` identifier remains compatible internally, although
its physical source is now `hosts/profiles/<name>.env`. Baseline profiles retain
`btrfs-desktop.env`, `f2fs-desktop.env` and `vm-desktop.env` fallback names. See
`d-i/forky/hosts/README.md` for the unchanged environment precedence.

## Diagnostics and validation limits

Bootstrap failures print a `[repository] fatal:` message to stderr and the
installer diagnostic console when available. Inspect `/tmp/installer.log`,
`/tmp/install-runtime/bootstrap/`, and private `*.fetch-error` response logs.
No `preflight.ok` marker is written on repository/class/profile preflight failure.
Early, partitioning and late phase runners require that marker.

The delivered validation reports cover regression tests, loopback HTTP/HTTPS
transport, complete generated bootstrap commands, relocation integrity and
syntax/inventory checks. They do **not** certify a booted Debian installer,
partitioning, package downloads, graphical login, Secure Boot, GPU suspend or
systemd/AppArmor behavior on real hardware. See `docs/VALIDATION.md` and run the
hardware acceptance matrix before deployment to valuable disks.
