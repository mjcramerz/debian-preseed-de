# Hook and target layout

`installer/` contains code and hooks executed in the Debian installer context:
`apt-setup/`, `base-stage.d/`, `d-i/`, `finish-install.d/`, `partman/`,
`pre-pkgsel.d/`, and `late_command.sh`. Stage-specific dispatchers remain in
`scripts/early/`, `scripts/partman/` and `scripts/late/`.

`target/` contains payloads destined for the installed system. Shared, role and
hardware assets are physically colocated, but are **not** copied indiscriminately.
The original class predicates, profile variables, package gates, rendering and
per-file installed modes still control staging. Role implementation code is in
`scripts/late/desktop.sh` or `scripts/late/server.sh`, as appropriate to this repo.

## Hardware mapping

`d-i/forky/classes/configs/target-assets.tsv`. Each non-comment row contains four
TAB-separated fields:

```text
group<TAB>class<TAB>original-target-relative-path<TAB>source-relative-to-hooks/target
```

The detector continues selecting hardware classes. The common helper
`installer_hardware_asset_path` resolves the matching source file. CPU and disk
variants use descriptive suffixes when they originally had the same destination,
for example `80-cpu-profile-flags.intel.cfg` and `.amd.cfg`, or
`modules.nvme.tmpl` and `modules.vm.tmpl`. Installed filenames do not gain these
source-only suffixes. The build checks every mapping destination source exists.

NVIDIA detection does not bypass the original NVIDIA/CUDA addon opt-in and
compatibility checks. GPU power policy, initramfs, modprobe and service payloads
remain staged only through their existing applicable code paths.

Shared-first desktop-final files whose original contents differed use an
`.installer-base` source copy for the first stage and the canonical desktop
source for the final stage. This preserves the old staging order rather than
arbitrarily choosing one of the colliding source files.

APT preference source directories are called `default/` and (server repo only)
`server-suite/`. Their selection remains based on the original addon policy;
being a server alone does not silently switch APT pin priorities.
