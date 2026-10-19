# Journal and Tailscale startup review, 2026-10-19

> The log diagnosis below is retained. Current installer-product fingerprints
> and the later instruction to stop testing are recorded in
> [the final MOK/GPG source report](desktop-mok-gpg-20261019.md).

## Scope and evidence

Reviewed both supplied files as data, including the complete 1,571-line journal.
The one-line `todo/tailscale-netkit` contains two concatenated messages already
present in the journal. Neither file is changed or copied into the payload.

| Input | Bytes | SHA-256 |
| --- | ---: | --- |
| `todo/journalctl` | 193,926 | `d2fc12905f514c56065882937cfd04d1fe203772759c9d163e0d03c42f23520a` |
| `todo/tailscale-netkit` | 346 | `ff14bb7690414fff1b84d6b04d42169f97b7b5f61e2e03a7b2c527cb50e49768` |

The captured daemon identifies itself as Tailscale **1.104.1**. The installation
target remains Forky with systemd **262**. This change preserves the previous
MOK/GRUB edits and the existing Xwayland configuration, as explicitly requested.

## Findings and disposition

Line numbers refer to `todo/journalctl`, not to a new live-host query.

| Lines | Diagnostic | Cause and disposition |
| --- | --- | --- |
| 278 | `System is tainted: unmerged-bin` | systemd reports separate `/usr/bin` and `/usr/sbin` directories. This is distinct from an unmerged `/usr`. Debian documents this notice and advises against a manual directory merge. No filesystem migration or warning suppression is introduced. |
| 346–351 | BlueZ identity file absent | First-boot identity initialization: BlueZ immediately reports generating the IRK successfully. No fabricated identity file, privacy change or service retry is needed. |
| 570, 582, 600–601 | XFS healer: only logging errors | Describes the selected `autofsck` reporting mode. These lines do not report detected corruption or a failed repair. Preserve that non-mutating policy. |
| 879–880 | Tailscale log configuration absent/nil | Native first-use log configuration initialization. Upstream creates a new configuration after validation fails; no subsequent configuration-save failure appears here. Retain native generation rather than fabricating vendor state. |
| 883–884 | DNS cleanup/inotify cancellation | Startup cleanup context is canceled before normal daemon setup. Later DNS and engine setup proceed. No DNS policy change is supported by this excerpt. |
| 885–886 | `iptables`/`ip6tables` not found | Native startup cleanup probes legacy tools independently of nftables selection. The new private namespace has no inherited legacy rule set. Add exact absence-only diagnostic filters; retain execution denials and every other firewall error. No legacy package, compatibility backend or AppArmor grant is added. |
| 887 | Configured TUN absent during cleanup | Native cleanup runs before the daemon creates its private TUN. The existing exact filter failed because it omitted the Go timestamp in `MESSAGE`. Correct that filter; do not precreate a dummy interface or change namespace ownership. |
| 922, 953 | Profile directory not found | Fresh registration has not created a profile yet. The subsequent registration succeeds. Preserve native state ownership. |
| 924, 956 | Stopped/warming-up health messages | Bootstrap starts the initially inactive client. Both health conditions clear, and the client reaches Running. These health diagnostics remain visible. |
| 938 | `netfilter=off` warning | Intentional repository-owned nftables policy; the CLI uses generic wording mentioning iptables. Preserve the managed nftables/NAT/source-guard design and native warning. |
| 1020 | Lite-map HTTP 409, superseded update | A control-server response, not a link or firewall failure. The native updater retries with backoff. A valid network map, Running state and successful bootstrap follow in the same second. Keep this diagnostic visible; no restart, reauthentication loop or additional retry is added. The excerpt does not identify which request superseded it. |
| 1226–1228 | Global Xwayland probe fails | The global binary is intentionally absent; Labwc continues and the session target is reached. User explicitly chose to preserve the current configuration. Private Zoom/Discord eligibility and implementation are unchanged. |
| 1307–1308 | LayerShellQt API deprecation | Crystal Dock starts successfully; the warning names an upstream API. The repository installs Debian's `crystal-dock` package, not a local implementation of that API. A vendor package update is the appropriate owner of an API migration. No source compilation, generic Qt log suppression or speculative dock rewrite is introduced. |
| 1312–1313 | Netavark idle timeout | Socket-activated DHCP proxy exits after 30 seconds without work and its unit deactivates successfully. Preserve its activation and lifetime behavior. |

There is no failed Tailscale startup in this excerpt. Registration is authorized
at line 1018; a netmap arrives at 1024; the client becomes Running at 1052;
warm-up clears at 1053; bootstrap succeeds at 1056; and the netkit supervisor
reports two mirrored addresses and eight routes at 1060. This establishes the
captured startup's recovery, not uninterrupted connectivity after the excerpt.

### Primary-source checks

- Tailscale 1.104.1 calls cleanup unconditionally before server startup in
  [`cmd/tailscaled/tailscaled.go`](https://github.com/tailscale/tailscale/blob/v1.104.1/cmd/tailscaled/tailscaled.go#L528-L534).
  The Linux router's
  [cleanup implementation](https://github.com/tailscale/tailscale/blob/v1.104.1/wgengine/router/osrouter/router_linux.go#L1937-L1968)
  probes both firewall backends and treats address cleanup as best effort.
- The
  [control updater](https://github.com/tailscale/tailscale/blob/v1.104.1/control/controlclient/auto.go#L59-L107)
  logs failed updates and backs off before retrying. The server status/body
  originate in the
  [HTTP map response handler](https://github.com/tailscale/tailscale/blob/v1.104.1/control/controlclient/direct.go#L1207-L1216).
- Native
  [log configuration initialization](https://github.com/tailscale/tailscale/blob/v1.104.1/logpolicy/logpolicy.go#L624-L634)
  creates and saves a new configuration after a missing/invalid one.
- systemd 262 defines
  [unit message filtering](https://www.freedesktop.org/software/systemd/man/262/systemd.exec.html#LogFilterPatterns=)
  against the complete `MESSAGE` field. The
  [unit parser](https://github.com/systemd/systemd/blob/v262/src/core/load-fragment.c#L6689-L6736)
  consumes one complete expression per assignment. Its
  [taint check](https://github.com/systemd/systemd/blob/v262/src/core/taint.c#L39-L46)
  distinguishes the two directory-layout notices.
- Debian's
  [documented unmerged-bin disposition](https://www.debian.org/releases/trixie/release-notes/issues.en.html#systemd-message-system-is-tainted-unmerged-bin)
  warns that manually merging these directories is unsupported and breaks
  upgrades. That guidance describes this diagnostic; it is not a claim that a
  Trixie package version is installed on the Forky target.

## Source contract

Changed runtime input:

- `hooks/target/etc/systemd/system/tailscaled.service.d/override.conf.tmpl`:
  four anchored deny patterns, accepting either the exact Go date/time prefix
  or no prefix. The configured interface remains escaped through the existing
  `TAILSCALE_INTERFACE_REGEX` renderer. No allow-list or broad severity filter
  is introduced. The existing exact closed-extension-queue shutdown filter is
  updated consistently; that shutdown message is not present in this excerpt.

Traced through `scripts/late/tailscale.sh`, the installed unit, the root
`tailscale-netkit` constructor/daemon delegate, the bootstrap helper/service,
managed nftables policy and `usr.sbin.tailscaled` AppArmor profile. Rendering
still publishes the unit drop-in with mode 0644 and rejects unresolved tokens.
The constructor still forces `TS_DEBUG_FIREWALL_MODE=nftables`; AppArmor still
denies legacy firewall executables. No network, routing, authentication,
bootstrap retry, namespace, cgroup or authorization behavior is changed.

`tests/test_native_contracts_20260923.py` gains synthetic positive and negative
fixtures for timestamped/unprefixed records, literal dots in configured
interfaces, other interfaces, altered messages, real firewall/permission
errors, health warnings, authentication errors, HTTP 409 and AppArmor denials.
The guarded Python suite is not executed on the development host.

## Validation

Static source/AST/diff inspection and pure serialization are recorded below.
A narrowly scoped real-journal check uses a fresh snapshot of the retained
disposable Forky image, with no network, host shares, forwarded sockets or host
devices. It exercises only synthetic diagnostics and two fixture services;
it does not start Tailscale, authenticate a tailnet, run the full guarded suite,
boot a desktop or change any host service or policy.

### Native result

The reviewed fixture is retained at
`/tmp/preseed-tail-log-20261019-pdlfo22e/`. `qemu-argv.json` records the exact
argument array: QEMU TCG, `-nodefaults`, `-no-user-config`, `-nic none`, no
monitor or forwarded socket, a snapshot of the owned regular-file guest root,
and a read-only fixture ISO. The minimal host-side environment contains only
the fixture's HOME/TMPDIR, a fixed PATH and locale. The VM owns its kernel,
devices, procfs, managers, package tree and journal. The initrd and root boot
units were reviewed before execution. The historical guest root, kernel and
initrd hashes were recomputed and matched the retained evidence.

Guest packages: **systemd 262-1**, **Python 3.14.7-3**. Guest kernel:
**7.2.11+deb14-amd64**. No package installation or source compilation ran.

The guest executed
`/usr/bin/python3 -I -B /mnt/preseed-fixture/native-filter.py`, copying the four
actual template directives into two guest-only oneshot services with synthetic
stdout. Only the interface token was substituted, using the renderer's literal
dot representation. Real guest journald supplied the observed records.

| Interface | Exact no-op records discarded | Other records retained | Result |
| --- | ---: | ---: | --- |
| `tailscale0` | 8 | 39 | success |
| `ts.mesh0` | 8 | 41 | success |
| **Total** | **16** | **80** | **success** |

This includes timestamped and unprefixed HTTP 409, authentication failures,
health warnings, legacy-tool permission failures, nftables errors, synthetic
AppArmor-denial text, foreign interfaces, nonliteral dot substitutions,
unexpected prefixes/suffixes and unsupported timestamp precision. The native
fixture verifies journal retention of denial text; it does not load AppArmor
or exercise an actual policy denial.

The console reports `TAIL_FILTER_FINAL=success hidden=16 visible=80` and
`TAIL_FILTER_GUEST_STATUS=0`. QEMU exited 0 after guest poweroff and was reaped.
No fixture process remains running. The guarded unittest suite remains
unexecuted; the native result is for this independent, bounded journal fixture.

Retained evidence SHA-256:

| File in fixture directory | SHA-256 |
| --- | --- |
| `image-inputs.json` | `7da10c07ddb9eceac94c5568adad84eefbd510dfd2243a6b6ac39cbb9e55b220` |
| `fixture-inputs.json` | `c781a47894ab3e746ec655dcdf8ce814cd0fb67aa91cfcbdecfcd8daa99fa734` |
| `qemu-argv.json` | `0391ed099b42fbdd865c417df4c0a8474217258678dfb2b1aabf459cf0d355a3` |
| `qemu-console.log` | `0ec16bf02898f19140920d58fc6fe97d9fea6f9977f3a08e6793f303cb69019d` |

### Static and serialization result

Base revision: `f5d49636569baf5ae22cf6683ff449bfc28198a9`. The inherited MOK
working tree was preserved. The two changed source inputs have these hashes:

| Source | SHA-256 |
| --- | --- |
| Tailscaled drop-in template | `6812875ae83027de1cc6e5e7a454c2fef207535b447fad6b24242eb1cf68ed7e` |
| `test_native_contracts_20260923.py` | `b82735b11a184cb174db21724bd5a20b61439f0c8eca3959238d7e7b2025c3ad` |

The affected-source fingerprint is
`8b11d2a265c70f02d959214a85e8b48d0dc26a00c1e8a5ac26238324251120f0`,
computed over sorted `sha256  repository-relative-path\n` records for those
two inputs. The payload manifest identifies every serialized runtime input.
The report itself is not a payload input.

- Standard-library `ast.parse` accepted the changed Python fixture as data;
  no test discovery, fixture import or repository code execution occurred on
  the host for that inspection.
- Reviewed `Makefile`, `tools/build.py` and `tools/publication.py` before using
  `/usr/bin/make --no-print-directory build 'PYTHON=/usr/bin/python3 -I'` with
  only `PATH=/usr/bin:/bin` and `LC_ALL=C` in the child environment.
- Pure generation succeeded with **1,818 members**. A before/after digest map
  confirmed **2,359 non-product tracked/untracked paths** were unchanged by
  generation. The three generated products are the only build outputs.
- Bounded streaming archive inspection, without extraction or code execution,
  confirmed all **34,708,899 uncompressed bytes** match current source bytes
  and manifest hashes. Members are regular files with mode 0644, zero numeric
  owners and zero timestamps. Archive/manifest/source pins match the generated
  preseed include command.
- `git diff --check` is the final whitespace check. Source modes are preserved
  as 0644; no recursive ownership or permission operation is used.
- Both independent read-only sidecars failed during encrypted-context
  initialization. No independent findings or review approval are credited.

| Generated product | Bytes | SHA-256 |
| --- | ---: | --- |
| `d-i/forky/payload.tar.gz` | 26,565,189 | `f1ed7f5bbaf76fc43f537d0c9e8d24bdb953235b49c90393b7c79be0e3445cf9` |
| `d-i/forky/payload.manifest` | 224,057 | `ad5d25d053e0c9fdf1999d138e621598536a30d71a363c557b199e1320d833f5` |
| `d-i/forky/preseed.cfg` | 96,407 | `9d626d57c005da339e02065be1bc75e07db94e2bc860f1395aee720451e7c8fc` |

No live target is repaired or restarted by this task, and local generation is
not publication to the installation server. Existing journal records are not
removed. Full fresh-install/Tailscale connectivity and hotplug acceptance,
desktop/native-application/private Zoom/Discord regression checks and the
previous MOK firmware/GRUB gates remain outside this synthetic journal result.
