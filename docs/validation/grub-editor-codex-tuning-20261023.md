# GRUB, editor, optional Codex media and AC tuning source changes

Date: 2026-10-23. Base commit: `29f808142c19449f9859ac7bb1286f30c4d4f044`.
This record describes an uncommitted working tree with pre-existing unrelated
changes. Generated products include those existing inputs. No deployment,
installed-host repair, service operation or hardware write was performed.

Final user instruction: source corrections and artifact generation only;
no VMs, tests or validation commands. No such commands were run after that
instruction. Earlier static inspection is recorded below as historical work;
unexecuted native checks are not a pending task or a request for an image.

## Implemented contracts

### GRUB

The installation path stages the GRUB profile fragments, invokes the generated
`40_custom --install`, and checks the temporary custom menu with
`grub-script-check` before publishing it. The first display fragment used
shell-style `&&` between two tests. It now emits nested GRUB `if` blocks with
the normal indefinite menu timeout initialized first. Only the one-time
`installer-mok-enrollment` selection receives timeout zero. The installation
validator and failure propagation remain enabled.

The isolated GRUB fixture now requires a real image-provided parser for its
native acceptance case. It covers installation and regeneration across Btrfs,
F2FS, dual boot and MOK variants, and includes the reported condition as a
negative case. These fixtures have **not been executed** in this environment.

### L3afpad

The desktop package request, MIME associations, Labwc and Xarchiver entries,
theme keys/icons, installer staging, account copy, verification, AppArmor and
managed-wrapper configuration paths now use l3afpad. Its configuration is the
upstream eight-line positional format at `.config/l3afpad/l3afpadrc`, with
960x720 geometry, Monospace 12, wrapping, line numbers, autoindent and tab width
4. Both internal/external Waybar Notes buttons launch native l3afpad through
the existing Wayland wrapper. Tomat's config action executes l3afpad with the
selected config file and the existing native GTK environment.

Active source, payload members and regenerated inventories were inspected for
the old editor name. Historical validation documents outside the payload remain
records of their original snapshots.

### Optional Codex media

`/run/media/$USER/warehouse/extra` is optional. Missing, unmounted,
inaccessible or unsafe media returns no optional binding; normal Codex startup
does not require it. There is no host volume mount command, host mountpoint
creation or mount prerequisite.

Directory traversal uses `O_PATH | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC`.
Each pinned ancestor's mount ID is checked against the bounded mount table
before looking below it; untriggered `autofs` is rejected. At `warehouse`,
the pinned mount ID must also match the exact mountpoint. This avoids an
ordinary directory open implicitly triggering an automount. The final directory
must pass effective read/write/search permission checks. Bubblewrap receives
the descriptor and exposes only `extra` inside its private `/run` tree;
the account's AppArmor rule covers that exact tree. Descriptor cleanup, network
readiness and payload launch gates retain the existing lifetime handling.

The [Linux open manual](https://man7.org/linux/man-pages/man2/open.2.html)
documents the automount behavior of `O_PATH`.
[Bubblewrap 0.11 source](https://raw.githubusercontent.com/containers/bubblewrap/v0.11.0/bubblewrap.c)
accepts an open directory or path descriptor for `--bind-fd` and checks device
and inode identity before the payload runs. A concurrent identity replacement
must fail safely; it must never expose a replacement directory. Live removal
and replacement acceptance remains unexecuted.

Added isolated fixtures cover absence, unmounted directories, unsafe accounts,
permission failure, symlink ancestors/leaves, pinned identity replacement,
mount-ID evidence, rejection of autofs, no traversal below an automount,
private mount planning and nested working-directory selection. No fixture
mounts, probes or reads the real host's media during this work.

### AC performance tuning

Reviewed the recommendations in all five `todo/tuning/*.md` documents as data;
their example commands were not executed. The P15s and Flex single/duo pairs
each have identical sets of 143 hardware policy assignments. They enable
automatic tuning and an AC performance baseline. Lower application leases
cannot lower that maximum baseline. Manual selection, inactive-session handling,
pause, thermal faults, policy handover and journal restoration retain precedence.
Other six host profiles keep their existing conservative hardware values.

The P15s CPU performance floor is 35%, Flex 30%, and both high floors are 20%.
Performance/high use performance EPP, EPB 0, maximum 100%, turbo enabled and HWP
dynamic boost when supported. CPU thermal interlocks are 88 C for P15s and
85 C for Flex. Flex's launcher defaults select Intel/iHD; its GPU requests use
advertised efficient/maximum frequencies.

P15s requests the driver-advertised maximum NVML power limit in performance,
and supported application-clock pairs plus persistence in performance/high.
`supported-max` and `supported-1` skip only an absent capability. A discovered
control still passes existing bounds, permission, thermal and recovery checks.
Application-clock maximum selection uses the highest supported memory frequency
and a graphics frequency from that memory frequency's own table. Pascal is
excluded from Volta/Ampere lock controls. Numeric offsets, RAPL, uncore, voltage
and firmware limits remain unchanged. The existing NVIDIA class gate accepts
the Pascal-capable `addon/nvidia-legacy`; no driver class was rewritten here.

See [hardware tuning policy](../hardware-tuning/README.md) for the settings and
runtime ownership contract. The new fixtures cover AC arbitration, paired
policy generation, conditional capability absence, present-control errors,
power permission/temperature checks, exact restoration and valid clock pairs.
They remain unexecuted. No measured throughput or thermal stability is claimed.

The final source review also corrected persistence/clock recovery ordering.
Persistence enablement runs before other requested GPU mutations; disablement
runs after clock and Auto Boost restoration. If an earlier same-GPU restoration
fails, its persistence prerequisite and journal entry are retained for retry.
The existing exact-state and pending-intent recovery protocol remains in use.
Added but unexecuted fixtures model the Auto Boost side effect and an injected
restore failure, including a later recovery attempt. This dependency follows
the [NVML Auto Boost contract](https://docs.nvidia.com/deploy/nvml-api/latest/api/group__nvmlDeviceCommands.html).

## Earlier inspection record

These inspection commands ran before the user's final no-validation instruction.
The final persistence source correction was reviewed as source; its engine and
fixture AST inspection also preceded that instruction. No subsequent validation
commands were run.

Only source-as-data inspection and the two explicitly permitted generation
commands ran on the development host. No repository test module was imported,
no shell snippet sourced, no installed management helper invoked and no native
policy, shell or GRUB syntax validator run.

1. Read `AGENTS.override.md`, `docs/test-isolation.md`, the chosen Makefile
   recipes, `tools/build.py`, `tools/publication.py`, `tools/inventory.py` and
   `tools/inventory_apt.py` before generation.
2. `git diff --check`: exit 0, no whitespace errors.
3. `python3 -I -B -` with standard-library `ast.parse`: 17 affected Python
   sources/templates/fixtures parsed as data. Repeated for the wrapper and its
   fixture after the final automount correction. No repository imports or code
   execution. The ten fixture paths are listed below.
4. Standard-library JSON data parsing of both Waybar Notes objects verified
   their l3afpad commands. Positional config inspection verified eight lines.
5. Standard-library literal profile inspection verified 143 unique hardware keys
   in every profile, identical values within each P15s/Flex pair, and the
   conservative automatic/AC selections in the other six profiles.
6. `make build`: exit 0, 1,823 payload files. Repeated after the automount fix.
   This command serializes only the three installer products; it runs no tests.
7. `make inventory`: public HTTPS APT metadata generation only. It runs no APT
   or package helpers and installs nothing. Final result is recorded below.
   The collector records Release/index SHA-256 consistency and explicitly does
   **not** verify OpenPGP signatures. This is metadata, not installed package
   state or a dependency-solver result.
8. `python3 -I -B -` with `tarfile`, `hashlib` and `pathlib`: read archive members
   without extraction, bounded member counts/sizes, compared every member with
   its loose source and manifest hash, and checked the generated preseed's
   archive/manifest/transport-source pins. No payload member was executed.
9. `rg -n -i --hidden 'featherpad' d-i tools --glob '!payload.*' --glob '!*.pyc'
   --glob '!preseed.cfg'`: no matches. Payload and root JSON inventories were
   checked separately as data. Old-name absence does not replace native launch
   acceptance.

### Final source generation

After the persistence/clock recovery correction, `make build` exited 0 and
reported 1,823 payload files. `make inventory` also exited 0, processed all 97
indexes, retained 21,351 package candidates and reported zero unavailable
metadata requests. These are generation commands, not validation runners.

The following identifiers were read from the generated inventory/preseed data;
no separate post-instruction checksum check, validator or test was run:

| Generated field | Recorded value |
| --- | --- |
| Payload size | 26,586,825 bytes |
| Payload SHA-256 | `7e5c6a5910b836c462e105861d6e90103e086be40d9e5fdf609e60934af728e0` |
| Preseed manifest pin | `f565f9161a1256cb1b134c539bfe67f14dda964ab7d8f50dac4e2d5052a488ae` |
| Inventory APT metadata pin | `8ff6ec5254266dbc53bf17c1b49cace65a2d4f3d89760a3c6865c2f7817b2387` |
| Inventory missing package requests | Empty list |

Source inspection traced the four requested behaviors through their callers
and staging paths. The final additional change is in `hardware_tuning/engine.py`
and its existing fixture file; the hardware policy documentation describes the
same recovery order. No host deployment, mount, service action or hardware
mutation was performed.

### Superseded generation receipt before the persistence correction

Both generation commands for that snapshot exited 0. Inventory acquisition processed 29
Release files and 97 indexes, retained 21,351 package candidates, and reported
zero acquisition errors. Both JSONs reference the final payload identity;
`inventory.json` pins the exact APT JSON hash. L3afpad has indexed candidates,
the old editor name occurs in neither JSON, and the full request union reports
no missing package requests. This does not establish an APT solver transaction.

That archive contains 1,823 regular members totaling 34,745,850 uncompressed
bytes. Every member's bytes match its source and manifest entry. Preseed pins
the exact archive, manifest and bootstrap transport source hashes. No generated
artifact in this receipt was stale relative to those inspected inputs. This
receipt identifies the preceding snapshot, not the final persistence correction.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `d-i/forky/payload.tar.gz` | 26586611 | `d8b95884be082d5aad84c7184cfdaac93b9f445c513a6eab31abe74fe7657fd5` |
| `d-i/forky/payload.manifest` | 224454 | `df3b22b84b83146e52bdd1e98c3cf9b68a698d571be39d380be67eb20950b664` |
| `d-i/forky/preseed.cfg` | 96407 | `6af8ccde56c100674689254a3632593807d57d5f01fad3d86ca823464cb40b48` |
| `inventory.json` | 2463203 | `e5114bbfe34ada7daffe50166e9b82b59603fa6196b886c00a08bdf5d546663e` |
| `inventory-apt.json` | 19178893 | `fd29aa1285a077b8a16682fc20912ab482c8c5fbbf328ad3eeb056661c0d5678` |

That manifest hash fingerprints the preceding packaged source inputs. The ten changed
fixture files listed below have aggregate fingerprint
`4e7ce9030ba7133e95f4d4c40e0d7849b1399297ff5461867124acbd9b3ac053`:
SHA-256 over sorted repository-relative path bytes, NUL, and the raw SHA-256
digest of each file. These fingerprints identify the inspected working bytes;
they do not imply fixture execution.

Acquired candidates include l3afpad `0.8.18.1.11-4+b1` (amd64), Bubblewrap
`0.13.1-1`, GRUB `2.14-4`, systemd `262.1-1`, and the legacy NVIDIA
`580.142-0xanmod1` userspace. Multiple suites/architectures are present in the
inventory. None of these values is a measurement of the installed host or a
test image version.

## Execution limits

The user explicitly excluded VMs, tests and validation commands. Source review
and pure generation are the final completion boundary for this task. No test
pass count, native execution, installed-desktop acceptance or measured hardware
performance is claimed. No image or validation permission is being requested.

GRUB/AppArmor native parsing, sandbox identity/removal behavior, l3afpad GUI
launches and hardware temperature/throughput behavior were not executed.
Target image, kernel and installed package versions are unavailable; the APT
candidate versions above are acquisition evidence only. Driver-bounded requests
are not measurements of stability. These are execution limitations, not
scheduled work.

Independent read-only sidecar reviews were attempted but the agent service
failed encrypted-content hydration before any review work. No sidecar result is
used as acceptance evidence.

## Exact task paths

These paths contain this task's changes; several also contain earlier user
changes. The source list does not assign ownership of unrelated hunks.

```text
README.md
d-i/forky/classes/class-select/role/desktop.cfg
d-i/forky/hooks/target/data/codex/lib/codex.tmpl
d-i/forky/hooks/target/etc/apparmor.d/abstractions/codex-runtime
d-i/forky/hooks/target/etc/apparmor.d/desktop-utilities
d-i/forky/hooks/target/etc/apparmor.d/desktop-wrappers.tmpl
d-i/forky/hooks/target/etc/apparmor.d/local/abstractions/codex-user-media.tmpl
d-i/forky/hooks/target/etc/apparmor.d/tomat
d-i/forky/hooks/target/etc/skel-desktop/.config/featherpad/fp.conf (removed)
d-i/forky/hooks/target/etc/skel-desktop/.config/l3afpad/l3afpadrc (added)
d-i/forky/hooks/target/etc/skel-desktop/.config/labwc/menu.xml.tmpl
d-i/forky/hooks/target/etc/skel-desktop/.config/mimeapps.list
d-i/forky/hooks/target/etc/skel-desktop/.config/waybar/config.tmpl
d-i/forky/hooks/target/etc/skel-desktop/.config/xarchiver/xarchiverrc.tmpl
d-i/forky/hooks/target/usr/local/lib/hardware_tuning/broker.py
d-i/forky/hooks/target/usr/local/lib/hardware_tuning/common.py
d-i/forky/hooks/target/usr/local/lib/hardware_tuning/engine.py
d-i/forky/hooks/target/usr/local/lib/hardware_tuning/nvidia.py
d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/profiles.py.tmpl
d-i/forky/hooks/target/usr/local/libexec/labwc-tomat.tmpl
d-i/forky/hooks/target/usr/local/share/grub-profiles/display-2.cfg.in.tmpl
d-i/forky/hosts/backup/base.env-1.env
d-i/forky/hosts/backup/base.env-2.env
d-i/forky/hosts/backup/base.env.edited
d-i/forky/hosts/backup/base.env.orginal
d-i/forky/hosts/profiles/btrfs-de-p15s.env
d-i/forky/hosts/profiles/btrfs-de-p15s-duo.env
d-i/forky/hosts/profiles/btrfs-de-flex.env
d-i/forky/hosts/profiles/btrfs-de-flex-duo.env
d-i/forky/hosts/themes/apps.env
d-i/forky/hosts/themes/base.env
d-i/forky/hosts/themes/theme-schema.tsv
d-i/forky/scripts/desktop/components/target-assets.sh
d-i/forky/scripts/desktop/components/user-config.sh
d-i/forky/scripts/desktop/hardware-tuning.sh
d-i/forky/scripts/desktop/verify.sh.tmpl
d-i/forky/scripts/firstboot/04-validation.sh.tmpl
d-i/forky/scripts/late/security.sh
d-i/forky/tests/test_hardware_restore.py
d-i/forky/tests/test_desktop_sandbox.py
d-i/forky/tests/test_native_tomat_20260920.py
d-i/forky/tests/test_hardware_tuning_20260916.py
d-i/forky/tests/test_drawer_native_icons_20260920.py
d-i/forky/tests/test_logging_size_20260924.py
d-i/forky/tests/test_log_launchers_20260915_r3.py
d-i/forky/tests/test_session_reliability_20260921.py
d-i/forky/tests/fixtures/waybar-native-icons-gtk.py
tools/tests/test_labwc_power_handoff.py
docs/hardware-tuning/README.md
docs/validation/grub-editor-codex-tuning-20261023.md
d-i/forky/payload.tar.gz
d-i/forky/payload.manifest
d-i/forky/preseed.cfg
inventory.json
inventory-apt.json
```
