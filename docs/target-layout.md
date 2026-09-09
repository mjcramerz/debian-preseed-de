Desktop-specific target assets belong here when a class helper needs files that
must not apply to server installs. Shared target assets stay under
`hooks/target/`. Mirror the installed path directly under `target/`,
for example `target/etc/...` or `target/usr/local/...`.

Keep custom desktop-account units under
`target/etc/skel/.config/systemd/user/`. The desktop late-command copies that
tree into the primary account at `$HOME/.config/systemd/user/`, changes it to
the account owner, keeps the unit directories private, and creates
`labwc-session.target.wants/` links in both the skeleton and that account.
Custom Labwc, KWallet, Whisper, notification, and timer units belong there.

Keep administrator-owned user-manager policy under `target/etc/systemd/user/`.
That includes complete drop-ins for Debian or vendor package units and custom
units that must remain centrally root-owned rather than copied into a home. Do
not move them into
`target/etc/skel/.config/systemd/user/`, because those files become mutable
account-owned copies and take precedence over the central policy. Every
package-unit drop-in must be a complete tracked file; installer code may
validate and stage it but must not construct its configuration body inline.
This global placement is also required so the greeter's separate user manager
sees the conditions that block desktop-only portal, notification, policy-agent,
terminal-server, and related units until the managed Labwc environment has been
imported. PipeWire, PipeWire Pulse, and WirePlumber are deliberately excluded
from these Labwc drop-ins and retain their vendor socket-driven lifecycle. Do
not install custom Labwc or KWallet units globally. The shared D-Bus user-broker
hardening template remains under
`hooks/target/etc/systemd/user/` because it also applies to every user
manager.

Keep system services and their administrator drop-ins under
`target/etc/systemd/system/`. This includes the root-owned Incus host
reconciliation unit, the package-owned restricted user-broker drop-in, and the
Mullvad daemon DNS-backend and version-cache lifecycle policy.

Do not add a Labwc identity file under `target/etc/environment.d/`. A global
`environment.d` file applies to the greeter's user manager as well as the
desktop account. The `labwc-session` wrapper exports static session policy and
imports that bounded policy into the user manager before starting
`labwc-compositor.service`. The compositor uses the already-required seatd
backend, explicitly selects the rendered account `rc.xml`, and supplies
`labwc-autostart` through Labwc's asynchronous `--startup` hook. The ordinary
account `autostart` file remains a no-op so it cannot launch a second startup
owner. `labwc-autostart` imports the live compositor environment after the
Wayland socket and user bus exist, then activates `labwc-session.target` and
applies the initial managed output policy once.
Every service that belongs to `labwc-session.target` has
`BindsTo=labwc-compositor.service` and exactly one `After=` directive beginning
with `labwc-compositor.service`. The same line also names
`labwc-session.target` and any narrower service dependency. The target is bound
to and ordered after the compositor; the compositor uses
`KillMode=control-group`, is ordered after the canonical user `dbus.service`
and `dbus.socket`, and is ordered before the target. Reverse shutdown ordering
is therefore clients, session target, compositor, user broker, user D-Bus
socket. PipeWire, PipeWire Pulse, their sockets, and WirePlumber have no
Labwc-specific drop-ins or target links and no explicit ordering edge from a
Labwc service. The
login wrapper clears only user-manager environment state after the compositor
stops; it must not call `dbus-update-activation-environment` after the broker
may have begun shutting down. The desktop `user@.service` drop-in orders user
managers after `seatd.service`, reversing shutdown order so user-manager
teardown completes before seatd stops. Keep system-manager readiness
dependencies such as `systemd-user-sessions.service`,
`systemd-logind.service`, the system `dbus.socket`, and `seatd.service` on the
system-level `greetd.service` drop-in. A user unit cannot order against those
PID 1 units; the compositor unit refers only to the user manager's
`dbus.service` and `dbus.socket`.

The managed compositor explicitly sets `WLR_XWAYLAND=/usr/bin/false`.
This supplies wlroots with a root-owned fail-closed executable, so its lazy
Xwayland setup does not probe the intentionally absent system
`/usr/bin/Xwayland`. An empty value is not used because wlroots would treat it
as an executable path. Keep the private `/opt/xwayland` runtime confined to the
managed compatibility launchers; never expose it to the compositor, greeter,
autostart, or general user-manager environment.

KWallet activation overrides that refer to these account-local units belong in
`target/etc/skel/.local/share/dbus-1/services/`. The desktop late-command copies
that directory into the managed account. Do not divert or replace the package
files in `/usr/share/dbus-1/services/`: the account-local XDG data directory has
higher activation precedence for the desktop user, while the greeter retains
only the package activation metadata visible in its own session.

Desktop-only Perl runtime modules are authoritative here, not in the shared
hook tree: AI & Copilots, Whisper, Digital Assets, and managed external-software
modules live under
`target/usr/local/lib/perl5/site_perl/{ai-copilots,whisper,digital-assets,external-managed-software}`.
Their installed paths remain below `/usr/local/lib/perl5/site_perl/`; the
desktop role owns their source staging and deployment.

Curated Llama and Whisper download policy lives in the root-owned TSV catalogs
below `target/usr/local/share/labwc-ai-copilots/`. Computer Management remains
the only Fuzzel boundary: selecting AI & Copilots opens the managed Foot-first
terminal wrapper, and every action, model, project, file, catalog-download, and
free-text choice is completed there. The terminal selector displays only
validated filenames for installed models and an aligned resource table for
catalog downloads; it never displays internal catalog identifiers or absolute
model paths. Catalog resource figures are informational. The privileged helper
independently revalidates the catalog, resolves the exact LFS SHA-256 and byte
count from the pinned Hugging Face commit, and then uses the existing atomic
model publication path. The explicit custom Hugging Face URL flow retains its
required filename, SHA-256, and exact-byte inputs.

Application runtime configuration belongs at its installed path in this
target mirror. The llama launcher is the tracked
`target/data/llama/lib/llama` file and parses the rendered root-managed
`/etc/llama/llama.conf` from `target/etc/llama/llama.conf.tmpl`. Whisper uses
`/etc/whisper/whisper.conf`, rendered from
`target/etc/whisper/whisper.conf.tmpl`. Do not move these authoritative files
back into `scripts/late/templates/`, and do not use `/etc/default/llama.conf`
for application runtime policy that is unrelated to an init script.
The checksum-pinned release installers preserve llama's archive layout below
`/data/llama/{bin,metadata,share}` and Whisper's archive layout below
`/data/whisper/{bin,metadata}`; model storage remains below `/pool/cache`.
All Llama and Whisper release variants are AMD64-only. CUDA variants retain
their archive runpath to CUDA 12.8, and the shared desktop-graphics AppArmor
abstraction read-maps only the required CUDART and cuBLAS libraries from that
toolkit.

Whisper uses `WhisperMode/**` as its sole Perl namespace. Do not add
`Whisper/**` aliases or compatibility modules: the sole installed
`/usr/local/libexec/whisper-record-toggle` entrypoint dispatches directly to
`WhisperMode::CLI`.
The Labwc session target starts a confined microphone-mute oneshot after the
compositor is available. That unit starts PipeWire and WirePlumber, waits for
an internal non-HDMI capture source, makes it the default, and mutes every
usable source without blocking or terminating the graphical login when capture
hardware is absent or delayed. WirePlumber route/default-target restoration is
disabled so saved unmuted or HDMI selections cannot override the managed
session policy. Whisper is the only managed path that deliberately unmutes the
selected source; `WIN+R` and `Ctrl+Alt+R` share its user-owned recording
toggle, every stop or failure path restores mute, and a bounded recording
automatically finalizes after 15 seconds. Waybar microphone right-click only
toggles the default source mute state and never starts recording. A tmpfiles
metadata guard restores root ownership and mode for the generated runtime
configuration before the desktop session starts. The transcription and
persistent-server user units deliberately avoid per-user filesystem namespace
directives because systemd would otherwise expose host-root-owned files through
the overflow UID and invalidate that ownership check. Their AppArmor profiles
retain the least-privilege filesystem boundary. Recording, persistent-server,
and transcription units require the active `labwc-session.target` and stop
within five seconds. The controller resets failed state only when systemd
reports the specific recording or transcription unit failed. Asynchronous
transcription also rechecks
`labwc-session.target` immediately before its non-blocking start, so
finalization during teardown cannot load or restart the unit. The public
`whisper-cli` wrapper supplies the installed root-managed model unless the
caller provides an explicit model option.
Whisper application output, recording/transcription user-unit lifecycle
messages, and its AppArmor profile-mode events are routed through rsyslog to
`/var/log/managed/whisper/whisper.log` with root/adm ownership and bounded
logrotate retention.

The security class stages `/etc/apparmor.d/managed-desktop-wrappers`,
`/etc/apparmor.d/managed-system-wrappers`, and the bounded
`/etc/apparmor.d/usr.sbin.aa-status` reader. The desktop aggregate has one
profile attachment for every installed desktop `bin` and `libexec` helper,
including rendered session/root templates, all six desktop `sbin` wrappers,
the shared XSSH send/retrieve wrappers, and the TPM2 enrollment launcher/helper
pair. Internal helper calls transition to the matching managed profile through
rules that also permit bounded preflight reads. Named targets are used unless a
fan-out exceeds AppArmor's per-profile target limit, in which case the exact
executable attachment resolves the same strict transition.
Every non-comment policy row in the tracked
`hooks/target/etc/apparmor/managed-modes.conf.tmpl` source uses the
`__DESKTOP_APPARMOR_STATE__` placeholder. During target staging,
`DESKTOP_APPARMOR_STATE` renders that complete set to either enforce or
complain mode and publishes the concrete result as
`/etc/apparmor/managed-modes.conf`, including desktop and system wrappers,
applications, services, browsers, containers, vendor policies, and the bounded
`aa-status` reader. Disable remains an installed-system administrative action
rather than a valid installer profile value.
All managed GUI profiles share one Wayland/GLES/EGL/DRI/OpenGL policy with
Mesa, Intel, NVIDIA, and shader-cache access. The shared AppArmor graphics
abstraction permits the Vulkan loader ABI needed by package dependencies but
explicitly denies Vulkan ICD paths, while the managed launchers select the
OpenGLES WebGPU adapter and prevent Vulkan feature, interop, or backend
selection. GTK wrappers that render their own surfaces use
the same graphics abstraction, and package-owned GUI
profiles receive a generated `local/<profile>` include before their
unconfined/default mode is changed, preventing incomplete compatibility
profiles from flooding the AppArmor event log.
The desktop and greeter Labwc wrappers fix `WLR_RENDERER=gles2`, request GTK
OpenGL, and set `GDK_DISABLE=vulkan`; neither compositor may auto-select the
wlroots Vulkan renderer.
Package applications and privileged tools do not inherit the shell
wrapper domain; each wrapper receives only its bounded configuration, state,
capture, report, or policy paths. The complete enforced set contains one
installed-path attachment for every staged desktop wrapper when the selected
desktop AppArmor state is enforce.
FeatherPad, FocusWriter, KDiff3, Micro, Neovim, Qalculate, and Vim defaults are
desktop-role assets and are staged only when the desktop role is selected.
Recoll and Recollgui are installed with a multilingual, resource-bounded index
baseline, XDG-cached index and OCR data, private per-user GUI and index
configuration state, and GUI preferences which retain native desktop opening
and system color handling. Credential stores, cloud/container authentication
data, browser profiles, version-control metadata, removable mounts, and
transient build trees are excluded. Only the KeePassXC subtree below
`~/Syncthing` is excluded, so other synchronized documents remain searchable.
Image-only PDFs use bounded Tesseract OCR with the installed English and Swedish
language data, backed by Poppler extraction tools.

The desktop role stages Labwc session assets, Waybar/Fuzzel/Mako/Kanshi user
defaults, Zsh/Starship/fzf/btop defaults, portal and KWallet defaults, and a
Labwc-bound `systemd --user` service for `crystal-dock`. The Waybar
`quick-controls` groups render
network, Bluetooth, keyboard-layout, and screenshot modules inside one bordered
pill with transparent, borderless child controls. Internal eDP, LVDS, and
DSI outputs use a native output-specific Waybar configuration where a ``
leader opens the same four controls as a click-to-reveal drawer from right to
left; external outputs keep the four controls permanently expanded inside the
same pill. It includes an always-visible `` module
backed by interactive `bluetoothctl`, plus an
always-visible custom backlight module backed by `brightnessctl`. Right-clicking
the network icon opens fixed controls for both installer-owned ifupdown
adapters and NetworkManager-owned Ethernet/WiFi devices, plus confirmed MAC
randomization for saved profiles and directly managed physical adapters.
When either `addon/software` or `apps/mullvad` is selected, `pkgsel` installs
the browser while `late_command` captures installer DNS and installs Debian's
`systemd-resolved` before installing `mullvad-vpn` from Mullvad's
detached-signature-verified latest Debian artifact. The resolver step requires
the legacy `resolvconf` package to be absent, confirms that `/etc/resolv.conf`
resolves through `/run/systemd/resolve/stub-resolv.conf`, seeds that target-side
stub for remaining installer downloads, and verifies DNS before the Mullvad
download begins. The Mullvad APT archive remains configured for the browser and
later package updates without making the fresh install depend on a
release-transition pool object. The target requires
`systemd-resolved.service`, forces `mullvad-daemon.service` to use
`TALPID_DNS_MODULE=systemd`, and keeps every Tailscale profile on
`TAILSCALE_ACCEPT_DNS=false`, leaving one intentional system DNS owner. A
root-only coordinator also makes the two overlay-network daemons mutually
exclusive. Before Mullvad's daemon starts, it records whether Tailscale was
active, stops `tailscaled.service`, and verifies the daemon is inactive. A
Tailscale start requested during that exclusion window is skipped by an
`ExecCondition` rather than recorded as a service failure, while preserving a
restore request. Mullvad's post-stop path restores Tailscale only when it was
previously active or a deferred start was requested. Unsafe state or a failed
stop blocks Mullvad startup and attempts to restore the prior Tailscale state.
If that restoration fails, its marker remains available for a later
post-stop retry instead of silently losing the requested state. This exclusion
follows the explicitly managed Mullvad daemon lifetime; no vendor CLI status
text is parsed or polled. It
stores Mullvad's application-version cache under the systemd-managed persistent
`/var/lib/mullvad-version-cache` directory and orders the daemon after
`local-fs.target`, `systemd-resolved.service`, and
`systemd-tmpfiles-setup.service`. The role's tmpfiles policy creates the
root-owned directory with mode `0755` but does not pre-create
`version-info.json`; Mullvad remains solely responsible for writing valid cache
data. No account identifier, login, or automatic VPN connection is
provisioned. The late security phase normalizes the exact package-owned
`mullvad-browser` profile with `attach_disconnected` and `mediate_deleted`
before applying its selected mode. Nameless disconnected VA-API paths are
therefore mediated without adding a wildcard file grant. The desktop schema
override sets
`org.gnome.system.wsdd` to `display-mode='disabled'`, preventing GVFS from
broadcasting discovery traffic across Mullvad, Incus, and other managed
interfaces.
Right-clicking the Bluetooth icon opens quick scan, pair, connect, and
disconnect actions plus nested device and adapter management. BlueZ starts
independently and owns controller policy from `/etc/bluetooth/main.conf`; the
optional hardened
`bluetooth-controller-init.service` runs afterward without overriding rfkill
policy. Its low-level `btmgmt` request is wrapped in an external timeout so the
BlueZ 5.85 client cannot hold the oneshot open. User control continues over the
standard BlueZ D-Bus API on the managed
dbus-broker system bus. KeePassXC is part of the desktop
baseline with a mode-0600 hardened configuration, a private
`~/Syncthing/keepassxc/` database directory, and a native-Wayland launch path
confined by the dedicated no-network KeePassXC AppArmor profile. Avoiding a
second Bubblewrap/AppArmor layer keeps Qt's atomic configuration-file writes
functional while preserving the application-specific filesystem boundary.
Waybar uses the compositor's
native `ext/workspaces` protocol instead of a custom backend. Xwayland remains
excluded from system package installation by package selection and APT policy.
The installer instead verifies and extracts the Debian `xwayland`,
`xserver-common`, and `libxcb-cursor0` package payloads below `/opt/xwayland`
without registering them with dpkg and without adding wrappers or copied
executables. The desktop login wrapper, greeter wrapper and client, Labwc
autostart, and the persistent user-manager environment explicitly scrub
inherited X11/Xwayland state before profiles are sourced, children are
launched, or activation variables are imported. Codex and the managed ChatGPT
launcher apply the same ambient-state boundary. These paths do not bind or
execute the private payload, publish an X11 display, configure Xwayland
persistence, or create an X11 socket.
`labwc-compositor.service` additionally masks `/opt/xwayland` with
`InaccessiblePaths`, so host Labwc cannot inspect or execute the private
runtime. The payload becomes visible only inside the dedicated compatibility
service's Bubblewrap namespace.
Only the dedicated Zoom/Discord launcher may inspect the root-owned private
payload. Its Bubblewrap constructor keeps the system `/usr` read-only and
exposes the verified private payload read-only below `/opt/xwayland`; no
compositor-created X11 socket is imported. The compatibility CLI accepts only
`zoom` and `discord`; all other managed applications are excluded from this
path, and neither Xorg nor the system `/usr/bin/Xwayland` is an allowed server.
Bubblewrap creates a private mode-1777 `/tmp/.X11-unix`, a private
`/run/user/$UID`, and a private network namespace configured by `slirp4netns`.
The application therefore retains outbound network access without sharing the
host abstract Unix-socket namespace where the Labwc session's Xwayland display
may already own `@/tmp/.X11-unix/X0`. A sandbox-local resolver file points at
the slirp DNS endpoint; the host resolver is not reused inside this namespace.
The constructor binds only the current Labwc Wayland socket into the private
runtime and holds an exclusive lock-only bind for that imported socket name.
Cage consequently selects a different nested Wayland socket instead of trying
to replace the imported outer socket. The lock descriptor remains owned by the
constructor until Bubblewrap exits and is never passed to the application.

The launcher first redirects each invocation to a target-bound transient user
service with `labwc-zoom-cage` or `labwc-discord-cage` as its journal
identifier. Cage, private Xwayland, and application diagnostics therefore do
not inherit Labwc's journal identity. The service then starts Cage as a nested
Wayland compositor. `WLR_BACKENDS` is deliberately absent and is rejected by
both supervisor phases if supplied; Cage auto-selects its nested backend from
the validated outer `WAYLAND_DISPLAY`. Cage receives the managed native-Wayland
and OpenGL environment (`GDK_BACKEND=wayland`, `GDK_DISABLE=vulkan`,
`QT_QPA_PLATFORM=wayland`, `QSG_RHI_BACKEND=opengl`, `QT_OPENGL=desktop`, and
`MOZ_ENABLE_WAYLAND=1`) together with `WLR_RENDERER=gles2`,
`WLR_WL_OUTPUTS=1`, and `WLR_NO_HARDWARE_CURSORS=1`. It also fixes
`WLR_XWAYLAND=/opt/xwayland/usr/bin/Xwayland` and supplies only the curated
private Xwayland library directory while Cage and its Xwayland child start.
Cage is invoked without an Xwayland command-line toggle: its compiled wlroots
Xwayland/XWM integration starts automatically, while `WLR_XWAYLAND` selects the
private server binary. That integration owns display selection, listener
lifecycle, and rootless X11 surfaces inside the private filesystem and network
namespaces. The managed path does not create a fixed `:99` listener, pass an
X11 descriptor, import a host X11 socket, or invoke Xwayland with rootful
decoration or geometry options.
The auto-selected nested Wayland backend has no DRM lease backend. A bounded
outer supervisor
therefore omits only Cage's exact upstream `WLR_INFO` line stating that it could
not create `wlr_drm_lease_manager_v1`; source-path, severity, and complete
message must all match. It also omits only Xwayland's exact unadorned
`(EE) failed to write to Xwayland fd: Broken pipe` line during terminal Cage
teardown. Timestamped, extended, oversized, and otherwise different messages
remain visible. EGL, allocation, protocol, other Xwayland, and application
failures remain visible, and the supervisor propagates Cage's real exit or
terminating-signal status.
Every managed launch mode exposes only DRM render nodes to this namespace;
primary `card*`, unused `controlD*`, and NVIDIA's modeset device remain absent
and are denied by AppArmor. Cage, private Xwayland, Zoom, and Discord therefore
cannot acquire the host's KMS connectors, while render clients can still use
non-modesetting GPU acceleration.
Because Bubblewrap sets `no_new_privs`, the outer supervisor, Cage, its Xwayland
child, the inner supervisor, and the application inherit the same already-confined child
profile instead of attempting post-namespace AppArmor transitions. Same-profile
signal mediation permits their bounded lifecycle control. Direct execution of
Cage or either the private or system Xwayland binary still enters a separate
fail-closed attachment outside this launcher path.
Inside the compatibility child, AppArmor permits only the observed fixed
diagnostic and desktop helpers and keeps each one in the same inherited
profile. Xwayland's compiled keymap, Qt's architecture-specific shader cache,
and Zoom's atomic configuration files are owner-scoped. CPU topology and
vulnerability data, CPU frequency minima, PCI identifiers, power-supply
status, iproute2 group metadata, and portal inventory are read-only. The
compatibility policy does not add a generic home rule, writable procfs or
sysfs access, a new capability, broad process control, or unconfined
execution.
The inner supervisor requires Cage to replace the outer `WAYLAND_DISPLAY` with
its nested socket, requires Cage's local `DISPLAY` and private X11 socket, and
revalidates the private Xwayland executable, protocol data, XKB compiler, and
libraries. It then removes `WLR_XWAYLAND`, the nested-backend controls, and all
other Xwayland control variables before starting only the allowlisted Zoom or
Discord executable. Cage remains the Xwayland owner and exits when the
supervisor exits. Cage's private `DISPLAY` remains available only as a
compatibility endpoint; `XAUTHORITY` and every inherited host X11 control are
absent. Zoom and Discord remain native Wayland clients inside Cage with the
same managed toolkit environment listed above. Zoom keeps Desktop OpenGL and
the OpenGL Qt Quick RHI with `QT_QPA_PLATFORM=wayland`; it does not set
`QT_XCB_GL_INTEGRATION`. Discord uses the shared managed Chromium OpenGL path,
`--use-gl=angle --use-angle=gl`, while retaining the same tightly scoped
Xwayland compatibility. Both applications disable Vulkan in
their toolkit environment and launch arguments, override Chromium's GPU
blocklist, and keep GPU rasterization enabled. Private `/tmp`,
`/var/tmp`, and `/dev/shm` mounts are explicitly mode `01777` so desktop
applications can use standard temporary-file semantics.
The inner supervisor also starts a one-way text clipboard bridge. `wl-paste`
watches only the imported host Labwc Wayland socket and invokes a fixed sink
that sends each event through `wl-copy` on Cage's nested socket. Clipboard data
is streamed rather than buffered by Python, no Cage-to-host bridge is exposed,
startup failure prevents the application from launching, and an unexpected
bridge exit terminates the still-running application.
When the application exits, Cage owns and tears down the private Xwayland
server. The bounded relay removes only the exact known broken-pipe teardown
line and does not turn another Xwayland diagnostic into a successful unit.
Their required PipeWire and pipewire-pulse sockets are mandatory sandbox
inputs, and both namespaces bind only validated V4L2/media camera character
devices rather than the host `/dev` tree. Each launch creates separate filtered
`xdg-dbus-proxy` endpoints for the desktop session bus and the system bus. The
host `/run/dbus/system_bus_socket` is never bind-mounted into either namespace;
the filtered system proxy alone appears at that conventional path, with no
system service allowlist by default. Discord also receives its current
notification, portal, tray, and Secret Service session names, while Zoom owns
only its `org.kde.*` compatibility names and may talk to ScreenSaver.
Discord's user-space host/module updater is disabled in its bounded
`settings.json` only after the launcher validates the complete root-owned
stable runtime below `/opt/discord`. The software late phase has already
downloaded and digest-verified Discord's manifest, host `full.distro`, and
declared module `full.distro` files before the first login. The host executable
is `/opt/discord/Discord`; root-owned module directories are exposed through
Discord's versioned per-user module layout without granting execution or mmap
permission to `~/.config/discord/app-*`. The internal
`/usr/local/libexec/managed-discord-distro` program only validates and safely
extracts already downloaded manifests and archives for the preseed bootstrap,
scheduled updates, and offline repair. Scheduled apply runs also rebuild a
damaged `/opt/discord` from those retained artifacts when no newer release is
pending. Publication discards any module subtree bundled in the host archive
and rebuilds it exclusively from the manifest-declared, digest-verified module
archives. A failed staging operation preserves the stable updater reason while
reporting the exact host, module, metadata, normalization, or runtime-validation
stage in installer stderr and the managed updater log. Every module advertised
by the validated manifest is published and checked against `installed.json`,
including `discord_krisp` when it is part of that release; the launcher does not
suppress Krisp initialization failures or invent a replacement module.
Zoom's host-side `~/.config/zoom` directory is mounted as the sandbox's complete
`~/.config` directory. This lets Qt create, lock, and atomically replace
`zoomus.conf` while keeping every unrelated host configuration file outside the
sandbox. The installer stages a mode-`0600` complete managed `[General]`
baseline at `/etc/skel/.config/zoom/zoomus.conf` and copies `.config/zoom` into
the primary desktop account. The seed enables Wayland sharing and QML caching,
uses the system theme and locale, disables automatic meeting video, GIF
autoplay, mini-window and test modes, and carries the full managed audio-device
and SSO placeholder set without embedding account data.
Other Qt applications and systemd/D-Bus-activated Qt desktop services use the
native Wayland QPA backend, and the staged Labwc configuration must not include
legacy display-server startup assets such as `xinitrc`. Crystal Dock reads per-desktop configuration from
`~/.config/crystal-dock/labwc/`; the
role also stages the same preset under `/etc/xdg/crystal-dock/labwc/` so
Crystal Dock can copy it on first run when a home directory does not already
contain a dock configuration. The installer renders the profile-owned Qt6ct
preset with the desktop-wide `Papirus-Dark` icon theme into both `/etc/skel`
and `/etc/xdg`, then copies the skel configuration into the primary account.
The user service launches `/usr/bin/crystal-dock` directly only after the
single target-owned `labwc-sync-application-launchers.service` transaction has
refreshed the primary account's managed desktop entries. `Requires=` plus
`After=` keeps that prerequisite synchronous without launching a second helper
outside systemd's one-shot serialization. Crystal Dock inherits the real Labwc
user manager environment without rewriting `HOME`, `XDG_CONFIG_HOME`, or user
Qt configuration, enforces native Wayland/OpenGL rendering, and records both
standard streams in the user journal with `SyslogIdentifier=crystal-dock`. The unit is
explicitly ordered after the compositor and stops its complete control group
before the compositor exits, so a normal session teardown does not strand dock
children or let the Wayland connection disappear underneath the main process.
It also waits for a client-visible output before every start. Automatic failure
recovery uses systemd's direct restart mode and remains subject to the user
manager's start-rate limit; no crash signal is added to `SuccessExitStatus`.
Browser desktop entries still pass through `labwc-managed-app`, which forces
native Wayland and disables Vulkan for Chromium-family applications. KWallet portal and
wallet-daemon D-Bus activation files are account-local under
`~/.local/share/dbus-1/services/`; the package files under `/usr/share` remain
untouched and therefore cannot advertise desktop-only systemd units to the
greeter. Both managed commands set `QT_NO_XDG_DESKTOP_PORTAL=1`, so neither
`ksecretd` nor `kwalletd6` attempts to register itself as a host portal
application while ordinary Qt applications retain their normal portal
integration. The managed KWallet unit uses `org.freedesktop.secrets` as its
systemd D-Bus readiness name and introspects the Secret Service interface before
dependent clients may start; acquiring only the portal-backend name is not
sufficient for Electron secure storage. The managed
`labwc-autostart` helper imports the live Wayland environment and immediately
activates `labwc-session.target`, making the package-owned portal services
available for D-Bus activation before ordinary desktop clients request
`org.freedesktop.portal.Desktop`. As the compositor's single managed startup
hook, it then uses `labwc-output-watch` only for one bounded, passive readiness
probe before launching later session clients. The persistent
`labwc-output-watch.service` has no readiness `ExecStartPre`; after the session
target starts it applies managed policy once, then coalesces later connector
hotplug events. A failed startup probe therefore cannot put the persistent
watcher into a timed restart loop or repeat the same DRM transition every
twelve seconds.
Readiness requires
`wayland-info` to observe a client-visible `wl_output` with a current mode; an
output-management head reported by `wlr-randr` is not sufficient. The passive
startup probe never changes output state. Independently, the persistent watcher
applies managed policy once before opening its udev monitor, then coalesces only
connector hotplug or connector add/remove events before one settled refresh;
DRM `change` events without connector hotplug evidence do not reapply output
policy. Output-dependent units such as Foot and the output
watcher retain their own readiness gates rather than delaying the entire
session target. Every managed desktop profile disables Kanshi, leaving the
repository-owned watcher as the sole output-policy owner; the
tracked Kanshi wrapper exits cleanly when that policy is false.
Every managed desktop profile also exports
`WLR_SCENE_DISABLE_DIRECT_SCANOUT=1` for the user Labwc compositor. Accelerated
application surfaces remain GPU-rendered but stay in the compositor path rather
than being promoted to a DRM scanout plane. This removes the direct-scanout
plane-promotion path associated with the atomic contention observed while
RetroArch, Zoom, Discord, and nested Cage applications were active. This policy
is not applied to the greeter.
`labwc-output-watch` owns both persistent DRM monitoring and explicit
`--refresh`/DPMS actions. Its typed Moo runtime serializes output changes,
re-applies the saved DPMS topology, and confirms Labwc has committed its output
geometry before re-seating session chrome. Foot's vendor service remains
available for socket activation but is not eagerly linked into
`labwc-session.target`; only `foot-server.socket` is session-enabled, and both
units require the active Labwc target while the service repeats the bounded
client-visible readiness check before executing Foot. Fuzzel, the XFCE helper,
the local `foot.desktop` override, and `labwc-terminal` use `footclient` with an
explicit `$XDG_RUNTIME_DIR/foot.sock`, matching Debian's `foot-server.socket`
instead of first probing the absent Wayland-specific socket. Managed Foot
windows therefore share that server without a fallback warning. Missing
`footclient` falls back to Kitty rather than starting standalone Foot, and
reverse target ordering stops the server before the compositor.
The managed wtmpdb PAM profile keeps normal interactive and greetd accounting.
The installer atomically reconciles exactly one package-generated wtmpdb entry
in `common-session` without invoking `pam-auth-update` or rebuilding any PAM
authentication stack. The managed controls skip `pam_wtmpdb` only for
`service=login` with an empty `PAM_TTY`; this excludes systemd's transport-only
user-machine bridge from opening a database record that its unprivileged close
helper cannot update.
Systemd-owned Waybar instances start only after the compositor-owned
`labwc-session.target` is active. Outside an authenticated reboot or power-off,
the output helpers never stop `labwc-session.target`, the compositor, or an
arbitrary user application. The watcher only cancels its own debounce and
udev-monitor child processes. Before a destructive managed output transition,
the refresher synchronously stops only the systemd-owned Crystal Dock, then
restores it after output readiness; its remaining non-blocking requests are
limited to Waybar and Crystal Dock, and it does not manipulate Fuzzel or other
application PIDs.
The per-account target disables systemd's default target-after-member ordering
so Waybar and the other session-bound user units can be both wanted by and
ordered after the Labwc lifecycle boundary without an ordering cycle.
Account-local Labwc services combine `Requisite=` and `PartOf=` with
`labwc-session.target`, bind directly to `labwc-compositor.service`, and keep all
ordering on one compositor-first `After=` line. Root-owned package-service
drop-ins cannot use the hard `Requisite=` because they also load in the greeter
user manager, where the account-local target does not exist. They still use the
imported desktop environment, compositor `BindsTo=`, one combined `After=`, and
`PartOf=`; D-Bus-facing services also verify that the target is active before
execution. Target or compositor stop therefore propagates to loaded desktop
children without making greeter-side activation resolve a nonexistent unit.
`labwc-logout` queues a non-blocking stop of `labwc-session.target` rather than
signalling the compositor directly. This creates one target-first transaction:
reverse ordering stops desktop clients while the Wayland socket is still
usable, then stops the target, and stops the compositor last. Authenticated
power transitions stop the same user target before the system transition
proceeds. The Labwc shutdown hook only validates its invocation mode and
performs no teardown: Labwc launches it asynchronously while compositor
termination proceeds, so a non-blocking stop cannot preserve client ordering,
while waiting for the compositor-owning target would be self-referential. The
compositor wrapper only clears imported Labwc, Wayland, and X11 activation
variables after Labwc exits; the systemd user manager remains the sole owner of
ordered session-unit teardown.
Systemd may still journal an ignored destructive-transaction diagnostic when a
sound, smart-card, or rfkill device emits `SYSTEMD_WANTS` or
`SYSTEMD_USER_WANTS` after its manager has already queued shutdown. This is the
upstream issue [systemd/systemd#38987](https://github.com/systemd/systemd/issues/38987),
not a failed Labwc session stop; do not override Debian's udev rules or vendor
shutdown targets to hide it.
`gvfs-daemon.service` uses `KillMode=mixed` and a 15-second stop ceiling so
the main daemon can first release its FUSE and mount helpers without losing
systemd's bounded final cgroup cleanup.
Suspend, reboot, and power-off keep `labwc-admin-action` in the initiating
desktop process. The helper validates its fixed action allowlist and the
private user runtime directory, then holds one non-blocking runtime lock across
the foreground `pkexec` request for the root-owned
`labwc-admin-action-root` helper. The exact-program `03-labwc-power.rules`
policy precedes the generic active/local gate and returns `AUTH_ADMIN` only for
members of `sudo`, so Hyprpolkit displays the administrator-password prompt
without relying on a display manager or login1 to classify the session active.
Concurrent button invocations therefore fail visibly before a second Polkit or
PAM conversation can begin.
The root helper independently requires a valid non-root `PKEXEC_UID`, resolves
and validates that account through NSS, and accepts only `suspend`, `reboot`, or
`poweroff`. It then queues the fixed
`labwc-admin-action@<uid>-<action>.service` instance without waiting. PID 1
starts the separately confined `labwc-admin-action-worker`, so stopping the
requester's `labwc-session.target` cannot kill the authenticated action as a
descendant of `waybar.service`.
The worker revalidates the numeric UID and NSS identity. Suspend queues the
matching absolute `systemctl` power verb without pre-draining the desktop. For
reboot and power-off, the worker first uses systemd's
`--user --machine=<account>@.host` connection to synchronously stop
`labwc-session.target` under a 45-second ceiling. Reverse user-unit ordering
stops output hotplug handling, audio, Bluetooth clients, virtualization, and
the remaining session clients while the compositor, user bus, hardware, and
system services are still available; the worker then queues the exact system
power verb even if that bounded best-effort pre-drain reports an error.
A rejected, cancelled, or failed request leaves Labwc and
`labwc-session.target` running and produces a persistent critical Mako
notification. The helper never calls the lifecycle hook out of band, acquires
a recursive shutdown inhibitor, or changes authorization-agent state.
Hyprpolkit remains available while the request is pending and stops through
`PartOf=labwc-session.target` only after authentication succeeds and the root
helper has queued the PID-1 worker that begins the bounded session pre-drain.
The shared Tailscale service drop-in orders `tailscaled.service` after
`NetworkManager.service` and `network.target`, retaining the physical network
until its bounded 30-second shutdown completes. Upstream `tailscaled` performs
best-effort cleanup before every daemon start, so the image adds no duplicate
pre-start helper and clears the package's redundant post-stop cleanup. The
drop-in filters only the exact startup no-op for an absent configured TUN link
and Tailscale's deterministic non-fatal
`ipnext: work queue shutdown failed: execqueue shut down` diagnostic; real
router, DERP, and control-plane failures remain visible. The shared daemon
defaults also pass `--no-logs-no-support` for every profile, retaining local
journal output while disabling uploads and Tailscale technical support.
Systemd eagerly starts and directly owns `ksecretd` and `hyprpolkitagent`
through `labwc-session.target`. The Hyprpolkit drop-in applies bounded
failure-restart and stop behavior. Autostart waits for those services and the
selected portal services to report active before it starts Waybar. Debian's
package D-Bus service files own the portal, compatibility, and `kwalletd6`
names; the account-local service directory adds only the otherwise missing
`org.freedesktop.secrets` alias. The managed `ksecretd` unit is considered
active only after that generic Secret Service name is owned and its standard
service object can be introspected. `kwalletd6` therefore starts on demand without
duplicating package service names or racing an eager custom daemon unit.
Bitwarden launches through transient user services that require and are
requisite on the active Labwc target and Secret Service, use main-process-first
termination, and stop before those session dependencies. The AppArmor
transition to `systemd-run` preserves the launcher's validated
`XDG_RUNTIME_DIR` and `DBUS_SESSION_BUS_ADDRESS` instead of applying secure-exec
environment scrubbing. Upstream's exact
native-messaging listener directories are created privately, while AppArmor
grants only the exact proxy, manifest, socket, and applicable log names in each
target. The
installer and managed updater retain a fail-closed repack of the vendor Debian
package whose size-preserving ASAR patch copies `desktop_proxy` directly and
therefore never attempts a cross-filesystem or protected hard link; package
identity and Debian `md5sums` are revalidated after the transformation. Runtime
updates also inspect `/proc/*/exe` under the updater's confined profile before
any package transaction, offline repair, or atomic `/opt` publication. The
protected inventory covers Bitwarden, Zoom, Filen, ChatGPT/Codex Desktop,
Obsidian, Sleek, QoreDB, Discord, Postman, Tuta Mail, and Ledger Live. Exact
launcher paths are combined with each application's installed executable root,
so resident helper and renderer processes are detected even when their
executable symlink already carries Linux's ` (deleted)` suffix. Normal
process-exit races are ignored, but every other inspection failure aborts the
apply path. A validated artifact remains retained instead of replacing an
in-use application tree; the application-neutral notifier tells the user to
close the program before the next apply attempt. For Bitwarden this also avoids
an integration-created mixed-generation main/renderer resource set while the
Secret Service readiness gate addresses secure-storage startup ordering.
Systemd also directly owns `labwc-health-notify`; the notifier performs its
signal trap and display/socket preflight before its ten-second coalescing delay,
terminates the delay child on target stop, and exits successfully. The service
uses no separately killable `ExecCondition` control process. No shared
session-child wrapper, user-unit stop, synchronous GVfs/FUSE unmount, process
signal, clipboard clearing, or global `sync` runs in the compositor shutdown
hook. The Labwc session wrapper only clears imported compositor environment
after Labwc exits; systemd owns user-service and socket teardown. Because systemd drop-ins
cannot remove dependency directives from Debian's vendor unit, the role
installs a complete managed `waybar.service` that contains no
`graphical-session.target`
relationship and follows the same three-directive Labwc lifecycle contract. It
is deliberately not enabled from a user target. After a
profile-owned two-second delay, `labwc-autostart` starts it only when
`LABWC_ENABLE_WAYBAR` is enabled, waits for a healthy systemd-owned process,
stops a failed job, and only then uses the bounded direct fallback. The unit
names the rendered config and style explicitly and sets a deterministic `PATH`
for managed custom-module helpers. The Unity tray compatibility drop-in
records both standard streams in the user journal with
`SyslogIdentifier=waybar`, keeping startup, module, and tray failures
diagnosable while the internal and external bar definitions remain aligned
without duplicate processes.
Crystal Dock is synchronously quiesced through its `systemd --user` service
before managed output destruction and is started again after readiness,
preserving the authenticated desktop user's environment and configuration. A
connected HDMI output overrides every other connector: the first HDMI output
is placed at `0,0`, while internal panels and all other external outputs are
disabled. The greeter follows the same HDMI-first policy, otherwise selecting
the internal panel before using a non-HDMI external connector as a last resort;
it starts on the first usable Wayland output without a fixed sleep or Labwc
auto-enable race. Without HDMI, the automatic topology policy extends the first
internal panel across every connected external output on laptops, but keeps
stationary systems external-only when no eDP, LVDS, or DSI connector is
present. Internal and external connectors use separate preferred-mode
settings, and unsupported preferences fall back to the connector-reported
preferred mode.
Mako receives local mail, disk, thermal, memory, battery, restart-required,
managed-software, Timeshift, authentication, USB/hardware-hotplug, storage-error,
AppArmor-denial, firewall-drop, calendar-sync, OCR, and managed desktop-action
events. Rsyslog writes the full authentication, USB, AppArmor, nftables, and
storage records to protected `root:adm` logs. The desktop bridge consumes
root-owned category-only signal files below
`/var/lib/labwc-notifications/security`. Those files are restricted to the
dedicated `logreader` group. The primary desktop account is added only to that
group, allowing the notification bridge to read sanitized event counters
without granting access to the underlying authentication, audit, AppArmor,
nftables, USB, or storage logs. Auditd keeps `/var/log/audit/audit.log`
authoritative for `ausearch`; rsyslog tails that file directly with `imfile`
and writes the dedicated managed audit and AppArmor logs. The audit syslog
dispatcher stays disabled and security-class staging masks journald's audit
socket, so audit events do not traverse or consume the journal.
Timeshift results are queued under `/var/lib/labwc-notifications/timeshift` so
snapshots taken without an active desktop session are reported on the next
Labwc login instead of being discarded. Started, completed, and failed
snapshot events are delivered independently; persistent timer catch-up runs
are serialized, and notification-queue errors do not replace the Timeshift
process status.

The greetd Labwc session renders gtkgreet with a dedicated 17px typography
baseline instead of inheriting the desktop-wide GTK size, and the login clock
uses a prominent 104px size. The greeter client executes
`gtkgreet --layer-shell`, so GTK creates a native full-output layer surface
rather than a decorated `xdg_toplevel` window. The greeter-only Labwc
configuration contains no `wtf.kl.gtkgreet` fullscreen rule. Its output helper
applies the same HDMI-only override with scale `1`, keeping the layer surface on
the selected output's complete logical geometry.
External greeter outputs first request the profile-owned
preferred external mode, normally `1920x1080` at the configured refresh rate,
and retry with the connector-preferred mode when that exact mode is
unavailable. This keeps the greeter comfortably sized on high-resolution
external monitors without the half-width logical canvas caused by scale `2`.
The isolated greeter process tree sets `GTK_USE_PORTAL=0` and
`GIO_USE_PORTALS=0`, preventing its GTK applications from requesting
desktop-only portal activation from the `_greetd` user manager. The real
desktop session retains normal portal integration after Labwc imports its
Wayland environment into the desktop account's user manager.
Labwc also auto-enables DRM outputs, and a transient output-helper failure is
logged but does not terminate gtkgreet before it can create a login session.
Labwc suspend, reboot, and power-off keep one foreground `pkexec` request in
the desktop process. The dedicated exact-program Polkit rule leaves one
Hyprpolkit administrator prompt for the requested power transition regardless
of which display manager launched the managed Labwc Wayland session.
The greeter owns only tty1 and has no Labwc bindings for `Ctrl+Alt+F2` through
`Ctrl+Alt+F6`; normal Linux VT handling therefore reaches the standard recovery
gettys on tty2 through tty6, while `Ctrl+Alt+F1` returns to the tty1 greeter.

F2FS desktop profiles render a slightly smaller internal-panel typography
baseline across Labwc, GTK, Qt, Waybar, Fuzzel, gtkgreet, and Crystal Dock.
Chromebook-specific F2FS profiles retain their more compact dock and panel
geometry while sharing the same reduced Qt font baseline.

Application shortcuts use `Super+F` for Thunar, `Super+B` for Vivaldi,
`Super+T` for the managed Foot terminal, `Super+E` for Tuta Mail, `Super+P`
for Bitwarden, `Super+W` for Wayscriber, `Super+S` for Spotify, `Super+C` for
Qalculate, and `Super+O` for Filen. Power and output refresh remain available
on `Super+Shift+P` and `Super+Shift+O`.

The same application actions are also available on
`Ctrl+Alt+F/B/T/E/P/W/S/C/O/A`, including `Super+S` and `Ctrl+Alt+S` for Spotify.
`Ctrl+Alt+Space` opens the Fuzzel application launcher.

Mako owns the session D-Bus `org.freedesktop.Notifications` destination through
the dbus-broker compatibility alias. Pure-privacy application sandboxes may
talk only to that notification destination and the existing portal names
through their filtered `xdg-dbus-proxy` session bus. Privileged services must
not use the user session bus directly; they queue bounded printable records
with `/usr/local/sbin/labwc-notify`, and `labwc-health-notify` relays trusted
root-owned events from `/var/lib/labwc-notifications/system` after a Labwc
session is active.

The managed Fruux calendar action runs collection discovery for both calendar
and task pairs before every synchronization. Vdirsyncer retains the downloaded
VEVENT and VTODO resources as local `.ics` files below
`~/.local/share/calendars/personal` and
`~/.local/share/calendars/tasks`, where other desktop applications can import
or inspect them without contacting Fruux directly.

The `labwc-plans` user service is wanted directly by
`labwc-session.target` and polls the primary account's
`~/Syncthing/sleek/*.txt` files. It accepts only
active `(A)`, `(B)`, and `(C)` entries, sends a one-time notification for each
new entry, and persists per-channel delivery state so Telegram and ntfy
failures are retried independently after connectivity returns. Date scheduling
uses `t:` as the recurrence start, `due:` as an inclusive end, and
`rec:N[d|b|w|m|y]` for day, business-day, week, calendar-month, and
calendar-year intervals; month- and year-end recurrences clamp to the final
valid day when the original day does not exist. Timed entries receive reminders
at 60, 45, 30, 15, 10, and 5 minutes before the event plus the event start;
every occurrence also receives a 10:00 local-time notification. The first
daemon scan does not replay past scheduled reminders; subsequent restarts catch
up from persisted state. The installer renders the outbound Telegram API key
and chat ID from `telegram_api_key=` and `telegram_chat_id=` kernel arguments,
falling back to
`PRESEED_TELEGRAM_API_KEY` and `PRESEED_TELEGRAM_CHAT_ID` from `/preseed.env`
only when the corresponding kernel argument is absent, into root-owned,
primary-group-readable `/etc/default/labwc-plans`. The user manager loads that
file with `LoadCredential=` and parses only its private `%d/labwc-plans.env`
copy; the confined daemon no longer opens the persistent credential source.
The configured ntfy topic remains `labwc_plans_notify`. The same protected
configuration backs the installed
`/usr/local/bin/telbot` terminal wrapper. `telbot -m "text"` uses
`sendMessage`, `telbot -u PATH` uploads an unchanged file with `sendDocument`,
and `telbot -c IMAGE` sends an image with `sendPhoto`; captions, plain/HTML/
MarkdownV2 formatting, silent delivery, protected content, photo spoilers,
link-preview suppression, stdin text, and bounded timeout overrides are
documented by `telbot --help`. The wrapper validates the root-owned
configuration and local upload before making one non-retried HTTPS request, and
never places the bot token in a child-process argument.


Foot and the Kitty fallback render their font family and size from the selected
desktop profile through `LABWC_TERMINAL_FONT_FAMILY` and
`LABWC_TERMINAL_FONT_SIZE`; the managed profiles preserve the existing
`Noto Sans Mono` size `12` baseline. Logical Foot selections are translated to
`footclient --server-socket=$XDG_RUNTIME_DIR/foot.sock`, preserving xterm-style
`-e` for the socket client while removing that incompatible flag before a Kitty
fallback. RetroArch retains the managed OpenGL video driver and PipeWire-backed
audio, while `midi_driver = "null"` prevents its optional ALSA MIDI backend from
probing `/dev/snd/seq`; no raw ALSA sequencer access is granted.

Each new interactive Bash or Zsh instance in Foot or Kitty sources readable,
non-symlinked `~/.profile.d/[0-9][0-9]-*.sh` fragments in lexical order. Login
shells keep the fragments single-loaded, while non-login terminal shells still
pick up managed addon helpers such as development, firmware, and Incus
commands. Zsh keeps its general completion cache but disables persistent
`DEBS_*` package caches for `apt`, `apt-get`, `apt-cache`, and `apt-mark`, so
`sudo apt install <TAB>` builds candidates once in memory per shell without
re-sourcing a malformed `DEBS_avail` file. Nano uses the managed XDG
configuration at
`~/.config/nano/nanorc`, with line numbers, indentation and navigation
defaults plus the standard, Debian-specific, and extra syntax-color bundles
shipped by the installed `nano` package.

The opt-in `devops` command starts a nested interactive shell in the caller's
current terminal and working directory. Its activated environment remains
confined to that shell, which is titled `[devops]`; managed Zsh `precmd` and
`preexec` hooks keep that title visible while it is active. The QEMU addon
instead exports only Incus's native account-local `INCUS_CACHE` and
`INCUS_CONF` path selectors; it starts no activation shell and does not alter
daemon state, the selected project, or the selected remote.

With `addon/devops`, the managed Codex and ChatGPT/Codex launchers
reconstruct the profile environment with POSIX `/bin/sh`. They source the
mandatory `~/.profile.d/71-devops-de.sh` first, followed by installed
`72-incus.sh` and `75-firmware-workspace.sh` fragments in fixed order, and
reject unsafe ownership, links, malformed exports, or incomplete class-specific
state. A validated active DevOps shell may contribute additional normalized
absolute `PATH` entries, but it must contain every clean reconstructed entry.
The final exported variables and ordered path are passed to the Codex payload in
both sandboxed and explicit `--no-bwrap` modes; ChatGPT uses the same clean
profile contract after clearing ambient state.

The installer-stage standalone package is deliberately separate from the
checksum-pinned repository build that remains the public `codex` command. The
official `https://chatgpt.com/codex/install.sh` script resolves its current
standalone version noninteractively inside a private staging `CODEX_HOME` and
an isolated shell `HOME`. Its visible command and any shell-profile edits are
discarded, so the standalone binary is never added to the account or managed
payload `PATH`. Before publication, the installer-created absolute
`standalone/current` selector is validated and rewritten as a relative
`releases/<release>` link. The relocatable package cache is then atomically
moved to `/data/codex/packages`; the fixed `/data/codex/usr/home/packages` link
exposes it only for official app-server daemon discovery and the managed control
socket. A failed download, install, normalization, or publication removes
private staging without publishing partial package state.

The launcher makes these locations authoritative instead of trusting inherited
values:

```text
CODEX_AGENTS=/data/codex/usr/agents
CODEX_HOME=/data/codex/usr/home
CODEX_LOG_DIR=/data/codex/log
CODEX_SKILLS=/data/codex/usr/skills
CODEX_SQLITE_HOME=/data/codex/sqlite
```

Build, cache, and database exports resolve below the account's
`/pool/{build,cache,db}/<user>` roots. Python bytecode/runtime and Ansible
temporary, persistent-connection, and SSH control paths resolve below private
mode-`0700` `/run/user/<uid>/python` and `/run/user/<uid>/ansible` trees. The
real `~/Workspace`, shared downloads, Codex home/log/SQLite state, and the
managed work roots remain writable; selected development configuration and
installed toolchains remain read-only unless their contract names a writable
state path.

`/data/codex/usr/.git` is the real metadata directory from the pinned clone, not
a tmpfiles-created placeholder. Installation uses `git clone --no-hardlinks`,
rejects symbolic links, special nodes, and multiply-linked files, assigns the
desktop account and `devops` group recursively, and normalizes the root and
child directories to `0750` and files to `0640`. Launch-time validation repeats
type, path, owner, mode, and write checks. `$CODEX_HOME/memories/.git` is a
direct single-link regular marker owned by the desktop account and `devops` at
mode `0660`; it is writable and is not rebound read-only.

The Codex Bubblewrap namespace contains synthetic passwd/group/NSS data and a
private resolver directed at the `slirp4netns` DNS endpoint. It preserves
outbound network access without importing host identity or the host abstract
Unix-socket namespace. Bubblewrap uses a private PID namespace and exactly one
`--proc /proc`; host `/proc` is never bind-mounted. The supervisor waits for
Bubblewrap PID metadata and slirp readiness, rechecks both helpers, and releases
the payload block descriptor only after readiness is stable.

Before executing Codex, the generated payload launcher verifies that inherited
active capability sets are zero, that the required namespace capability remains
available only in the bounding set, and that a real nested Bubblewrap invocation
can create its own user/PID namespace and private procfs. This fail-closed probe
covers nested Codex tools such as `apply_patch`. All readiness, information,
block, and exit descriptors are bounded and closed on every path; signal and
`finally` cleanup terminates and reaps Bubblewrap/slirp children and removes the
private control tree while preserving the payload status.

Managed ChatGPT and the isolated desktop applications create filtered session
and system endpoints with `xdg-dbus-proxy`; they never bind the host system-bus
socket directly. Proxy readiness requires the correct marker and EOF behavior.
Proxy liveness is checked before network setup and again after slirp readiness,
immediately before payload release. An early exit blocks launch, and partial,
failed, interrupted, and successful paths terminate/reap every proxy and remove
its socket. `dbus-broker` remains the package-owned user bus with centrally
installed hardening. Static tests prove these construction and teardown
contracts; a fresh installed Labwc session is still required to prove live
Wayland geometry, external DNS/HTTPS, and a disposable real nested
`apply_patch` invocation.
`addon/qemu` installs direct QEMU/KVM plus confined Incus. The explicit package
set contains QEMU x86, OpenGL modules, utilities and block extras, OVMF, swtpm,
virtiofsd, passt, Incus, its client and Canonical UI payload, uidmap, libosinfo,
and genisoimage. Libvirt, virt-manager, Vagrant, classic LXC, and standalone
LXCFS are absent. The selected APT preference pins the complete Incus provider
set to Zabbly and blocks Debian's LXCFS-dependent Incus packages. The late
helper verifies the packages, direct QEMU and Incus executables, packaged
units, UI-aware daemon wrapper, and UI payload before it stages the root-owned
policy.

The rendered tmpfiles policy creates only `/pool/qemu` and `/pool/incus`.
Direct QEMU may attach only to the managed Incus bridge from
`/etc/qemu/bridge.conf`. The qemu nftables overlay admits guest DHCP, DNS,
forwarding, and masquerading only on that bridge; no Incus HTTPS port is
opened. The account receives `kvm` and restricted `incus` membership, while
root-equivalent `incus-admin` membership is rejected.

Only `incus.socket` and `incus-user.socket` are enabled. Boot-target links for
the daemon, package LXCFS companion, startup helper, restricted user broker,
and repository host unit are removed, so no Incus service process starts at
boot or login. A first client request reaches `incus-user.socket`; the tracked
package-unit drop-in requires the static `incus-host-managed.service`, which
starts the package daemon and shutdown helper and reconciles the host before
the restricted user broker serves the account.

`incus-host-managed` validates the administrator and restricted Unix sockets,
creates or verifies the `local` directory pool on `/pool/incus`, reconciles
`incusbr0`, binds the default profile to that pool and bridge with
`security.privileged=false`, rejects a configured `core.https_address`, and
requires the packaged `/ui/` endpoint to answer over the local administrator
socket. Its AppArmor profile grants only the exact managed files, units,
sockets, UI payload, `/pool` roots, and Unix-stream access. The account's
normal `incus` and `incus webui` commands use the confined client path with
native cache and configuration directories below its managed `/pool` roots,
without requiring a persistent network listener. The host
unit has no custom stop command, leaving orderly instance shutdown to the
package-owned startup service in reverse dependency order. Codex and ChatGPT
receive no libvirt/Vagrant environment or runtime-socket injection.

Waybar keeps the existing `LABWC_WAYBAR_*` values as the external/default bar
dimensions and adds `LABWC_WAYBAR_INTERNAL_*` overrides for the internal-output
bar. The internal family covers bar height, taskbar/tray icons, font size, menu,
workspace, taskbar and application buttons, compact status modules, quick
controls, and lock/power button widths and padding.

`Super+M` and `Ctrl+Alt+M` open the searchable **Computer Management**
Fuzzel launcher.
Its folder-style categories are Container Management, Remote Desktop,
Endpoint Security, Digital Assets, Users & Groups, Network Management, System
Configuration, Phone Management, Backup & Recovery, and Hardware &
Peripherals. Firewall Security is nested below Endpoint Security instead of
competing with it at the Computer Management root. The former
`Ctrl+Super+A`, `Ctrl+Super+N`, `Ctrl+Super+P`, and `Ctrl+Super+R` bindings are
retired so laptops and stationary systems share one management navigation
model. Each category can override the shared Fuzzel menu sizing through
`LABWC_FUZZEL_<CATEGORY>_WIDTH`, `LABWC_FUZZEL_<CATEGORY>_LINES`, and
`LABWC_FUZZEL_<CATEGORY>_FONT_SIZE`, where `<CATEGORY>` is
`CONTAINER_MANAGEMENT`, `REMOTE_DESKTOP`, `ENDPOINT_SECURITY`,
`DIGITAL_ASSETS`, `USERS_GROUPS`, `NETWORK_MANAGEMENT`,
`FIREWALL_SECURITY`, `SYSTEM_CONFIGURATION`, `PHONE_MANAGEMENT`,
`BACKUP_RECOVERY`, or `HARDWARE_PERIPHERALS`.

**Network Management** and the Waybar network module's right-click action use
the same `labwc-network-control-menu` backend. OpenVPN imports retain their
bounded user-owned file workflow, but WireGuard imports are deliberately
administrator-provisioned: only direct, non-symlink `*.conf` files below
`/data/config/network/wireguard` are accepted. The desktop tmpfiles policy
creates `/data/config/network/wireguard` as `root:devops` mode `0750`; accepted
profiles are root-owned, at most 1 MiB, and mode `0400`, `0440`, `0600`, or
`0640`, with group-readable profiles restricted to the `devops` group. Both
the unprivileged client and the root helper revalidate the canonical path and
metadata before the existing fixed-argument
`nmcli connection import type wireguard file ...` call. No `$HOME/.config`
WireGuard discovery, `wg-quick`, or competing resolver path is used.
NetworkManager remains the connection and DNS owner and continues to integrate
with the managed systemd-resolved/`resolvectl` compatibility path.
`networking.service` is ordered after `dbus.service` and
`systemd-resolved.service`, so reverse shutdown keeps both available until
Debian's ifupdown `if-down.d/resolved` hook has completed its final
`resolvectl revert` call.

**Computer Management → Digital Assets** opens DOCX, PDF, and image action
menus. Inputs are bounded regular files chosen only from `~/Downloads`,
`~/Documents`, and `~/Desktop`; original files are never overwritten, and
results are created with private permissions below
`~/Documents/Digital-Assets`. The desktop package set provides Pandoc, QPDF,
Poppler, ExifTool with ZIP support for DOCX metadata, GraphicsMagick, libvips,
WebP, OptiPNG, and JPEGoptim. The late-command checksum-verifies pinned
`pdfcpu` and Typst archives, installs them below `/usr/local/lib` with fixed
`/usr/local/bin` links, and builds the Pipx **code** environment for
`pdf2docx` and `pymupdf4llm` with a temporary locked non-root account. Its
Pipx state and private build home are below `/usr/local/lib/digital-assets`;
the installer removes the build account and its state before sealing the shared
runtime as `root:root` and non-user-writable; a non-forced account removal
fails the install rather than sealing if the builder cannot be removed. Root
ownership protects the shared interpreter and imported modules; it does not
grant root execution to document actions. The launcher and action dispatcher
reject UID 0. Conversions, temporary workspaces, and outputs therefore run as
that logged-in user without `sudo`, `pkexec`, or setuid helpers. The action
wrapper starts the interpreter with a minimal environment plus isolated,
no-bytecode Python mode (`-I -B`), so it neither imports user-site packages nor
honors Python environment overrides, and it keeps library scratch files in the
private runtime workspace.
Pandoc always uses Typst as its PDF engine, so this workflow does not require a
LaTeX stack.

PDF content editing creates a reflowable Markdown working copy, runs
FocusWriter with native Wayland backends forced, and builds a new PDF with
Pandoc plus Typst. It cannot preserve original page geometry, forms,
signatures, annotations, or exact layout. PDF bookmark editing exports a
private `bookmarks.json` working copy for Nano and imports it with pdfcpu into
a new validated PDF. QDF hyperlink/typo edits use a bounded literal byte
replacement followed by `fix-qdf` and QPDF validation; they invalidate
signatures and do not preserve source encryption.

Endpoint Security keeps selected
file and folder operations
unprivileged, while fixed host-wide audits and signature updates use the
existing desktop-owned `10-pkexec.rules` policy and a root helper. System provides
firmware, package, NVMe, Btrfs, journal, resolver, user-service, notification,
Waybar, and external-drive maintenance alongside the existing host inspection
actions. `Manage External Drives` inventories only USB disks and their direct
volumes, reports mounted state, and serializes its actions within the active
desktop session. Before unmounting, it runs a bounded `syncfs` operation for
each mounted filesystem, revalidates the USB device identity, delegates the
unmount to UDisks, and waits for the kernel mount table to confirm that the
volume disappeared. Whole-drive power-off first synchronizes every mounted
child, then cleanly unmounts and confirms every child in order, rechecks that
none remain mounted, and only then asks UDisks to power off the parent disk.
Any sync timeout, changed device identity, busy volume, unmount-confirmation
timeout, or remaining mount leaves the drive powered and never triggers a
forced or lazy unmount. The flow is filesystem-neutral, including F2FS.
The desktop APT policy blocks the optional cramerz OBS Release during normal
resolution, so `labwc`, `libwlroots-0.20`, and related packages come from
Debian Forky. The archive remains configured only for explicit administrative
selection with `package/Debian_Unstable` or `apt-get -t Debian_Unstable`; it is
not an automatic upgrade source for the compositor stack.
The desktop package set explicitly selects `thunar/forky`, keeping Thunar's
native GIO/UDisks device actions on the Forky package line with the upstream
unmount/reload crash fixes. The `usbmedia` policy names the actual UDisks2
actions used by GIO and Thunar, including `filesystem-unmount-others`;
nonexistent `filesystem-unmount` and obsolete `drive-eject` action names are
rejected by target verification so a denied unmount cannot tear down the
browsing window without completing the requested operation. The Debian
`eject` utility remains installed for Thunar/GIO compatibility, but neither
the native path nor the managed launcher bypasses UDisks or forces a busy
filesystem offline.
Disruptive firmware, upgrade, journal, and audio actions require an explicit
second confirmation. Troubleshooting separates user-session restarts from explicitly
confirmed root repairs for services, caches, managed zram, Btrfs chunk reclaim,
dpkg/APT, initramfs, GRUB, and optional Timeshift snapshots. APT dependency
repair refuses package removals, and Timeshift selects Btrfs or rsync mode from
the installed root filesystem. Endpoint Security no longer duplicates port
inspection or Nmap entries; those actions live under Network Management
and use its dedicated bounded privileged helper.
Security file actions list bounded candidates below common home directories or
accept a manually entered absolute path. File hashing reports SHA-256 and
SHA-512 with a 10-minute ceiling per digest, and SHA-256 verification validates
the expected 64-character hexadecimal value before comparing it. Recursive
folder hashing stays on the selected filesystem, skips symlinks, accepts at
most 50,000 regular files and 100 GiB, and writes a private mode-0600 manifest
below `~/.local/state/labwc/security-reports`.
AppArmor is divided into Status & Events, Profile Drafts, App Modes, and
Policy Tools. It reports kernel
enablement, unconfined network processes, the active features ABI, recent
complain/denied events, disabled profiles, and unknown-profile cleanup in dry
run mode. The confirmed profile-generation flow covers `aa-easyprof`,
`aa-autodep`, `aa-logprof`, and `aa-genprof`; easyprof writes syntax-checked,
non-active drafts below `/var/lib/apparmor/easyprof`, while the other tools
publish syntax-checked drafts below `/var/lib/apparmor/drafts` rather than
editing active policy directly. Re-running those generators merges new draft
content into the existing non-active draft when that remains valid, or replaces
the stored draft with the newly generated syntax-checked profile when the merge
would be invalid. logprof and genprof consume
`/var/log/managed/apparmor/apparmor.log`, which rsyslog populates from AppArmor
kernel and audit events. Managed applications can change enforce/complain/
disable and audit logging with explicit confirmation. **Generate New Rules**
is a separately confirmed root action that parses bounded `DENIED` records from
the managed AppArmor log and maps only installed profile labels with an
unambiguous `local/*` include. It can add owner-qualified file permissions,
exact allowlisted low-risk capabilities, and access-qualified IPv4/IPv6 network
rules. Both `requested_mask`/`denied_mask` and the network audit
`requested`/`denied` field names are normalized before rule rendering.
Conservative path normalization replaces only owner-matched home, runtime UID,
and process-ID components; it rejects dot-segment traversal and does not invent
arbitrary recursive wildcards. Execute transitions, link permissions without a
reviewed source/target pair, non-allowlisted capabilities, non-IP network
families, sensitive paths, malformed masks, unknown classes, unconfined events,
and ambiguous profiles are reported but not granted. Generated rules are
confined to one managed marker block below
`/etc/apparmor.d/local/`, preserving manual content outside that block. Every
changed source is validated in an isolated include overlay before atomic
publication, then the exact source is reloaded; any validation, publication,
or reload failure restores the previous local include and reloads the restored
policy. The root-only transaction directory is provisioned by tmpfiles; the
generator fails closed rather than writing elsewhere below `/var/lib/apparmor`
when that directory is unavailable.

The App Modes menu also provides direct Enforce, Complain, and Disable toggles
for managed applications. Individual application-mode changes affect only the
selected application profiles. The global desktop-state action changes every
profile source declared in `/etc/apparmor/managed-modes.conf` together, using
the same complete set owned by `DESKTOP_APPARMOR_STATE`. Reloading the managed
modes clears temporary audit flags, while service-wide reloads remain
separately confirmed.
Draft maintenance lists and validates stored drafts without invoking `pkexec`.
**Activate Selected Draft** applies only the
explicitly selected root-owned draft after another syntax check.
Existing target profiles must retain the same parsed profile-label set and are
backed up below `/var/lib/apparmor/backup/`; activation failures restore and
reload the previous source automatically. New profile files are loaded using
the mode declared in their draft, while repository-managed profiles are
reconciled back to their configured mode. Activated drafts persist on that
installed host, but their required policy changes must still be incorporated
into the repository-managed source to survive a reinstall.
The shared fwupd refresh drop-in treats upstream exit statuses `2` and `101`
as successful no-op outcomes, preventing current metadata or unsupported
hardware from leaving `fwupd-refresh.service` failed. The daemon ordering
drop-in places `fwupd.service` after `upower.service`, so shutdown reverses the
dependency and stops fwupd before UPower when both services are active.
ClamAV status, file scans, and recursive folder scans run as the logged-in
desktop user, never follow symlinks or cross filesystems, and remain
report-only: infected files are not moved or deleted. File scans have a
15-minute ceiling, folder scans have a 45-minute ceiling, and the launcher
rejects regular files above the managed 512 MiB per-file limit instead of
silently skipping them. Official FreshClam data plus the SaneSecurity and
URLhaus providers managed by Fangfrisch update once a day through
`managed-clamav-signature-update.timer`; the vendor FreshClam daemon and
Fangfrisch timer are masked to prevent competing schedules.

**Computer Management → Network Management → Network Scanning** opens the
five-category scanner. Packet capture is delegated to
Debian's `wireshark` group through the package-managed
`dumpcap` capabilities, and only the primary desktop account is enrolled
automatically. Wireshark and TShark remain non-setuid and capability-free;
Nmap, Wireshark, Dumpcap, tcpdump, and TShark use the same folder-style
top-level icon as the three maintenance categories.
The Nmap category also owns listening TCP/UDP port inspection plus localhost,
LAN, specific LAN host, and explicitly authorized WAN host scans.
Wireshark can launch normally, while the managed `Open Capture` action accepts
only managed captures. Dumpcap, tcpdump, and TShark captures are
time/count/size bounded and stored privately below
`~/Captures/network-scanning`. Privileged tcpdump and Nmap actions require the
active desktop administrator through pkexec. Nmap actions use conservative
packet rates, per-host and per-script ceilings, and whole-command timeouts.
They accept RFC1918 or loopback hosts and `/24` through `/32` private CIDRs,
plus explicitly authorized public WAN IPv4 hosts. Public CIDRs and
protocol-assignment, shared, link-local, relay-anycast, benchmark,
documentation, multicast, or reserved destinations are rejected. The
approved-service check uses separate range-aware TCP and UDP catalogs covering
common infrastructure, directory, messaging, storage, observability, database,
virtualization, VPN, and application service ports. Lua 5.5 is installed
explicitly, and target verification parses every managed NSE script with
`luac5.5`.

**Computer Management → Phone Management** opens the Android Debug Bridge
launcher. The desktop late-command downloads Google's current Linux
Platform-Tools archive directly over HTTPS,
applies compressed/extracted size and member-count ceilings, rejects unsafe
paths and unsupported extracted node types, validates the required x86-64
payload, records revision and SHA-256 provenance, installs the full bundle
under `/usr/local/lib/android-sdk/platform-tools`, and links `adb` and
`fastboot` from `/usr/local/bin`. Installation does not invoke `adb`; the
per-user server remains stopped until **Start ADB Server** is selected. The
managed user unit permits Unix, IPv4, IPv6, and netlink sockets so the Google
daemon and libusb can monitor Android USB device changes. Menu selections,
bounded action outcomes and exceptions, daemon output, and systemd lifecycle
messages are routed to `/var/log/managed/adb/adb.log`; the generic Fuzzel logs
retain the same normalized menu and action audit events.
action helper detects and repairs an already-running hung current-user server,
waits for a selected serial to reconnect, requests offline transport reconnects,
and reports permission, offline, and RSA authorization problems explicitly.
The launcher covers server lifecycle, device inspection and shell access,
files/APKs, diagnostics and captures, wireless debugging, port forwarding,
confirmed reboot modes, and non-flashing fastboot inspection/reboot actions.
The primary desktop account is added to `plugdev`, and
`51-android-debug-bridge.rules` covers common OEM and chipset IDs only when an
Android debug, fastboot, or legacy debug USB interface is present. Preseed
stages the rule file but does not try to reload, exercise, or validate udev
device behavior inside the installer.
The Reboot & Recovery submenu adds **Backup Device** plus official Samsung
firmware download and flash actions. Backups are built atomically below
`~/Android/adb/backups` with private permissions and contain ADB-readable shared
storage, device/package/settings metadata, integrity hashes, a bugreport when
available, and a legacy Android Backup archive when the deprecated protocol is
still supported. They cannot capture app-private data that production Android
does not expose through ADB, hardware-backed keys, or protected partitions.

The desktop role pins the official samloader-rs 2.0.0 Linux x86-64 archive and
release SHA-256, validates its archive shape, ELF architecture, and version,
and installs it below `/usr/local/lib/samloader` with a managed
`/usr/local/bin/samloader` link. Downloads must match the connected Samsung
model, are decrypted and safely extracted under
`~/Android/adb/samsung-firmware`, and receive MD5, SHA-256, and provenance
validation. Flashing accepts only those managed directories, rechecks the
device model and components, requires exactly one supported Samsung Download
Mode USB device, and uses a typed confirmation. **Keep Data** supplies
`HOME_CSC_*.tar.md5`; **Factory Reset** supplies `CSC_*.tar.md5` and erases
device data. The managed udev rule grants access only to the Samsung Download
Mode product IDs supported by samloader-rs 2.0.0.

**Computer Management → Remote Desktop** opens the managed RDP frontend.
**Computer Management** is the only searchable management application; the
remote-desktop compatibility entry remains hidden for MIME associations. The
managed `freerdp-sdl` launcher resolves the staged SDL client as `sdl-freerdp` or the
older `sdl-freerdp3` compatibility binary, supports direct or explicitly shared-folder
connections, and exposes fixed, dynamic, full-screen, and multi-monitor display
choices. Dynamic windows use FreeRDP dynamic resolution without the mutually
exclusive smart-sizing flag. The launcher also supports optional device
redirection, private saved connection metadata, and explicit unreachable-target
diagnostics. The launcher requires the Labwc Wayland session, forces SDL's
Wayland backend, and removes the X11 display fallback from the client
environment. Passwords are never written to the saved connection store and are
requested through `FREERDP_ASKPASS` by a root-owned masked GTK askpass helper.
The default certificate policy leaves `/cert` unset so the SDL3 client presents
the remote server certificate with temporary trust, permanent trust, and cancel
choices. Strict profiles add `/cert:deny`. The launcher does not generate a
local RDP certificate or key and does not maintain a separate TOFU certificate
cache or reset path; permanent approvals remain owned by FreeRDP in the user's
configuration.

Taskwarrior and `taskwarrior-tui` share
`~/.config/task/taskrc`, store task data in `~/.local/share/task`, and expose
managed Pending, In Progress, and Completed reports with desktop-aligned colors.
Taskwarrior remains available from the application launcher and managed
terminal without occupying permanent Waybar space. Waybar places the Wayscriber
glyph directly after `ext/workspaces` and before the apps drawer, toggling the
overlay through the session-bound daemon helper. The vendor user service is
attached to `labwc-session.target`, conditioned on the active Wayland session,
restarted with bounded backoff, and run without its tray integration. The
drawer exposes Font Awesome glyphs for Foot, Thunar, Tuta Mail, FeatherPad, and
Sleek without loading native application icon assets. Tuta Mail and Sleek use
the managed `NvidiaAccelerated` launch mode; Foot, Thunar, and FeatherPad retain
their direct desktop commands. Tuta's persistent sandbox sees the managed
primary-user `mimeapps.list` read-only so it can confirm the default mail
handler correctly. Liferea is installed as the managed feed reader,
uses the system browser, and owns the RSS, Atom, RDF, and `feed:` MIME handlers.

Waypaper uses its selector-only backend and stores validated selections from
`/usr/share/backgrounds/desktop` in `~/.local/state/labwc/wallpaper`. Its
post-command restarts the single systemd-owned `swaybg.service` instance only
while `labwc-session.target` is active, so Waypaper never owns or kills a
separate swaybg process. The service automatically restarts only after an
unexpected failure. Labwc restores the saved PNG or JPEG on login and uses the
managed default whenever the state is absent or invalid.

Thunar uses the next supported icon and zoom step for its icon, details, compact,
shortcuts, and tree views; unsupported pixel-level GTK icon overrides are not
used.

### Managed application package, sandbox, and logging contract

The three isolated Python entrypoints use one root-owned
`labwc_managed_app` package. Fresh installation creates a private sibling
staging directory, fetches only the exact manifest, installs each module as a
root-owned mode-`0644` regular file under a mode-`0755` package root, validates
the complete staged tree, renames it atomically into its previously absent
fresh-target path, and validates the published tree again. A pre-existing
destination is fatal rather than treated as upgrade state.

Before importing implementation code, every entrypoint validates the complete
`/usr/local/lib/python3.14/dist-packages` trust chain and exact package
inventory. Modules must be direct, single-link, root-owned mode-`0644` regular
files. Symlinks, hard links, bytecode, `__pycache__`, unexpected files or
directories, FIFOs, sockets, devices, missing modules, ownership drift, and mode
drift identify the exact unsafe path and reason. The `native` scope excludes
compatibility-only modules, the `wayland-compat` scope covers the complete outer
launcher, and the inner `compat-runtime` scope contains only bootstrap,
integrity, event, runtime, and Cage-supervision code.

The package keeps stable `sandbox.py` and `environment.py` facades while
separating trust and operations by responsibility:

| Module | Owned responsibility |
| --- | --- |
| `bootstrap.py` and `integrity.py` | trusted scope selection and package inventory validation |
| `events.py` | bounded structured lifecycle records without application arguments |
| `bubblewrap.py` | the private PID namespace and procfs invariant |
| `dbus_proxy.py` | filtered session/system D-Bus proxy lifecycle |
| `network_namespace.py` | Bubblewrap PID handoff and bounded `slirp4netns` supervision |
| `mounts.py` | normalized home, device, runtime, and absolute bind construction |
| `identity.py` | deterministic synthetic machine, boot, hostname, and Codex installation identity |
| `user_state.py` | atomic current-user file and directory primitives |
| `sandbox.py` and `environment.py` | public orchestration facades used by the launchers |

Every desktop Bubblewrap constructor must create a private PID namespace and
supply exactly one `--proc /proc`; launch-time validation rejects a missing,
duplicate, or redirected procfs mount. Every confined `*-bwrap` child inherits
`managed-bwrap-common`, which permits the mount operations required to create
that private procfs. This does not bind the host `/proc` into the sandbox.

Filtered session and system D-Bus endpoints are created with
`xdg-dbus-proxy`; the host system-bus socket is never bound directly into a
managed namespace. Startup requires the expected readiness byte and EOF
semantics, then verifies every proxy remains alive before networking. When
slirp is enabled, proxy and Bubblewrap/slirp liveness are checked again after
slirp readiness and immediately before the payload block descriptor is
released. A proxy that exits in that window prevents application execution.
Every partial-start, success, failure, and interruption path closes descriptors,
terminates and reaps known children, unlinks proxy sockets, and removes the
private temporary root. The package-owned `dbus-broker` remains the user-bus
implementation and receives centrally staged hardening.

Native and outer compatibility lifecycle records use the
`labwc-managed-app` syslog identifier. Rsyslog writes them only to
`/var/log/managed/desktop/applications.log` and stops further processing; the
file is pre-created by tmpfiles and covered by bounded daily rotation.
ChatGPT retains its separate privacy boundary: lifecycle output goes to stderr,
the capture runner normalizes it and writes only through the protected OpenAI
rsyslog socket, and generic `/dev/log` access remains denied. The inner
Zoom/Discord runtime also emits to stderr so its transient user unit journals
the record without importing a syslog socket into the Bubblewrap child.

Computer Management exports the `computer-management` Fuzzel scope and the ADB
menu exports `android-debug-bridge`. The Perl writer bounds and normalizes every
field, uses only the `labwc-fuzzel-menu` or `labwc-fuzzel-action` identifier,
and rsyslog routes those records to
`/var/log/managed/fuzzel/{menu,actions}.log`. Android-scoped records also reach
the dedicated ADB log before the classified-record stop rule. Tmpfiles creates
all destinations with root/`adm` ownership, and logrotate keeps four daily,
compressed, size-bounded archives.

Repository tests reconcile every supplied diagnostic in
`todo/{Fail,Fail2,Fail3,Fail4,journalctl,apparmor.log}`, every supplied managed
log under `todo/managed/**`, and the copied ChatGPT/Codex logs under
`openai/**` without modifying those evidence files. Static fixtures prove
package publication, D-Bus failure cleanup, private procfs construction,
logging routes, and finite retention. Native layer-shell geometry, real target
D-Bus behavior, Mullvad GUI startup, Codex DNS/HTTPS, and nested `apply_patch`
still require a fresh installed desktop for live acceptance.

Managed application launchers live in the primary account's user-owned
`~/.local/share/applications` tree and are published with atomic replacement.
All managed home directories are mode `0700`; non-executable regular files,
including `~/.config/mimeapps.list` and generated desktop entries, are mode
`0600`, while owner-executable helpers remain mode `0700`. The login profile,
systemd user manager, and shadow account policy all use umask `0077`, and the
final finish-install hook reapplies this metadata-only policy across the fresh
account home after every late-command addon has finished.
This keeps Vivaldi's desktop-entry refresh writable, seeds private Vivaldi
profile/cache directories, and gives managed applications an explicit Debian
fontconfig path. Direct legacy Tuta AppRun launchers are removed so Tuta always
starts through the managed `/opt/tuta-mail/AppRun` sandbox contract. The
root-owned AppDir remains traversable at mode `0755`, including after managed
updates and interrupted-publication recovery. Every Tuta launch mode receives
the filtered session-bus allowlist for desktop portals, notifications, and
KWallet Secret Service names, but no system-bus socket. It also receives the
outer-sandbox-compatible `--no-sandbox` argument. Publication normalizes every
AppDir directory to mode `0755`, preserves root-only writes, and removes unused
set-ID bits.
Obsidian prefers the package-owned `/usr/bin/obsidian` launcher when it exists
so bundled runtime libraries resolve correctly, while `/opt/Obsidian/obsidian`
remains the validated payload anchor for managed publication. Native Wayland
normal, Intel, and NVIDIA desktop actions are preserved. When `addon/software`
is selected on `amd64`,
Postman is archive-validated and atomically published below `/opt/postman`; its
system launcher uses `/opt/postman/app/resources/app/assets/icon.png` from the
downloaded bundle and routes normal, Intel, and NVIDIA launches through
`/opt/postman/app/Postman`. Sleek `2.0.26` is installed as its pinned amd64
Debian package with `/opt/sleek/sleek` as the validated payload anchor, but
its managed launcher prefers the package-owned `/usr/bin/sleek` helper when it
is present. Filen uses the same launcher preference for `/usr/bin/{filen,filen-desktop}`
before falling back to `/opt/Filen/Filen`, and Telegram bootstraps its private
state tree under `~/.local/share/TelegramDesktop` before the vendor process
opens its session logs. KeePassXC likewise repairs its user-owned
`~/.config/keepassxc/keepassxc.ini` seed before the no-network AppArmor path
starts the database-scoped GUI.
Neither app exposes a PurePrivacy action because hiding user-selected API or
todo files would make that mode misleading. Chromium, Microsoft Edge, and
Vivaldi receive seeded system-frame preferences. Obsidian's global registry
receives `frame=native`, an empty vault registry, and no pre-approved external
URI schemes. A private default vault is staged at
`~/Syncthing/obsidian-md` and copied into the primary account; later accounts
receive the same tree through normal `/etc/skel` account creation. The runtime
launcher never reads the skeleton. Before Obsidian starts, it validates the installed
user-owned home vault and registry, derives a
deterministic 16-character vault identifier from the absolute path, preserves
other vaults, and atomically registers the managed vault. The vault enables the
safe built-in file, search, graph, Canvas, backlink, properties, daily-note,
template, bookmark, outline, Bases, and recovery workflows while keeping
community plugins, Publish, Obsidian Sync, Web viewer, slides, and audio
recording disabled. A scoped Syncthing `.stignore` excludes only Obsidian's
per-device `workspace*.json` layout files. The local `evergreen-notes` theme
and `managed-ux` snippet provide managed light and dark palettes, Noto
typography, accessible focus, reduced-motion behavior, print styling, and
consistent editor, navigation, graph, Canvas, code, table, tag, and callout UX.
Visual Studio Code receives
`window.titleBarStyle=native`, `chat.disableAIFeatures=true`, a built-in dark
theme with managed workbench, terminal, syntax, and semantic-token colors, and
privacy, workspace-trust, file, editor, and UX defaults. Its bundled Copilot
extensions therefore stay disabled and do not provision `~/.copilot`. Filen
does not expose a persistent native-frame preference, so its decoration
contract is enforced by the managed
Chromium feature flags and Labwc's server-decoration rule. Those settings
disable Chromium's decoration fallback, but Filen's vendor UI hardcodes its own
window controls; removing them would require modifying the Filen application
rather than a supported configuration file. All managed
Chromium/Electron launches
disable the `WaylandWindowDecorations` client-side fallback, while the Labwc session exports
`QT_WAYLAND_DISABLE_WINDOWDECORATION=1` and `GTK_CSD=0` for compositor-owned
Qt and GTK decorations.

When `addon/software` is selected on `amd64`, Ledger Wallet (Ledger Live) is
downloaded from `https://download.live.ledger.com/latest/linux` and resolved
against Ledger's official stable Linux metadata. The installer verifies the
pinned Ledger public key, Ledger's signature over the release SHA-512 manifest,
the metadata digest and size, the x86-64 AppImage framing, and the extracted desktop version before publishing a
root-owned `/opt/ledger-live` AppDir. Only the verified Chromium sandbox is
installed setuid-root; the managed launcher keeps the sandbox enabled, uses
native Wayland and KWallet, and does not expose a non-functional PurePrivacy
action. `53-ledger-wallet.rules` covers Ledger Stax and other current Ledger
devices with `plugdev` plus active-seat `uaccess` at `0660`, including
firmware-update re-enumeration, without making hidraw world-writable.
