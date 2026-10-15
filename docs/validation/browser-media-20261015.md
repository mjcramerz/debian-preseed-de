# Browser media and supplied log review, 2026-10-15

## Scope and evidence

Target: Debian Forky, systemd 262. This change repairs the installer sources;
it does not deploy them to an existing desktop. The existing Codex project
identity and hardware tuning changes in the working tree are retained. No
source compilation or private Xwayland policy changes are included.

All five files under `todo/` were inventoried and scanned, including the hidden
older journal. Repeated AppArmor records were grouped by profile, operation,
path and requested permission; journal diagnostics were correlated with their
surrounding startup, network and shutdown records. Input evidence is retained.

| Input | Logical lines | Bytes | SHA-256 |
| --- | ---: | ---: | --- |
| `todo/.~` | 1617 | 212514 | `bb68928a2100b4c3378cca60b1e39403c06d380532374615d84ef7e542f8d900` |
| `todo/about-gpu-vivaldi.txt` | 751 | 34216 | `9c3e5c5b83ea0c964eb59694230dae91f4dbfa2153482a4c573de0877e334eb5` |
| `todo/apparmor` | 81 | 24237 | `d58aaf65d694780794f341cd771e2ce6787f032257178c4ee7069d2594d1b7d1` |
| `todo/error` | 4 | 901 | `ea5bec57e2f1da9ccf0f1b06ba910b34e1afceb029b761a5ca21265a9bab46a6` |
| `todo/journalctl` | 2171 | 364535 | `d9fde276608411a1b341877c72dd6de05ad23ae2ef32200699868cc7328fb37d` |

The GPU report's final line has no terminating newline. It includes both the
GPU sandbox warning and the later EGL context error.

## Implemented media contracts

### Vivaldi

The exact official `vivaldi-stable_8.2.4133.87-1_amd64.deb` was inspected as
archive data, without executing package contents or maintainer scripts. The
package index advertised SHA-256
`0e259d867109ceaa3d011df7fc99fa5cc9484e4c77db33a7055e5dd941cb242f`;
the downloaded archive matched it. This inspection used the public vendor
index and HTTPS; the installer continues to obtain the browser through its
existing authenticated APT source.

The package launcher advertises compatible codec versions in its literal
`FFMPEG_VERSIONS` assignment, checks `/var/opt/vivaldi/media-codecs-VERSION/`,
and exports the selected `libffmpeg.so` through its own preload mechanism.
Its postinst starts `/opt/vivaldi/update-ffmpeg` asynchronously. That helper
checks the downloaded library against a hash shipped in the browser package.
The repository disabled per-user downloading with `VIVALDI_FFMPEG_AUTO=0`,
but neither managed sandbox mounted `/var/opt/vivaldi`. This prevented the
launcher from seeing a compatible system codec even when one was installed.
Vivaldi documents the separate support files required for H.264/AAC in its
[Linux proprietary media guide](https://help.vivaldi.com/desktop/media/html5-proprietary-media-on-linux/).

The installer now waits for an existing root-owned `update-ffmpeg` process,
then runs the packaged updater synchronously. The wait and installation share
a minimal environment and a 180-second timeout plus a five-second kill deadline.
`pidwait` comes from the already selected `procps` package; it waits without
signalling the updater. Status 1 also covers a process that has already exited;
other command failures propagate. This ordering avoids overlapping the vendor's
background postinst downloader, whose cleanup removes `libffmpeg.so*` files,
including another invocation's partial download. The installer then checks
the compatible system codec inventory before completing desktop setup.
The launcher parses that inventory as data, checks ownership, file types,
writable modes, hard links and size bounds, and rejects incompatible/missing
files with a specific diagnostic. It does not source shell code or load the
codec into the Python supervisor. Each normal or privacy launch mounts the
system codec directory read-only through the shared proxy/mount builder.
The parent and Bubblewrap AppArmor domains have the corresponding bounded
read/mapping permissions. User-owned codec downloads remain disabled.

The codec version list follows the installed browser package; no particular
Chromium codec build, checksum or version is hardcoded into the wrapper.
Browser package upgrades retain the vendor's existing system codec updater.
If an upgrade's background download fails, a managed launch now reports the
missing compatible codec instead of silently running without it. An
administrator can repair that installation using the installed vendor helper
`/opt/vivaldi/update-ffmpeg --system`; this command was not run on the host.

### System codecs and Tor Browser

The desktop package selection now explicitly includes `libavcodec-extra` and
the GStreamer libav/base/good/bad/ugly plugin sets from the existing Debian
repositories. The extra-codec metapackage tracks the distribution ABI. It adds
the additional codecs supplied by Debian; ordinary FFmpeg already includes
H.264/AAC. GStreamer supports WebKit and desktop media consumers, while
Firefox and Vivaldi have their own decoder integration paths. See Debian's
[codec metapackage](https://packages.debian.org/forky/libavcodec-extra) and
[GStreamer libav package](https://packages.debian.org/forky/gstreamer1.0-libav).

The pinned Tor Browser remains 15.0.25. Its Firefox ESR branch supports
`libavcodec.so.62`; an earlier assertion that all ESR 140 builds necessarily
require ABI 61 is incorrect. Mozilla's
[ESR 140 FFmpeg linker](https://raw.githubusercontent.com/mozilla-firefox/firefox/FIREFOX_140_16_0esr_RELEASE/dom/media/platforms/ffmpeg/FFmpegRuntimeLinker.cpp)
includes ABI 62. The current distribution supplies FFmpeg 8.1.2.

Tor's required runtime file inventory now includes ABI 62 and its matching
utility/resampler libraries. The installer also loads the target's library
with dropped desktop-user privileges and checks decoder availability for
H.264, AAC, MP3, FLAC, Opus, VP8, VP9 and AV1, accepting the packaged decoder
name variants. That installer check is not an end-to-end playback test. Both
Tor mount namespaces already retain the immutable system `/usr` tree.

Both stacked Tor AppArmor profiles now allow the owning user's private
`pulse/` directory to be opened and cleaned up. Only the Pulse socket is
bound from the desktop; the directory itself is private. The browser uses
that bound socket explicitly through `PULSE_SERVER`. Raw ALSA devices remain
unavailable. Normal launches use an unambiguous render-node override when
exactly one render node is present; multiple GPUs retain native selection.

Normal Tor launches now receive a filtered UPower proxy permitting service
discovery, device enumeration, property reads and change notifications. It
permits no property writes or power-control methods. The transport's mount
namespace hides this socket; only the browser receives its bus address. Proxy
readiness and cleanup use the existing bounded lifecycle. ANOM retains its
existing absence of host power data, GPU devices and host audio sockets.

The second integration pass corrected the signal rule to the supported
`/org/freedesktop/UPower/*` subtree syntax. `xdg-dbus-proxy` treats a trailing
`/UPower*` as a literal path, so the former pattern could not deliver property
change notifications. Its
[filter implementation](https://raw.githubusercontent.com/flatpak/xdg-dbus-proxy/main/flatpak-proxy.c)
matches both the subtree root and its descendants with the `/*` form. Both
stacked Tor profiles also include AppArmor's
[strict system-bus setup rules](https://gitlab.com/apparmor/apparmor/-/raw/master/profiles/apparmor.d/abstractions/dbus-strict)
for the handshake, match registration and name discovery, plus the bus's
`NameOwnerChanged` signal. The proxy still filters access to other services.

Tor browser IP sockets remain denied by its child profile and separate network
namespace. Its connection to bundled Tor still uses local SOCKS/control Unix
sockets; the transport retains the dedicated veth and no host DNS.

## Graphics and ANGLE

The supplied Intel Tigerlake/Mesa report already has hardware compositing,
rasterization, WebGL, WebGPU and H.264/VP8/VP9/HEVC/AV1 decoding. It reports zero
GPU process crashes. Video encode is software-only; that does not prevent
video playback.

The Chromium-family accelerated profiles now use `AcceleratedVideoDecoder`,
`AcceleratedVideoDecodeLinuxGL` and, where encode was already requested,
`AcceleratedVideoEncoder`. Obsolete decoder feature names were removed from
these profiles. Duplicate `--use-webgpu-adapter=opengles` arguments were
removed. The matching Chromium source defines these current features in
[media_switches.cc](https://raw.githubusercontent.com/chromium/chromium/ef1ce85f6dbc0471fbf7154a539bdbf53c0d73c7/media/base/media_switches.cc).

The later October 15 managed logs show ANGLE failing to open native
`libEGL.so.1` (`Permission denied`), followed by three GPU process
initialization failures. The captured launch forces
`--gpu-sandbox-start-early`, consistent with this library-access failure.
That override has been removed from every Vivaldi mode. Chromium's normal
Linux order loads GL before entering its GPU sandbox, as shown in
[gpu_init.cc](https://raw.githubusercontent.com/chromium/chromium/ef1ce85f6dbc0471fbf7154a539bdbf53c0d73c7/gpu/ipc/service/gpu_init.cc).
The GPU sandbox remains enabled. Runtime acceptance on the supplied hardware
is still required; no browser was launched on the development host.

ANGLE remains the OpenGL backend, Dawn uses OpenGLES, and the existing Vulkan
exclusions remain. Shader caching and driver-selected workarounds are retained.
Vivaldi still respects the GPU blocklist and driver workarounds. The long
ANGLE feature dump includes both capabilities and bug workarounds; enabling
every entry would force incompatible behavior and debugging/test paths.

The EGL error means that one context request used a version unsupported by
that display. A context probe followed by a supported fallback is a possible
explanation, not a proven cause of the site's player failure. The report
shows successful GL/WebGPU initialization. No request-version override,
error suppression or safety-workaround removal is applied to hide this log.

## Disposition of the supplied diagnostics

| Diagnostic | Evidence and disposition |
| --- | --- |
| Hardware tuning `ptrace read`, peer `desktop-terminal` | Exact grant already present in the pending hardware-tuning repair. No trace/attach grant added by this media change. |
| Tor `pulse/` open/rmdir, both stacked profiles | All 80 records covered by the owning-user directory `rw` rule in their shared runtime abstraction. |
| Tor missing UPower bus and `glib warning` source annotation | Same underlying warning, not two independent faults. Normal launches now have the filtered read-only service path. ANOM intentionally retains the power-data restriction. The `/var/tmp/build/...` string is a compiled source location. |
| Tor `glxtest: Cannot find DRM device` | Primary card nodes are hidden. Upstream glxtest tries the EGL primary device name before its render-node fallback. Normal launches now provide the unique render node to DMABuf when available. The probe warning itself can remain; no primary device access was granted to remove it. |
| Vivaldi GPU sandbox thread warning, `Sandboxed: false` | Early native GPU sandbox startup requested. Verify `Sandboxed: true` in a new GPU report on the target hardware. No sandbox-disable flag was introduced. |
| Vivaldi `eglCreateContext` version error | Context request failed; no supplied crash or media decoder failure connects it to the player error. Driver-specific live verification is still needed. |
| Vivaldi missing `jplgfhpmjnbigmhklmmbgecoobifkmpa` | Public extension ID, not a UUID. The only active native policy entry is `installation_mode: removed`; wrappers do not inject it. Existing native UI/profile references can outlive extension removal. No user profile or vendor UI was rewritten. |
| Vivaldi NoScript/uBlock image `web_accessible_resources` rejections | Chromium extension manifest enforcement, unrelated to AppArmor. Relaxing AppArmor cannot permit a resource omitted from an extension manifest. Requires an extension/Vivaldi fix if the UI is broken. |
| Extension EventAck, shutdown exceptions and Mojo WidgetHost rejection | Native browser/extension IPC diagnostics. The recorded Vivaldi shutdown completes with status 0. A repeatable UI failure and media-internals record are needed to attribute remaining runtime faults. |
| Missing `eth0` ifindex/device during ifdown | Same timestamp as removal of `eth0` and default-route change to working Wi-Fi; ifup@eth0 stops successfully. Do not fabricate an interface or rewrite sysfs. |
| Tailscale closed connection/DERP reconnect at Ethernet removal | Correlated link loss and subsequent rebind, not codec permission failure. Subsequent veth rebinds report successful DERP pings. |
| Older Tailscale `NeedsMachineAuth` timeout | The older journal explicitly says device approval is pending. Approval belongs in the Tailscale admin service; retry/bootstrap state is retained. Do not bypass approval or reuse credentials. |
| CrowdSec console enrollment pending approval | Bootstrap reports pass while waiting for the external console approval. This is not a failed local parser/bouncer startup. No enrollment approval was attempted. |
| secondboot has multiple trigger sources for exit-status propagation | Its three OnSuccess senders can complete together. Cleanup uses persisted completion markers rather than the ambiguous MONITOR environment and finishes successfully in both journals, retaining pending enrollment work. No cleanup failure is established. |
| systemd reports `unmerged-bin` taint | Installed filesystem-layout diagnostic. The logs do not establish the exact `/bin` layout or ownership of its creation. No host filesystem migration or Xwayland change was attempted; this remains an installed-layout investigation. |
| Tailscale `netfilter=off` warning | The repository owns firewall/routing policy through nftables. Allowing Tailscale to replace it would change the accepted network contract. |
| Tor remote resolve/connect attempts give up | Tor reaches bootstrap 100%, then some remote connections fail. Site/CDN/exit reachability still requires live diagnosis. Adding codecs cannot repair a refused media request. |
| qBittorrent storage unavailable | Launch precedes the removable volume's mount. Storage appears later in the journal. Its existing refusal prevents writes to the wrong filesystem; keep that protection. |
| Waybar GTK accelerator assertions | All five current menu templates already define `GtkAccelGroup`, and all eleven GtkMenu objects reference it. Compare installed/generated menu data and Waybar/GTK versions in the disposable environment before making another configuration change. Not established resolved by this media repair. |
| Older Waypaper has no monitor enumerators | The same log records the supported All-displays fallback and successful swaybg rendering/persistent save. No evidence of wallpaper failure. |
| Bluetooth missing identity key | Controller-specific BlueZ state, with no codec link. The logs do not establish a failed pairing or justify manufacturing/replacing identity keys. |
| Global Xwayland missing and duplicate X11 tmpfiles rule | Existing private-Xwayland policy is explicitly outside this change. Zoom/Discord policy remains intact. |
| XFS `Only logging errors per autofsck directive` | Informational filesystem healer mode. No filesystem corruption is established by that sentence. |
| netavark inactivity timeout, terminal Hangup | Normal helper/terminal lifecycle records in these logs; no codec repair applies. |
| Initial Tailscale missing log/profile state, temporary DNS cleanup, later warming-up OK | First-start/transient records with subsequent successful startup. Do not create stale state or change resolver policy from these alone. |
| Optional profile/service skips, missing MTP/ModemManager backend, module already built in, power feature disabled by policy | Expected capability/condition checks or explicit configuration. They are not missing browser codecs. |

## Verification and remaining acceptance

No tests, native policy parser, installed host helper, package manager, browser,
system/user manager or host repair command was executed. No disposable test
environment was supplied. `AGENTS.override.md` requires stopping at static
inspection in that case; an ordinary namespace on this host is insufficient.

Performed static checks:

- AST parsing of the seven changed/new Python production and regression files,
  plus the two embedded installer Python snippets, without imports/execution.
- Source-to-caller review of both Vivaldi sandbox paths, codec setup, Tor's
  nested roots, proxy startup/cleanup and both stacked AppArmor profiles.
- XML data inspection of all five current Waybar menu templates: eleven menus
  reference their defined accelerator groups.
- `git diff --check`.

The permitted pure `make build` completed with 1,784 payload files. Static
archive inspection compared every member byte-for-byte with its source and
manifest digest, then checked all three embedded preseed hash pins. Results:

| Generated artifact | SHA-256 |
| --- | --- |
| `d-i/forky/payload.tar.gz` | `e4d7bf546b971c2280aeea79c39d4bcb54b2fbcf8baa425940656af825636954` |
| `d-i/forky/payload.manifest` | `5c180c8fb5ccf36d0d24cba07e28760aac8a75d685bacba72d3bb3ada1749b3a` |

The source bootstrap pin is
`6b3a40bb85942ed8f4b780852743140132414898b578af7c7597bb7c3872b246`.
Generation and byte/hash comparison are not test-suite or live-browser results.

Ten focused media regression methods were added, using synthetic codec files
and mocked launch operations. The second pass strengthened the UPower checks
to cover the supported subtree suffix and both profiles' system-bus setup
permissions. Existing network/Tor fixtures were updated for codec discovery
and the two bus lifecycles. These tests have **not been run**.
They must run through the prepared environment described in
[test-isolation.md](../test-isolation.md). Synthetic file fixtures do not prove
real codec ABI loading or playback. The installer decoder probe likewise has
not been run in a fresh target during this session.

Required live acceptance in that environment/target:

1. Fresh signed-package installation, Vivaldi setup with a postinst downloader
   still active, foreground codec setup and compatibility check; inspect the
   actual browser namespace to confirm the selected codec is visible read-only.
   Exercise the shared wait/install deadline and updater failure propagation.
2. Vivaldi's official H.264/AAC sample, WebM/VP9/Opus and AV1 playback with
   sound. Check `vivaldi://media-internals` for the actual player decoder and
   failure code. Repeat the reported sites and inspect failed media/CDN
   requests and extension blocking if the player still reports Loading error.
3. Vivaldi GPU report after early sandbox startup, including native GPU sandbox
   status, startup/fallback behavior and EGL logs on Intel and NVIDIA hardware.
   No performance improvement has been measured in this session.
4. Tor normal/Intel/NVIDIA playback and audio, filtered UPower operations and
   negative checks for other services/power writes/transport socket access;
   ANOM retains its intended hardware and bus restrictions.
5. Enforcing AppArmor acceptance for every supplied denial; regression coverage
   is not proof of a loaded kernel policy.

There is also an open, unconfirmed upstream report of streaming failures with
Firefox 140.16/Tor and FFmpeg 8.1.2 despite ABI 62 loading:
[Mozilla bug 2073258](https://bugzilla.mozilla.org/show_bug.cgi?id=2073258).
The supplied logs do not prove this host has that defect. No foreign-release
libraries, ABI aliases, Tor alpha release, sandbox disabling, global extension
disable or source build was introduced as an unverified workaround.

Browser playback remains bounded by the browser's supported formats, the site's
media delivery and DRM availability, extensions and Tor security level. The
repository fixes cannot guarantee every possible format, DRM service or site.
