# Forky maintenance and supplied log review - 2026-10-04

This revision changes the served installer source and its payload for subsequent
installations. The requested target is Forky with systemd 261.2. All files under
`todo/`, including `todo/managed/`, were read (49 files, 20,367 lines). The source review
covered all 95 target AppArmor files and the firstboot profile, the ten desktop
profiles, package hooks, their installer staging, and the managed notification
paths. No installed host was upgraded, mounted, enrolled or reconfigured here.
The private Xwayland launchers and configuration for Zoom/Discord were preserved.
No application, driver or kernel was compiled from source.

## Implemented contracts

1. `52unattended-upgrades` now covers every active archive site declared in the
   installer classes, including `mirrors.glesys.net`. Explicit package families
   exclude the base system, interpreters, authentication, service/device manager,
   boot/kernel/module/firmware, storage, network, desktop session, graphics and
   audio stacks from automatic updates. NVIDIA/CUDA SDK, runtime and management
   packages are covered even when their names omit the vendor tokens. All 547
   distinct binary package names sampled from the official NVIDIA Debian 13
   archive matched the blacklist. Kernel and dependency removals are disabled;
   maintenance of these families, including their security updates, is manual.
   The blacklist contains the exact anchored expression used by the MOK hook,
   and both consumers use Python `re.match`. Regression checks require identical
   expressions, including after native APT parsing, and cover all branches with
   package suffix/boundary examples. This closes the `dkms-*`, `kmod-*`,
   `module-assistant-*` and numbered TensorRT gaps. Colon boundaries also cover
   foreign-architecture names such as `kmod:i386` and `zfs-dkms:arm64` returned
   by Python APT; the hook protocol itself supplies unqualified names.
   Automatic interrupted-dpkg repair is disabled because its
   `dpkg --configure -a` runs before blacklist filtering; recovery of
   interrupted maintenance remains an explicit action.

2. The encrypted-MOK installer branch stages `apt-mok-prehook` and two APT
   fragments. APT supplies action protocol version 2 on FD 3; the helper also
   accepts version 3. It validates bounded metadata and returns before touching
   signing state for unrelated packages. Relevant boot/module/GPU operations
   verify the mounted key/certificates, then use the existing `luks-mok-open`
   when needed. The prompt retains its controlling terminal, with bounded
   subprocess-group cleanup. An administrator's existing open is preserved.
   A root-owned 0600 marker records only an open owned by this hook. The first
   APT post hook closes that open; close failure retains retry intent and emits
   a critical notification. A later relevant transaction recovers interrupted
   hook-owned state. APT has no `Post-Install-Pkgs` interface, so cleanup uses
   `DPkg::Post-Invoke`. Noninteractive relevant APT operations require an
   administrator to open signing storage beforehand and close it afterwards.
   APT's registered pre-install hook is still called for unrelated transactions.
   The blacklist prevents unattended-upgrades from selecting MOK-gated packages;
   unrelated transactions return after metadata validation, before signing-state
   checks or an unlock prompt. Blacklisting does not suppress the hook process.

3. Desktop reconciliation now collects affected desktop paths from installed
   package lists and incoming archive metadata. Optional missing `md5sums`
   falls back to bounded archive contents inspection. Archive filenames with
   spaces work; alternate dpkg roots and malformed operations fail before
   state publication. Final APT reconciliation handles only those paths.
   Unrelated packages do not inspect, rewrite or announce a preserved Foot
   override. Direct dpkg uses directory-change gating, and the system path
   watcher handles policy/helper changes. Existing ownership-journal recovery
   and administrator overrides are preserved. Safe root-owned vendor hardlinks
   are accepted without weakening ancestry, ownership or write-mode checks.

4. The identical shared system/skel WirePlumber policy gives internal Speaker
   nodes precedence over Headphones and disables saved profile restoration in
   the global settings scope. Existing route/default-target restoration policy
   remains consistent. The common login helper selects explicit available
   internal UCM Speaker profiles/sinks or ACP speaker ports. It accepts the two
   JSON port representations, rejects virtual/USB/Bluetooth/HDMI candidates,
   and keeps login usable on profiles without internal speakers. Microphones
   are still muted even if playback selection fails. All ten desktop profiles
   stage the common policy/helper; P15s retains its specific UCM preference.

5. All AppArmor policy sources and named transitions were reviewed. Scoped
   changes cover reciprocal process-statistic reads, inherited terminals,
   Codex child termination, failed-service probes, audio selection, bounded
   package inspection/temporary files, and the existing signing-helper tools.
   The new MOK and ThinkPad helpers have separate profiles. Process observers
   received read permissions, without new trace/attach grants. All canonical
   target policies and local fragments parse in an isolated tree. Chromium,
   Edge and Mullvad Browser outer profiles are vendor package inputs; their
   local includes and child profiles were parsed in enclosing fixtures, and
   their installer normalization paths were checked. This is syntax/transition
   review, not a live AppArmor enforcement acceptance test.

6. The existing Mako mailbox, acknowledgement, deduplication and service ordering
   were inspected. Health notifications now include failed user/system services
   and sockets with bounded unit identities and concrete diagnostic commands.
   Failed probes do not announce recovery. MOK open/close/failed-close events use
   the existing root-to-desktop notification queue. Unattended-upgrade completion
   describes the broader manual-maintenance exclusions. Existing storage/security
   signals already cover NVMe errors and remain wired into desktop notifications.

7. `81-labwc-thinkpad-backlight.rules` initializes `tpacpi::kbd_backlight` to 2,
   supplies video-group write access to display brightness, and starts the fixed
   ThinkPad hotkey service when the driver appears. The helper ORs only supported
   `0x00008000`/`0x00010000` bits into the current mask and verifies the result.
   Other mask bits are retained. The shared account is already in `video`.
   The display brightness command keeps a minimum value of 1.

8. Codex preserves validated toolchain ordering and appends all six standard
   Debian binary directories, including sbin. Read-only APT/dpkg metadata access
   is complete, and `gnupg` is explicitly selected alongside the existing Perl
   and ShellCheck packages. The real dpkg database remains inherited from the
   read-only root. A private account-owned 0700 directory per launch is bound at
   `/run/systemd` for offline manager analysis. The readiness helper accepts a
   direct socket or the exact canonical-path SHA-256 alias used by current Codex,
   validates the 0700 directory/private socket/UID, checks peer credentials and
   detects endpoint replacement. The proxy shares only that per-UID temporary
   socket directory into its private `/tmp`.

The supplied NVMe endpoint is already covered by `74-nvme-link-idle.rules`, staged
by both storage families. That existing workaround disables controller APST via
PM QoS, runtime D3 and kernel-exposed link idle states for the reported device.
It does not mask AER or issue raw PCI configuration writes. Policy, staging and
native udev syntax checks passed; physical-link fault resolution needs observation
on the installed controller.

## Validation evidence

Commands ran from the repository root. Fixture imports use
`PYTHONPATH="$PWD/d-i/forky/tests"`; no credentials are loaded by these tests.

| Check | Observed result |
|---|---|
| `python3 -B d-i/forky/tests/test_maintenance_20261004.py` | 33 passed. Metadata, MOK lifecycle, desktop scope, speaker selection, notification state, Codex alias/PATH/private manager state, archive inventory and native APT parsing. Exact MOK/blacklist parity, 257 matching package examples, 54 architecture-qualified variants and 17 negative/control names are checked. Root identity and hardware/service actions are mocked; timeout cleanup uses an actual subprocess; the archive fixture contains text only. |
| `python3 -B -m unittest test_codex_power_20260926.WrapperRegressionTests` | 10 passed; mount plans and lifecycle supervision use spies. |
| `python3 -B d-i/forky/tests/test_p15s_audio_20261004.py` | 4 passed; native WirePlumber/SPA parsing plus staging fixtures. |
| `python3 -B d-i/forky/tests/test_apparmor_incidents_20261004.py` | 3 passed; supplied denial contract fixtures. |
| `python3 -B d-i/forky/tests/test_notifications_followup_20260920.py` | 4 passed, 1 skipped; native GTK/Xvfb graphical fixture unavailable. |
| `python3 -B d-i/forky/tests/test_nvme_link_idle_20260927.py` | 4 passed, 15 skipped; kernel-behavior fixtures require UID 0. |
| `python3 -B tools/check_shells.py` | 349 shell files; 709 parser/dependency checks passed using native dash, BusyBox ash and bash. |
| `perl -I d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/runtime -I d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/whisper -c d-i/forky/hooks/target/usr/local/libexec/labwc-mute-default-microphone` | Syntax OK with the actual Perl/Moo dependencies. |
| `udevadm verify d-i/forky/hooks/target/etc/udev/rules.d/81-labwc-thinkpad-backlight.rules d-i/forky/hooks/target/etc/udev/rules.d/74-nvme-link-idle.rules` | Both rules files passed. |
| Isolated AppArmor compilation with `apparmor_parser -Q -K -b FIXTURE -I FIXTURE PROFILE` | 96 source files; 62 policy/enclosing-fragment compilations passed. Includes use a private copy of native parser support and rendered canonical templates. No policy was loaded into the kernel or written to host caches. Parser version 4.1.8. |
| `python3 -B tools/build.py` | Built 1,701 payload files; no browser artifact content changes. |
| `python3 -B tools/build.py --check` | Snapshot, pins and preseed are current. |
| Archive/manifest inspection | All seven new target assets and the unattended-upgrade configuration are regular archive members and have equal source/archive/manifest digests. The archived MOK and blacklist expressions are identical. |
| `git diff --check` | Passed. |

The focused ShellCheck command (`shellcheck -s sh -S warning` on `grub.sh`,
`target-assets.sh`, the signing helper, health notifier and brightness wrapper)
reported only existing SC2034 for `TARGET_BOOT_TOOL_STATE_LOADED` in `grub.sh`.
That assignment is present in the unchanged baseline. No suppression or unrelated
cleanup was added.

The final generated products are `payload.tar.gz`, `payload.manifest` and
`preseed.cfg`; build and freshness checks passed after the final source changes.

## Acceptance limits and remaining log findings

Native `systemd-analyze verify` could not initialize its test manager in this
execution environment. The system fixture lacked a usable runtime directory;
the private user fixture hit `SO_PASSRIGHTS`/`SO_PASSCRED` permission failures.
These occurred again after authorized execution outside the sandbox. Socket
readiness fixtures requiring real AF_UNIX binds were blocked similarly. The
available verifier is systemd 262, not the requested target's 261.2. Unit
directives/staging were inspected; target boot, unit activation and real Codex
socket readiness remain deployment acceptance work.

The older desktop override suite skipped all 30 root-only cases. The broader
Codex/power suite encountered three socket-permission errors and two unchanged
power-worker fixture errors; its successful focused wrapper cases are listed
separately above. The legacy Secure Boot credential suite encountered root-owned
fixture ancestry failures under this unprivileged runner. The older policy-review
suite also hit an obsolete power fixture and a host/template copy collision.
These results are not counted as passes or reasons to weaken production controls.
No full-suite green result is claimed.

The supplied captures also contain account/configuration issues whose values the
installer cannot safely invent: unavailable external MCP binaries or account
authentication, unknown keys in an externally cloned Codex home, Mullvad login
failure, and missing Obsidian Git identity after SSH authentication recovered.
The existing Codex binary mount plan does not mask dpkg's database; this execution
environment itself has tools without matching package records, so its inventory
is not proof of the installed host's dpkg contents. Confirm those records within
the deployed wrapper after rollout.

Libinput dispatch delay/touch jumps and DRM connector `EBUSY` need target hardware
measurements. The current single-wallpaper-owner and disabled HDMI/DP policies
already address the known source-level conflicts. Bitwarden's logged EXDEV rename
uses its copy fallback, and Tailscale's initial warm-up transitions are expected;
neither justified an unrelated code change.

No live MOK unlock/close, passphrase prompt, Secure Boot enrollment, unattended
upgrade, audio-device selection, LED/sysfs write, enforcing AppArmor application
launch, physical NVMe test or full unattended installation was performed here.
Abrupt SIGKILL/power loss cannot guarantee immediate MOK cleanup; retained intent
supports recovery while `/run` persists, and reboot removes the temporary mount.
All newly staged paths must be rolled out before these source changes affect an
existing host.

Primary interfaces checked: [APT hook protocol](https://manpages.debian.org/testing/apt/apt.conf.5.en.html),
[APT protocol implementation](https://github.com/Debian/apt/blob/main/apt-pkg/deb/dpkgpm.cc),
[unattended-upgrades matching and interrupted-dpkg recovery](https://github.com/mvo5/unattended-upgrades/blob/master/unattended-upgrade),
[WirePlumber settings](https://pipewire.pages.freedesktop.org/wireplumber/daemon/configuration/settings.html),
[NVIDIA Debian archive](https://developer.download.nvidia.com/compute/cuda/repos/debian13/x86_64/),
[Codex 0.159.1 socket transport](https://github.com/openai/codex/blob/rust-v0.159.1/codex-rs/app-server-transport/src/transport/unix_socket.rs),
and [ThinkPad ACPI documentation](https://www.kernel.org/doc/html/latest/admin-guide/laptops/thinkpad-acpi.html).
