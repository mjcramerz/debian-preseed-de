# Systemd resource policy and AppArmor audit - revision 4

Date: 2026-09-16. Base: the complete accepted R3 archive.

This is the current implementation report. R2/R3 reports and old validation
artifacts are retained as history and are not the current policy inventory.
R4 implements the four requested systemd corrections and reviews the supplied
complain-mode audit. The GitOps implementation and original Podman/zram workload
policies are preserved. No kernel tuning, drive scheduler, IOcost calibration,
hwdb/udev drive rule or unrelated service lifecycle change is included.

## Evidence and research boundaries

The supplied user audit reports systemd 261.2-1 and a user-manager delegation of
cpu, memory and pids, despite cpuset and io being available upstream. Its Foot
example is a UUID-named transient service in app.slice. The user supplied the
installed coredump socket's MaxConnections=16 and MaxConnectionsPerSource=8.
These are host observations, not measurements made inside this build container.

Upstream documentation supports delegation-list reset, hierarchical weights,
essential-session classification, core opt-out and self-recovering socket polling.
Upstream's coredump sysctl source explicitly coordinates core_pipe_limit=16 with
the socket's concurrency. Sources are listed below. Some web-rendered manpages
were stale; the package documentation and offline parser were cross-checked.
The exact 261.2 source tag/binary was not obtained here. Local systemd is 257.9;
AppArmor parser is 4.1.0. Neither live 261.2 execution nor kernel policy enforcement
was tested. Do not interpret parser success as either of those tests.

## Coredump: preserve vendor concurrency, own polling only

The retired R3 file `systemd-coredump.socket.d/60-concurrency.conf` is absent.
It is replaced with `60-poll-limit.conf`, rendering by default:

```ini
[Socket]
PollLimitIntervalSec=2s
PollLimitBurst=64
```

There is no MaxConnections or MaxConnectionsPerSource assignment, no empty reset
of those values, and no kernel.core_pipe_limit change. The obsolete
SYSTEMD_COREDUMP_MAX_CONNECTIONS knob is removed from all 13 profiles and the
renderer. The existing concurrency values therefore come from the installed
vendor unit, including future vendor updates. [1]

Both polling values remain explicit profile variables. Interval is validated as
2-60 integer seconds; burst as 1-1000000. Defaults are 2 and 64. The parser rejects
missing, zero, signed, leading-zero and multiline values before publishing the
rendered file. A burst of 150 is accepted and tested, rather than making the
local validation prevent restoration of the documented Accept=yes default.
Polling temporarily pauses acceptance instead of intentionally failing the
socket as trigger-rate exhaustion would. The value 64 is an administrator
choice, not a proven latency or crash-reliability optimum. Vendor trigger policy
and per-source limits remain unchanged. [2]

Existing coredump storage/profile variables remain separate from socket policy.
The 64M process/external-size defaults retain the prior small-core diagnostic
tradeoff; they do not guarantee capture of large application dumps. Journald
storage defaults remain as in R2/R3. No additional worker weights, socket
concurrency knobs or sysctl limits are introduced.

## User classes, service exceptions and lifecycle

The three sibling classes retain CPU/optional-I/O weights: session 200/200,
app 100/100, background 30/30. They are relative preferences under contention,
not fixed shares, CPU quotas, GPU controls or guaranteed disk bandwidth. [3]

| Component | Placement and exceptional policy |
| --- | --- |
| Labwc compositor | session.slice; CPU 300, optional I/O 300 |
| Kanshi and output watcher | session.slice; no service weights |
| swayidle and transient power-lock helper | session.slice; no service weights |
| Hyprpolkit, KWallet, SSH agent/key loader, portals | session.slice; no service weights |
| Waybar and Crystal Dock | Original default app.slice; R3 class-only overrides removed |
| Mako | Explicit app.slice |
| PipeWire, Pulse, filter-chain | Preserve package placement; CPU 200 only |
| WirePlumber | Preserve package placement; redundant R3 override removed |
| Calendar synchronization | background.slice |
| Managed ordinary applications | Existing launcher-selected app.slice |

This keeps session overrides for infrastructure needed to operate the session
instead of elevating every visible desktop component. [4] Existing audio realtime,
RTKit, memory-lock, sandbox and lifecycle settings are not changed. The compositor
I/O weight remains the explicitly requested policy; no device benchmark or storage
controller calibration establishes a latency improvement from that number.

The R3 `app-.scope.d/60-resource-class.conf` is removed. Existing managed launchers
already create services with --slice=app.slice. The original
`app-.scope.d/50-session-labwc.conf` remains byte-for-byte unchanged. No new generic
scope execution policy or unverified scope producer is introduced.

Sensitive services retain their separate `70-no-core.conf` with LimitCORE=0:
Bitwarden's service prefix, Hyprpolkitagent, KWallet and the lock-helper prefix.
The original SSH restrictions remain. The offline manager verifies prefix lookup
and both hard and soft limits while leaving an unrelated test service's core
limit unchanged. This opts out of systemd core collection; application-owned
crash reporting and crash metadata are separate concerns. [5]

## Delegation, accounting and system maintenance

`user@.service.d/60-resource-delegation.conf` retains exactly:

```ini
[Service]
Delegate=
Delegate=cpuset cpu pids memory io
```

There are no direct cgroupfs writes. The two manager configuration directories
retain explicit DefaultMemoryAccounting=yes and DefaultTasksAccounting=yes.
DefaultIOAccounting is controlled by the existing Boolean profile switch.
Delegation and accounting are distinct from scheduling preference. [3]

Exactly six managed IOWeight placeholders remain: three user classes, compositor,
system-maintenance.slice and system-background.slice. With
SYSTEMD_DEFAULT_IOACCOUNTING_ENABLE="false", both managers render
DefaultIOAccounting=no and all six new IOWeight lines are omitted. CPU weights
and delegation remain. Existing explicit zram/Podman policies are untouched;
the switch does not mean that the kernel io controller is disabled everywhere.

System maintenance and background slices remain children of system.slice through
their names. APT, local-APT, Timeshift and signature-update service drop-ins contain
only Slice=system-maintenance.slice; managed Syncthing contains only
Slice=system-background.slice. Their collective weights remain 30/30 and 50/50.
No separate root-level managed.slice is introduced and no workload limits,
restart behavior or cleanup/ownership rules are rewritten.

## AppArmor: audit classification, not automatic allow generation

The full attached file contains **153879 records**, including 153877 complain-mode
ALLOWED events and two STATUS records, with **10846 unique signatures** under the
recorded field set. `docs/resource-policy-r4/apparmor-log-triage.json` contains the
source checksum, exact category counts, physical line bounds and decisions.
The raw private audit is deliberately not put in the publishable codebase.

142871 records are under the Git learning-profile cascade, 6328 under the GLib
launcher cascade, and 1130 under Edge's missing bwrap transition. The main Git
executable, APT list/cache and dpkg read grants already exist in R3. Thus the log
cannot establish that R3 was deployed and loaded when those events occurred.
A missing exec transition in complain mode creates secondary learning-profile
noise; copying every descendant path into broad policy would misdiagnose it.

Only three production AppArmor files are changed:

### managed-desktop-utilities

The launcher adds flat, package-owned `/usr/lib/git-core/git-*` execution and the
exact multiarch `gio-launch-desktop` helper, both inheriting the current profile.
The existing main Git rule remains. There is no recursive /usr/lib executable
grant or generated null-profile policy. [6]

Read-only udev database entries cover observed block and USB metadata queries,
not access to raw block/USB devices. Eight exact peer labels receive ptrace read
permission for process-status queries: code, Edge and its launcher, Mullvad Browser
and its launcher, mullvad, obsidian and managed-desktop-editors. No new trace,
tracedby, wildcard peer or capability grant is added. AppArmor distinguishes these
read permissions from attaching a debugger, and the other peer must also permit
the interaction; existing base-policy readby is retained. [6]

The editor profile gets same-owner proc stat/cmdline reads and owner-only non-hidden
single-component filenames directly in HOME. That permits an extensionless document
without hard-coding the user's test filename, granting hidden credentials, adding
recursive home-tree access or allowing executable mapping.

### managed-desktop-wrappers

Only affected panel helpers gain read-only battery cycle_count, proc net/dev or
CPU-present metadata for inherited status descriptors. There is no mutable sysfs
or broad device grant.

The existing managed-app bubblewrap child gains an inherit-only link-dispatch
bridge for xdg-open, env (through the existing Python abstraction), the managed
launcher and systemd-run. The audited managed Python modules are enumerated, not
opened through a recursive package wildcard. Existing import-location restrictions,
validated launcher arguments, transient service ownership and no_new_privs remain.
No new unconfined fallback or profile-changing exec is used after no_new_privs.

### local/microsoft-edge-stable

The parent may read installed Glycin configuration and enter a dedicated
`edge-glycin-bwrap` child for GTK previews. Paired termination signals are explicit.
The child reuses the repository's namespace-construction abstraction, reads trusted
loader/library/font/configuration files, and inherits into the installed SVG/image
loaders after no_new_privs. No new parent capability rule is added.

There is **no Workspace allow rule**. Explicit denies cover Workspace in parent
and child plus the standard oldroot/newroot constructor aliases. The child does
not include the user-documents abstraction, browser database or GPU-descriptor
grants, or Internet networking. The 138 inherited-descriptor events in the old
Edge learning domain are not evidence that every browser descriptor belongs in a
decoder sandbox. The new child omits attach_disconnected because the audit does
not establish a need for it and AppArmor documents its aliasing risk. [6]

These are path-based restrictions, not a claim of absolute confinement against
arbitrary aliases, changed vendor/local policy or application-controlled IPC.
In enforce mode, attempts to upload directly from Workspace are expected to fail;
copy a deliberately selected upload to Downloads instead. Explicit denies also
remain effective when complain mode is used. No profile is globally switched to
complain, disabled, or unloaded by this revision.

## Installation, structure and stale-file handling

Policy remains split by purpose: 60-resource-class.conf for Slice only;
60-resources.conf for selected weights; 70-no-core.conf for core limits;
60-poll-limit.conf for socket polling. The existing renderer validates values and
publishes each rendered file atomically. User files render before the original
private-home copier. Optional package drop-ins are staged only for available
units; adding a drop-in does not enable an optional service. Existing AppArmor
publishers and managed-mode discovery already stage these files and enumerate
child labels; no parallel install route is added. Profile provenance hashes are
updated while retaining original source hashes.

This archive is a **fresh-install publishing tree, not an in-place host migration**.
Extract it into a clean serving directory. Do not overlay it onto R3: five retired
R3 files would otherwise survive, especially 60-concurrency.conf. The exact retired
paths are in the scope manifest. A host already running R3 needs administrator
review of those old local files before applying the new policy; no live cleanup,
manager reexecution or reboot is performed by this deliverable.

The complete repository, payload.tar.gz, payload.manifest and preseed pins must be
published together. GitOps mirror support and commit output remain unchanged.

## Post-install acceptance checks (read-only inspection)

Run these after a normal reboot/new login on the intended 261.2 host, not as proof
that this container ran the target system:

```sh
systemctl --version
systemctl cat systemd-coredump.socket
systemctl show systemd-coredump.socket -p MaxConnections -p MaxConnectionsPerSource -p PollLimitIntervalUSec -p PollLimitBurst
sysctl kernel.core_pipe_limit
systemctl show "user@$(id -u).service" -p Delegate -p DelegateControllers
systemctl show -p DefaultMemoryAccounting -p DefaultTasksAccounting -p DefaultIOAccounting
systemctl --user show -p DefaultMemoryAccounting -p DefaultTasksAccounting -p DefaultIOAccounting
systemctl --user show labwc-compositor.service -p Slice -p CPUWeight -p IOWeight
systemctl --user show waybar.service crystal-dock.service mako.service -p Slice
systemctl --user show pipewire.service pipewire-pulse.service wireplumber.service -p Slice -p CPUWeight
systemctl --user list-units 'labwc-bitwarden-*.service' 'labwc-power-lock-*.service'
aa-status
```

Inspect DelegateControllers and the user manager's cgroup.controllers for all
five requested controllers; controller availability and effective weights are
separate checks. Inspect the actual transient service's LimitCORE/LimitCORESoft.
Run Git aliases, links opened by sandboxed apps, editor save/process checks and
GTK previews after policy load; compare new audit records with the triage report.
Confirm that Edge still cannot open Workspace. Test logout/lock cleanup and audio
behavior on the desktop. No crash flood, host lifecycle transition, provider
push or kernel enforcement was executed here.

## Primary sources consulted

[1] https://raw.githubusercontent.com/systemd/systemd/main/sysctl.d/50-coredump.conf.in
[2] https://manpages.debian.org/trixie/systemd/systemd.socket.5.en.html
[3] https://manpages.debian.org/unstable/systemd/systemd.resource-control.5.en.html
[4] https://systemd.io/DESKTOP_ENVIRONMENTS/
[5] https://systemd.io/COREDUMP/
[6] https://manpages.debian.org/unstable/apparmor/apparmor.d.5.en.html

Documentation was reviewed on 2026-09-16. These are upstream/package references,
not a claim that a retrieved main-branch source is the exact 261.2 release.
