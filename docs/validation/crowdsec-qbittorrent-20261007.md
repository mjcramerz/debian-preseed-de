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
