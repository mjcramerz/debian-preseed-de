# CrowdSec enrollment and qBittorrent follow-up — 2026-10-07

## Supplied evidence

This follow-up uses the current `todo/` capture: 47 files, 1,195,269 bytes,
24 nonempty files and 23 empty files. All files were inspected. The earlier
desktop runtime report describes a different capture of these paths.
Credentials and private command output are not reproduced here.

| Nonempty path under `todo/` | Lines | Finding |
| --- | ---: | --- |
| `journalctl` | 1023 | Hub and CAPI requests rejected; bootstrap stopped the engine before Console enrollment. NFS and Tailscale subsequently report success. |
| `qbit` | 16 | Default, Intel and torrent-file launches all reject `/run/systemd/resolve`. |
| `managed/apps/apps.log` | 187 | Repeats the same resolver-directory failure. |
| `managed/models/whisper/whisper.log` | 1 | Informational model record. |
| `managed/security/apparmor/apparmor.log` | 434 | All AVC records contain `apparmor="STATUS"`; no application denial in this capture. |
| `managed/security/apparmor/modes.log` | 82 | Profile mode records. |
| `managed/security/audit/auditd.log` | 2769 | All 725 SYSCALL records have `success=yes`; remaining records describe policy, service, authentication and configuration activity. |
| `managed/security/auth/auth.log` | 43 | Session and authentication records. |
| `managed/security/crowdsec/crowdsec.log` | 76 | CrowdSec 1.8.1 loads LAPI, parsers and scenarios, reports CAPI disabled, then receives bootstrap's stop. |
| `managed/security/crowdsec/crowdsec_api.log` | 3 | Successful local API requests. |
| `managed/security/fail2ban/fail2ban.log` | 19 | Successful startup and SSH jail; first-run database creation. |
| `managed/security/nftables/nftables.log` | 24 | Accepted packets; no rejected request established by these records. |
| `managed/system/initramfs/01-init-top.log` | 49 | Normal phase records. |
| `managed/system/initramfs/02-init-premount.log` | 53 | Normal phase records. |
| `managed/system/initramfs/03-local-top.log` | 55 | Root-device setup records. |
| `managed/system/initramfs/04-local-block.log` | 5 | Root already available; local-block invocation was unnecessary. |
| `managed/system/initramfs/05-local-premount.log` | 25 | Normal phase records. |
| `managed/system/initramfs/06-local-bottom.log` | 33 | Normal phase records. |
| `managed/system/initramfs/07-init-bottom.log` | 85 | Final root mounted; required paths present. |
| `managed/system/kernel.log` | 949 | Includes an unclean EFI FAT filesystem and ACPI/HID hardware messages. |
| `managed/system/system.log` | 772 | Repeats the CrowdSec registration failure and engine stop; later time synchronization succeeds. |
| `managed/system/timeshift/timeshift.log` | 2 | Informational records. |
| `managed/system/usb/usb.log` | 105 | Includes UCSI error 88 and failed GET_PDOS (-5). |
| `managed/system/zram/zram.log` | 5 | Successful setup records. |

The 23 empty logs comprise OpenAI model/runtime logs (5), chkrootkit (4),
ClamAV (2), clamscan (1), CrowdSec firewall bouncer (1), debsecan (1), debsums
(1), Lynis (3), rkhunter (2), spectre-meltdown-checker (1), fwupd security scan
(1), and storage (1). Empty output does not establish successful execution.

## CrowdSec history and automatic sequence

The initial available snapshot is
`2c0e368471ad4f78486dce93879144a319dcc13c`, following the GitOps branch clear.
Before this patch, the late-stage credential route, CAPI registration command
and Console command were unchanged from that snapshot. The latest prior commit
`ddbbfb9b10eb1e5033a75574060f44198c6a24b0` reduced Console attempts to one and
changed restart delay from 30 seconds to one hour while introducing a verified
local-core marker. The logs establish a registration rejection, not its remote
cause; they contain no Console enrollment attempt. The user subsequently reports
that a direct CAPI registration succeeds and asks for the engine reload.

Installation still reads `PRESEED_CROWDSEC_TOKEN` from the trusted d-i
`/preseed.env` through the existing credential reader and stages it privately as
`/var/lib/firstboot/crowdsec/enroll.token`. Supported explicit command-line aliases
retain their existing precedence. No deployment secret is added to the payload.

Firstboot now performs the following automatically:

1. Bootstrap and verify the local engine and nftables bouncer, then enable them.
2. Parse the CAPI credential file privately. A missing, empty or incomplete
   credential mapping triggers `cscli capi register`; a nonempty URL alone no
   longer counts as registration. Unsafe or malformed configuration fails closed.
3. Verify that managed CAPI sharing, community pulls and blocklist pulls are
   enabled, then reload `crowdsec.service` and wait for LAPI readiness.
4. Enroll the Console with the staged token. The argument delimiter protects
   option-like token values. Successful requests are recorded as
   `pending-approval`; the user approves the engine in the CrowdSec Console.
5. Remove the consumed token and write the final completion marker only after
   that request succeeds. Temporary failures retain the token and remain retryable.

The package's `crowdsec/capi=false` debconf selection defers its install-time
remote request to this automatic firstboot sequence. The runtime `.local`
overlay explicitly enables CAPI and references the standard credentials path.
Valid existing credentials are reused and reloaded before enrollment.

A failed remote registration no longer stops verified local protection.
Reload failure invalidates the local-core marker so the next pass rechecks it.
Systemd retries initially after 30 seconds, increasing over five steps to a
maximum delay of one hour. An explicitly invalid Console token retains exit
status 2 and requires corrected input. Error categories and exit status are
logged; captured credential-bearing output remains private.

[CrowdSec configuration](https://docs.crowdsec.net/docs/configuration/crowdsec_configuration/),
[CAPI registration](https://docs.crowdsec.net/docs/cscli/cscli_capi_register/),
[Console enrollment](https://docs.crowdsec.net/docs/cscli/cscli_console_enroll/).

## Bouncer wiring

`crowdsec-firewall-bouncer-nftables` is installed by `scripts/late/crowdsec.sh`
after `cscli` validates the engine configuration. Its package provides the
`crowdsec-firewall-bouncer` binary and service. The inspected package postinst
calls its API-key setup before service start. Installation verifies the package,
protects the configuration with mode 0600, and runs the private bouncer verifier
offline. Firstboot verifies authentication to loopback LAPI, starts the service
after nftables and the engine, and enables both CrowdSec services.

The managed bouncer overlay selects nftables and loopback LAPI without replacing
the package-created secret. The firewall generator and nftables stop/reload
override replace only `labwc_filter` and `labwc_nat`; they preserve tables owned
by the CrowdSec bouncer. Existing stable/testing APT sources and pins are retained.
Python and PyYAML are explicit addon dependencies for credential/key verification.

The nftables package is the applicable firewall remediation component for this
setup. Local APT metadata lists a conflict with the iptables variant. eBPF is a
separate remediation backend; this task supplies no additional eBPF deployment
requirement. The custom bouncer needs a defined custom decision-handling script,
which this setup does not provide. Those components are not prerequisites for
the nftables bouncer or Console enrollment.
[Firewall bouncer package selection and managed mode](https://docs.crowdsec.net/docs/bouncers/firewall/),
[Custom remediation scripts](https://docs.crowdsec.net/u/bouncers/custom/).

## qBittorrent

The resolver directory and resolver file may be owned by root or by the specific
`systemd-resolve` account. Parent `/run` and `/run/systemd` checks remain root-only.
Symlinks, unrelated owners, writable shared state, nonregular files, hard links,
oversized input and DNS servers outside the selected route remain rejected.
This matches the systemd 261 resolved service's runtime-directory ownership.
[systemd v261 resolved service](https://raw.githubusercontent.com/systemd/systemd/v261/units/systemd-resolved.service.in).

Storage selection requires the configured persistent volume. Missing volumes,
symlink ancestry and directories left on `/run` fail before profile/download
creation. The launcher no longer creates or selects `$HOME/bittorrent`, and its
dedicated AppArmor grants have been removed. Existing files are preserved.
The existing network namespace, TCP/UDP peer forwarding, privacy policy, Qt
Fusion mitigation, GPU launch modes and private-Xwayland policy are retained.

## Validation

The focused suite executed 50 tests: 47 passed and 3 were skipped. It includes
`test_crowdsec_firstboot_retry`, `test_compz_qbittorrent_followup`, two CrowdSec
installer-ordering checks, four selected initrd credential checks, and four
qBittorrent/AppArmor incident checks.

The exact suite can be repeated from the repository root:

```sh
python3 -I -B - <<'PY'
import sys
import unittest
sys.path.insert(0, 'd-i/forky/tests')
names = (
    'test_crowdsec_firstboot_retry',
    'test_compz_qbittorrent_followup',
    'test_installer_hardening.ConfigurationOrderingTests.test_crowdsec_target_package_checks_preserve_dpkg_status_format',
    'test_installer_hardening.ConfigurationOrderingTests.test_crowdsec_engine_config_precedes_bouncer_install',
    'test_initrd_credentials.InitrdCredentialTests.test_full_supplied_env_format_all_mappings_all_shells',
    'test_initrd_credentials.InitrdCredentialTests.test_every_mapping_cmdline_overrides_env',
    'test_initrd_credentials.InitrdCredentialTests.test_env_fallback_works_without_stat_in_all_shells',
    'test_initrd_credentials.InitrdCredentialTests.test_known_alias_does_not_reenable_fallback_of_another_alias',
    'test_apparmor_incidents_20261004.SuppliedDenialTests.test_native_rule_reader_keeps_env_and_qbittorrent_inherit_execution',
    'test_apparmor_incidents_20261004.SuppliedDenialTests.test_qbittorrent_helper_has_reciprocal_namespace_and_cleanup_permissions',
    'test_apparmor_incidents_20261004.SuppliedDenialTests.test_qbittorrent_exec_inherits_payload_runtime_under_no_new_privs',
    'test_apparmor_incidents_20261004.SuppliedDenialTests.test_native_parser_permissions_cover_nested_documents_usb_and_unclean_journals',
)
result = unittest.TextTestRunner(verbosity=2).run(
    unittest.defaultTestLoader.loadTestsFromNames(names))
raise SystemExit(not result.wasSuccessful())
PY
```

- Shell fixtures exercise production control flow in dash and BusyBox ash with
  mocked services and remote commands. They do not enroll a real engine.
- Packaged `cscli` 1.8.1 parses a private fake configuration and confirms the
  overlay and the actual configuration field names without contacting CAPI.
- Credential YAML, file metadata, staging and token consumption use private
  fixtures. Ancestor trust/root UID are modeled where the tool runtime maps
  `/` and `/tmp` to UID 65534. Production ownership checks remain strict.
- Two pre-existing initrd tests explicitly skip that unavailable trusted-ancestry
  fixture. A separate owned fixture covers the CrowdSec token path.
- Live slirp packet forwarding is skipped because `/dev/net/tun` is unavailable.
- Native AppArmor parsing uses an isolated policy copy; no kernel policy is loaded.
- Both changed POSIX scripts pass dash and BusyBox syntax checks. Python parsing
  passes for the embedded credential parser, launcher and changed tests.
- ShellCheck passes with SC2016 excluded for the existing intentional quoted
  scripts evaluated inside the target shell.
- The rendered firstboot unit passes isolated `systemd-analyze --root` verification
  with inert dependency/executable fixtures. The checker is systemd 262; the new
  retry directives are documented in systemd v261 and were introduced in 254.
  [systemd v261 service directives](https://raw.githubusercontent.com/systemd/systemd/v261/man/systemd.service.xml).

`python3 -B tools/build.py` completed successfully and regenerated
`payload.manifest`, `payload.tar.gz` and `preseed.cfg`.
`python3 -B tools/build.py --check` completed successfully with
`snapshot, pins and preseed are current`. Existing EncodingWarning diagnostics
in build/check helpers did not fail either command.

Independent verification compared all 1,704 archive entries to source bytes and
manifest SHA-256 values. Exactly eight intended CrowdSec/qBittorrent payload
entries changed, with no added or removed entries. All 12 paths named for
Zoom/Discord/Xwayland and all 133 other desktop-wrapper profile blocks, plus the
policy preamble, remain byte-identical to HEAD. `git diff --check` passes.

## Installed-host limits

Live automatic registration, Console appearance/approval, post-reload CAPI
communication, bouncer enforcement, and graphical qBittorrent/tracker operation
still require an installed host. A remote HTTP rejection cannot be conclusively
attributed from the supplied redacted diagnostics. The patch provides automatic
retry and preserves local protection and enrollment input during that failure.

The FAT warning for `nvme0n1p1` describes an existing unclean EFI filesystem and
requires host filesystem investigation. UCSI/GET_PDOS, ACPI reservations and
the HID report error require device/firmware/kernel investigation. This repository
change does not establish that those conditions have been repaired. Missing
global Xwayland, Crystal Dock API deprecation, duplicate packaged grok notices,
and the unmerged-bin package taint do not establish additional failures in this
capture. No source compilation or Xwayland-policy change is introduced.

## Additional thunar-volman denial supplied afterward

The subsequent LPL-346 records numbered 3166–3215 contain 50 repeated
`desktop-launcher` open denials for five root-owned input metadata paths:

- `/run/udev/data/+input:input33`
- `/run/udev/data/+input:input34`
- `/run/udev/data/c13:73`
- `/run/udev/data/c13:72`
- `/run/udev/data/c13:34`

These records were supplied separately after the 47-file capture above.
The installed package lists `/usr/bin/thunar-volman`. The existing
`desktop-launcher` `/usr/bin/** rPix` rule permits inherited execution when
there is no matching application profile, consistent with the supplied label.
The canonical profile had block/USB udev metadata grants but lacked these input
families. Linux character major 13 is the input core.
[Linux device assignments](https://www.kernel.org/doc/Documentation/admin-guide/devices.txt).

The only production policy addition is this read rule and its comment in
`hooks/target/etc/apparmor.d/desktop-utilities`:

```apparmor
/run/udev/data/{c13:[0-9]*,+input:input[0-9]*} r,
```

The rule is in `desktop-launcher`, which is the label in the denial records.
It permits root-owned udev metadata reads without an owner qualifier and adds
no raw-device or write permission. The existing desktop-profile catalog and
`stage_target_desktop_apparmor_profiles` already stage this source to
`/etc/apparmor.d/desktop-utilities`; no new staging path or profile transition
is required.

The existing native AppArmor effective-rule test was extended. Before the
policy change, all five reported paths and four additional input-ID cases
lacked read permission. After the change, all nine cases have exactly `r` for
non-owned files. Six negative cases verify that unrelated subsystems/majors,
nonnumeric initial IDs and child paths remain outside these grants.

All three selected checks pass:

1. `test_apparmor_incidents_20261004.SuppliedDenialTests.test_native_parser_permissions_cover_nested_documents_usb_and_unclean_journals`
2. `test_apparmor_incidents_20261004.SuppliedDenialTests.test_compositor_env_helper_inherits_confinement_without_missing_transition`
3. `test_policy_review_20260916.AppArmorReviewTests.test_udev_queries_do_not_add_device_access`

The native parser uses the actual managed profiles and abstractions in an
isolated copy, including the existing document, USB, qBittorrent and journal
checks. This verifies compiled rule matching without loading policy into the
host kernel. Live hotplug and denial clearance on LPL-346 require the updated
installed policy and have not been exercised from this workspace.

The follow-up `python3 -B tools/build.py` and `python3 -B tools/build.py --check`
both pass. Independent comparison against the pre-fix snapshot `1f304d4`
confirms all 1,704 source/archive/manifest entries agree. Only
`hooks/target/etc/apparmor.d/desktop-utilities` changes in the payload, and its
entire difference is the read rule and comment above. The other 1,703 entries,
including CrowdSec, qBittorrent and private Xwayland, are byte-identical.

## Working-backup and network follow-up

The later supplied `todo/cs`, `todo/crowd` and `todo/crowdi` were also read,
bringing this capture to 50 files. These contain private credential material;
only the non-secret failure facts are recorded here. LPL-454 runs
`v1.8.1-debian-pragmatic-amd64-909b5157`. Correct Console enrollment syntax and
`cscli capi status` both receive remote HTTP 403. The successful enrollment on
LPL-346 establishes that the attachment key can work; an invalid attachment
key does not explain a separate CAPI authentication failure.

Compared CrowdSec's class, late installer, firstboot helper and service against
the user-identified working checkout at
`/home/mcramer/Workspace/debian-preseed-de.bak`. It also defers CAPI registration
to firstboot and uses `cscli capi register --error`, followed by engine
activation and `cscli console enroll --overwrite --name HOST TOKEN`. The current
helper preserves those registration/enrollment commands, adds an option
terminator before the token, and uses the documented reload operation to
activate credentials. It does not rotate populated credentials on HTTP 403.

CrowdSec documents a one-hour CAPI ban after excessive authentication, including
restart loops and repeated `cscli capi status` calls. This is a documented
explanation consistent with the capture, rather than proof of the failing
host's public-IP ban state.
[CrowdSec CAPI 403 troubleshooting](https://docs.crowdsec.net/u/troubleshooting/capi_403/).
All ten repository profiles disable Tailscale accepted DNS/routes and leave
the exit-node value empty. This change adds no enrollment routing override.

The follow-up changes:

- Both firstboot retry and engine failure restart wait 65 minutes, allowing the
  documented ban interval to expire. This also delays recovery from other
  engine failures; healthy engine operation is unaffected.
- A root-only credential fingerprint records successful activation. Console
  retries do not reload unchanged credentials or add CAPI status probes.
  Changed/new credentials still reload before enrollment. The token and
  completion gate remain intact after failures, with local services retained
  when they have passed their existing verification.
- The retry drop-in is staged by the late CrowdSec installer, the fingerprint
  is removed by secondboot cleanup, and firstboot AppArmor permits inherited
  `sha256sum` execution. CAPI sharing and both pull options remain enabled.
- The normal, Intel and NVIDIA qBittorrent launch paths now use packaged
  `pasta` from Debian's `passt` package. The desktop package class and installed
  verifier require it. Its package maintainer scripts only manage the packaged
  AppArmor profiles; no daemon is introduced by this package.
- The private TAP remains `tap0`, `10.0.2.100/24`, MTU 65520. Only the configured
  peer port is forwarded for TCP and UDP, bound to the selected host address
  and interface. Outbound sockets use that same source/interface. Automatic
  forwarding/scanning, gateway-to-host mapping, and DHCP/IPv6 advertisements
  are disabled; DNS continues to use the validated routed upstreams.
- Pasta is supervised in the existing session cgroup. Private PID-file
  readiness must match the actual helper PID before either startup gate is
  released. Failed setup kills the pinned namespace init before closing
  Bubblewrap's release pipe. Helper failure stops the application. Diagnostics
  are private, bounded and sanitized before reporting the backend error cause.
- The helper has a dedicated AppArmor label, native sandbox permissions, and
  reciprocal namespace/cleanup permissions. The torrent payload receives no
  helper state, TUN device or host network. Unrelated applications keep their
  existing network backend; the disposable pure-privacy launch path is unchanged.
- Global/alternate upload and download limits are managed as unlimited, and
  alternative-speed selection and bandwidth scheduling are disabled. Existing
  unrelated preferences, tracker privacy, TLS/SSRF checks, fixed peer ports,
  profile locking, Qt IPC, mounted-volume requirement and no-home-fallback
  storage policy are retained.

Pasta translates packets to native host sockets rather than implementing
slirp's full TCP stack.
[Debian pasta manual](https://manpages.debian.org/testing/passt/pasta.1.en.html).
Its installed package is `0.0~git20261002.cba3570-1`. The corresponding Debian
source was inspected as data, without compilation: `passt.c` calls TAP setup
and `fwd_listen_init()` before writing the PID file; `fwd.c` exits initialization
when a strong explicit TCP or UDP port bind fails. Automatic/`all` forwarding
rules would have weaker semantics and are not used here.
[Debian source archive](https://deb.debian.org/debian/pool/main/p/passt/passt_0.0~git20261002.cba3570.orig.tar.xz).

### Follow-up validation

The exact focused suite is:

```sh
python3 -I -B - <<'PY'
import sys
import unittest
sys.path.insert(0, 'd-i/forky/tests')
names = [
    'test_crowdsec_firstboot_retry',
    'test_compz_qbittorrent_followup',
    'test_installer_hardening.ConfigurationOrderingTests',
    'test_apparmor_incidents_20261004',
    'test_policy_review_20260916.AppArmorReviewTests.test_udev_queries_do_not_add_device_access',
]
result = unittest.TextTestRunner(verbosity=1).run(
    unittest.defaultTestLoader.loadTestsFromNames(names))
raise SystemExit(not result.wasSuccessful())
PY
```

It runs 77 tests: 75 pass and the two packaged-backend TCP/UDP packet tests
skip because the tool environment has no `/dev/net/tun`. Real Bubblewrap,
pidfd cancellation, startup gates, argument preservation and process reaping
run with simulated pasta network readiness. Native AppArmor compilation and
effective file-permission checks cover five policy files, including the
CrowdSec fingerprint operation and pasta helper permissions. Native systemd
unit parsing passes with inert executable/dependency fixtures; the checker
is systemd 262, while the changed duration directives also apply to 261.2.
Dash parsing and `git diff --check` pass.

The user's ISP advertises 1000/1000 Mbit/s and their usual torrent rate is about
90 MiB/s. This environment does not establish a new torrent transfer rate:
live TCP/UDP forwarding under enforced policy, throughput on the mounted volume,
remote CAPI enrollment/appearance, and Console approval remain installed-host
validation. The code cannot override a CrowdSec server-side ban. No live
enrollment, host service restart, policy load, source compilation or deployment
was performed during this follow-up.
