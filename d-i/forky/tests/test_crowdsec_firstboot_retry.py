"""Exercise CrowdSec firstboot retry decisions without a daemon or remote API."""

from pathlib import Path
import os
import shlex
import shutil
import subprocess
import tempfile
import unittest


FORKY = Path(__file__).resolve().parents[1]
SOURCE = (FORKY / "scripts/firstboot/assets/var/lib/firstboot/bin/crowdsec-firstboot.tmpl").read_text(encoding="utf-8")
UNIT = (FORKY / "scripts/firstboot/assets/etc/systemd/system/crowdsec-firstboot.service.tmpl").read_text(encoding="utf-8")
LATE = (FORKY / "scripts/late/crowdsec.sh").read_text(encoding="utf-8")
OVERLAY = (FORKY / "hooks/target/etc/crowdsec/config.yaml.local.tmpl").read_text(encoding="utf-8")
SHELLS = (("dash", ["/bin/dash"]),)
BUSYBOX = shutil.which("busybox")
if BUSYBOX:
    SHELLS += (("busybox", [BUSYBOX, "sh"]),)


def source_function(name: str, source: str = SOURCE) -> str:
    start = source.index(name + "() {")
    return source[start:source.index("\n}\n", start) + 2]


class CrowdSecFirstbootRetryTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('systemd-analyze'), 'native systemd unit checker unavailable')
    def test_retry_unit_and_engine_dropin_parse_with_native_systemd(self):
        with tempfile.TemporaryDirectory(prefix='crowdsec-units-') as directory:
            units = Path(directory)
            firstboot = UNIT
            for name, value in (('HOST_VARIANT', 'desktop'), ('ENROLL_TOKEN_FILE', '/private/enroll.token'),
                                ('COMPLETE_FILE', '/private/complete'), ('STATUS_FILE', '/private/status.env')):
                firstboot = firstboot.replace('__INSTALLER_CROWDSEC_' + name + '__', value)
            # Parsing only: substitute the absent installed bootstrap helper
            # with an inert executable. No service or remote API is started.
            firstboot = firstboot.replace('ExecStart=/var/lib/firstboot/bin/crowdsec-firstboot',
                                           'ExecStart=/usr/bin/true')
            (units / 'crowdsec-firstboot.service').write_text(firstboot, encoding='utf-8')
            for name in ('secondboot', 'auditd'):
                (units / (name + '.service')).write_text(
                    '[Unit]\nDescription=Inert dependency fixture\n[Service]\nExecStart=/usr/bin/true\n', encoding='ascii')
            engine = units / 'crowdsec.service'
            engine.write_text('[Unit]\nDescription=Engine parser fixture\n'
                              '[Service]\nType=notify\nExecStart=/usr/bin/true\nRestart=always\nRestartSec=60\n', encoding='ascii')
            dropin = units / 'crowdsec.service.d/20-capi-retry.conf'
            dropin.parent.mkdir()
            shutil.copyfile(FORKY / 'hooks/target/etc/systemd/system/crowdsec.service.d/20-capi-retry.conf', dropin)
            result = subprocess.run(['systemd-analyze', '--man=no', '--generators=no', 'verify',
                                      str(units / 'crowdsec-firstboot.service'), str(engine)],
                env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'SYSTEMD_UNIT_PATH': str(units) + ':',
                     'SYSTEMD_LOG_LEVEL': 'warning'}, text=True, encoding='utf-8', capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotRegex(result.stderr, r'Unknown (key|section)|Failed to parse|Invalid argument')

    def test_preseed_env_token_is_staged_privately_and_consumed_as_console_argument(self):
        credentials = (FORKY / 'scripts/common/credentials.sh').read_text(encoding='utf-8')
        # Only the ancestry limit and firstboot root UID are modeled for this
        # non-root fixture. File checks, reader, staging and enroll code are real.
        credentials = credentials.replace('[ "$preseed_check_parent" != / ] || break',
            '[ "$preseed_check_parent" != "${INSTALLER_PRESEED_ENV_FILE%/*}" ] || break')
        probes = (FORKY / 'scripts/common/modules/credentials-probes.sh').read_text(encoding='utf-8')
        probes = probes[:probes.index('installer_cmdline_seed_reference_pair() {')]
        start = LATE.index('if crowdsec_token=$(crowdsec_cmdline_token 2>/dev/null); then')
        end = LATE.index('\n\n\nrun_in_target', start)
        reader = source_function('read_token').replace('= 0:600:1', '= "$CASE_UID":600:1')
        code = credentials + '\n' + probes + '\n' + '\n'.join((
            source_function('crowdsec_normalize_token', LATE),
            source_function('crowdsec_cmdline_token', LATE),
            source_function('normalize_crowdsec_token'), reader,
            source_function('enroll_console'), source_function('remove_enrollment_token'),
        )) + """
umask 077
INSTALLER_PRESEED_ENV_FILE=$1/preseed.env
INSTALLER_CMDLINE=quiet
target_root=$1/target
token_file=/var/lib/firstboot/crowdsec/enroll.token
CROWDSEC_ENROLL_TOKEN_FILE=${target_root}${token_file}
CROWDSEC_ENROLL_ATTEMPTS=1
work_dir=$1
crowdsec_info() { printf 'staged\\n'; }
crowdsec_fatal() { printf 'invalid-token\\n' >&2; exit 91; }
log_line() { :; }
timeout() { printf '%s\\n' "$@" >"$CASE_ARGUMENTS"; }
""" + LATE[start:end] + """
[ "$(find -P "$CROWDSEC_ENROLL_TOKEN_FILE" -maxdepth 0 -printf %m:%n)" = 600:1 ]
consumed=$(read_token)
enroll_console "$consumed" fixture-host
unset consumed
remove_enrollment_token
"""
        for label, shell in SHELLS:
            for token in ('fixture-token', '--fixture-$(id)'):
                with self.subTest(shell=label, token_kind=token.startswith('--')), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    token_path = root / 'target/var/lib/firstboot/crowdsec/enroll.token'
                    token_path.parent.mkdir(parents=True, mode=0o700)
                    environment_file = root / 'preseed.env'
                    content = 'PRESEED_CROWDSEC_TOKEN=' + shlex.quote(token) + '\n'
                    environment_file.write_text(content, encoding='ascii')
                    environment_file.chmod(0o600)
                    arguments = root / 'arguments'
                    result = subprocess.run([*shell, '-eu', '-c', code, 'crowdsec-fixture', directory],
                        env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'CASE_UID': str(os.geteuid()),
                             'CASE_ARGUMENTS': str(arguments)}, text=True, encoding='utf-8',
                        capture_output=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(arguments.read_text(encoding='ascii').splitlines()[-2:], ['--', token])
                    self.assertEqual(environment_file.read_text(encoding='ascii'), content)
                    self.assertFalse(token_path.exists())
                    self.assertNotIn(token, result.stdout + result.stderr)

    def test_capi_overlay_guard_preserves_unknown_administrator_config(self):
        code = source_function('crowdsec_stage_logging_overlay', LATE) + """
target_root=$1
crowdsec_validate_abs_target_path() { :; }
crowdsec_stage_target_asset() { printf 'staged\\n'; }
crowdsec_fatal() { printf 'preserved\\n' >&2; exit 91; }
crowdsec_stage_logging_overlay fixture /config.yaml.local engine
"""
        cases = ((OVERLAY, True), (OVERLAY.split('api:\n', 1)[0], True),
                 (OVERLAY.replace('sharing: true', 'sharing: false'), False),
                 (OVERLAY.replace('/etc/crowdsec/online_api_credentials.yaml', '/etc/custom.yaml'), False),
                 (OVERLAY.replace('        blocklists: true\n', ''), False),
                 (OVERLAY + '  client:\n    insecure_skip_verify: true\n', False))
        for label, shell in SHELLS:
            for source, accepted in cases:
                with self.subTest(shell=label, accepted=accepted), tempfile.TemporaryDirectory() as root:
                    path = Path(root) / 'config.yaml.local'
                    path.write_text(source, encoding='utf-8')
                    result = subprocess.run([*shell, '-eu', '-c', code, 'crowdsec-fixture', root],
                        env={'PATH': '/usr/bin:/bin'}, text=True, encoding='utf-8',
                        capture_output=True, timeout=5)
                    self.assertEqual(result.returncode, 0 if accepted else 91, result.stderr)
                    self.assertEqual(path.read_text(encoding='utf-8'), source)
                    self.assertEqual('staged' in result.stdout, accepted)

    @unittest.skipUnless(shutil.which('cscli'), 'packaged cscli unavailable for offline config parsing')
    def test_packaged_cscli_loads_enabled_capi_overlay_and_rejects_disabled_state(self):
        # Real cscli parsing; private fake credentials and paths, no API call.
        binary = shutil.which('cscli')
        with tempfile.TemporaryDirectory(prefix='crowdsec-config-fixture-') as directory:
            root = Path(directory)
            (root / 'hub').mkdir()
            shim = root / 'cscli'
            shim.write_text('#!/bin/sh\nexec "$CASE_BINARY" -c "$CASE_CONFIG" "$@"\n', encoding='ascii')
            shim.chmod(0o700)
            credentials = root / 'credentials.yaml'
            credentials.write_text('url: https://api.crowdsec.net/\nlogin: fixture-login\n'
                                   'password: fixture-password\n', encoding='ascii')
            credentials.chmod(0o600)
            config = root / 'config.yaml'
            config.write_text(f'''common:
  daemonize: false
  log_media: stdout
  log_level: error
  log_dir: {root}
config_paths:
  config_dir: {root}
  data_dir: {root}
  hub_dir: {root}/hub
  simulation_path: {root}/simulation.yaml
crowdsec_service:
  enable: false
db_config:
  type: sqlite
  db_path: {root}/database.sqlite
api:
  client:
    credentials_path: {credentials}
  server:
    listen_uri: 127.0.0.1:8080
    profiles_path: {root}/profiles.yaml
    online_client:
      credentials_path: {credentials}
''', encoding='utf-8')
            overlay = OVERLAY.replace('__INSTALLER_LOG_CROWDSEC_DIR__', str(root))
            overlay = overlay.replace('__INSTALLER_LOG_CROWDSEC_LEVEL__', 'error')
            for suffix in ('MAXSIZE_MIB', 'MAXAGE_DAYS', 'COUNT'):
                overlay = overlay.replace('__INSTALLER_LOG_ROTATE_' + suffix + '__', '2')
            overlay = overlay.replace('/etc/crowdsec/online_api_credentials.yaml', str(credentials))
            overlay = overlay.replace('log_media: file', 'log_media: stdout')
            code = source_function('verify_capi_enabled') + """
log_line() { printf '%s\\n' "$*"; }
verify_capi_enabled
"""
            for setting in (None, 'sharing', 'community', 'blocklists'):
                value = overlay if setting is None else overlay.replace(setting + ': true', setting + ': false')
                config.with_name('config.yaml.local').write_text(value, encoding='utf-8')
                result = subprocess.run(['/bin/dash', '-eu', '-c', code, 'crowdsec-fixture'],
                    env={'PATH': str(root) + ':/usr/bin:/bin', 'LC_ALL': 'C', 'CASE_CONFIG': str(config),
                         'CASE_BINARY': binary}, text=True, encoding='utf-8',
                    capture_output=True, timeout=10)
                with self.subTest(disabled_setting=setting):
                    self.assertEqual(result.returncode, 0 if setting is None else 1, result.stderr)
                    self.assertIn('capi_communication=' + ('enabled' if setting is None else 'disabled'), result.stdout)
                    self.assertNotIn('fixture-password', result.stdout + result.stderr)

    def test_private_capi_credentials_require_complete_safe_yaml(self):
        # The runtime remaps / and /tmp to an overflow UID. Restrict this fixture
        # to its owned parent; real file metadata, no-follow opens, bounds and
        # YAML parsing remain in use. Production checks every ancestor.
        parser = source_function('capi_credentials_configured').replace(
            'for parent in path.parents:', 'for parent in (path.parent,):')
        code = parser + '\nonline_credentials_file=$1\ncapi_credentials_configured\n'
        complete = 'url: https://api.crowdsec.net/\nlogin: fixture-login\npassword: fixture-password\n'
        cases = (('complete', complete, 0), ('url-only', 'url: https://api.crowdsec.net/\n', 1),
                 ('login-only', 'url: https://api.crowdsec.net/\nlogin: fixture-login\n', 1),
                 ('empty', '', 1), ('missing', '', 1), ('malformed', 'login: [\n', 2),
                 ('sequence', '- fixture-password\n', 2), ('oversized', 'x' * 16385, 2),
                 ('public-mode', complete, 2), ('hardlink', complete, 2),
                 ('symlink', complete, 2), ('writable-parent', complete, 2))
        for label, shell in SHELLS:
            for case, content, expected in cases:
                with self.subTest(shell=label, case=case), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    credentials = root / 'credentials.yaml'
                    if case != 'missing':
                        credentials.write_text(content, encoding='ascii')
                        credentials.chmod(0o644 if case == 'public-mode' else 0o600)
                    if case == 'hardlink':
                        os.link(credentials, root / 'other.yaml')
                    elif case == 'symlink':
                        credentials.rename(root / 'other.yaml')
                        credentials.symlink_to(root / 'other.yaml')
                    elif case == 'writable-parent':
                        root.chmod(0o770)
                    result = subprocess.run([*shell, '-eu', '-c', code,
                        'crowdsec-fixture', str(credentials)], env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'},
                        text=True, encoding='utf-8', capture_output=True, timeout=10)
                    self.assertEqual(result.returncode, expected, result.stderr)
                    self.assertEqual(result.stdout, '')
                    self.assertNotIn('fixture-password', result.stderr)

    def test_new_capi_credentials_reload_engine_and_failed_reload_invalidates_core_marker(self):
        code = source_function('ensure_capi_registration') + '\n' + source_function('write_core_ready_marker') + """
CROWDSEC_CORE_READY_FILE=$1/core-ready
CROWDSEC_CAPI_ACTIVATED_FILE=$1/capi-activated
CASE_CREDENTIALS=$1/credentials.yaml
crowdsec_config_path() { printf '%s\\n' "$CASE_CREDENTIALS"; }
run_required_crowdsec_command() { printf 'registered\\n'; printf 'fixture-credentials\\n' >"$CASE_CREDENTIALS"; }
capi_credentials_configured() { [ -s "$CASE_CREDENTIALS" ]; }
verify_capi_enabled() { return 0; }
wait_for_lapi() { return 0; }
systemctl() { printf '%s\\n' "$*"; [ "$CASE_RELOAD" = success ]; }
log_line() { printf '%s\\n' "$*"; }
ensure_capi_registration
"""
        for label, shell in SHELLS:
            for reload, existing in (('success', False), ('failure', False),
                                     ('success', True), ('failure', True)):
                with self.subTest(shell=label, reload=reload, existing=existing), tempfile.TemporaryDirectory() as root:
                    marker = Path(root) / 'core-ready'
                    marker.write_text('ready\n', encoding='ascii')
                    marker.chmod(0o600)
                    if existing:
                        (Path(root) / 'credentials.yaml').write_text('existing-credentials\n', encoding='ascii')
                    result = subprocess.run([*shell, '-eu', '-c', code, 'crowdsec-fixture', root],
                        env={'PATH': '/usr/bin:/bin', 'CASE_RELOAD': reload}, text=True,
                        encoding='utf-8', capture_output=True, timeout=5)
                    self.assertEqual(result.returncode, 0 if reload == 'success' else 1, result.stderr)
                    self.assertIn('reload crowdsec.service', result.stdout)
                    self.assertEqual('registered\n' in result.stdout, not existing)
                    self.assertEqual(marker.exists(), reload == 'success')
                    self.assertTrue((Path(root) / 'credentials.yaml').exists())

    def test_capi_failure_keeps_local_protection_and_token_until_successful_retry(self):
        start = SOURCE.index('if [ -f "$CROWDSEC_CORE_READY_FILE" ] &&')
        body = SOURCE[start:].replace(
            "/usr/local/libexec/crowdsec-bouncer-verify >/dev/null 2>&1",
            "bouncer_verify >/dev/null 2>&1",
        )
        code = """
umask 077
CROWDSEC_CORE_READY_FILE=$1/core-ready
CROWDSEC_COMPLETE_FILE=$1/complete
CROWDSEC_STATUS_FILE=$1/status.env
CROWDSEC_ENROLL_TOKEN_FILE=$1/enroll.token
CROWDSEC_HOST_VARIANT=desktop
CROWDSEC_LOG_FILE=fixture.log
timestamp() { printf 'fixture-time'; }
log_line() { printf 'event=%s\\n' "$*"; }
systemctl() { printf '%s\\n' "$*" >>"$FIXTURE_CALLS"; }
timeout() { return 0; }
bouncer_verify() { return 0; }
wait_for_unit() { return 0; }
wait_for_lapi() { return 0; }
run_optional_crowdsec_command() { return 0; }
run_required_crowdsec_command() { return 0; }
ensure_bouncer_api_key() { return 0; }
ensure_capi_registration() {
  printf 'capi-register\\n' >>"$FIXTURE_CALLS"
  [ "$CASE_CAPI" = success ]
}
read_token() { cat "$CROWDSEC_ENROLL_TOKEN_FILE"; }
enroll_console() { printf 'console-enroll\\n' >>"$FIXTURE_CALLS"; return 0; }
stop_bootstrap_services() { systemctl stop crowdsec-firewall-bouncer.service crowdsec.service; }
""" + "\n".join(source_function(name) for name in (
            "write_status", "write_complete_marker", "write_core_ready_marker", "remove_enrollment_token",
        )) + "\n" + body
        for label, shell in SHELLS:
            with self.subTest(shell=label), tempfile.TemporaryDirectory() as root:
                directory = Path(root)
                token = directory / "enroll.token"
                token.write_text("fixture-token\n", encoding="ascii")
                token.chmod(0o600)
                calls = directory / "calls"
                environment = {"PATH": "/usr/bin:/bin", "FIXTURE_CALLS": str(calls),
                               "CASE_CAPI": "failure"}
                failed = subprocess.run([*shell, "-eu", "-c", code, "crowdsec-fixture", root],
                    env=environment, text=True, encoding="utf-8", capture_output=True, timeout=5)
                self.assertEqual(failed.returncode, 1, failed.stderr)
                actions = calls.read_text(encoding="ascii")
                self.assertIn("enable crowdsec.service crowdsec-firewall-bouncer.service", actions)
                self.assertNotIn("stop ", actions)
                self.assertNotIn("console-enroll", actions)
                self.assertTrue((directory / "core-ready").exists())
                self.assertFalse((directory / "complete").exists())
                self.assertEqual(token.read_text(encoding="ascii"), "fixture-token\n")
                self.assertIn("enrollment=retry-pending", (directory / "status.env").read_text())
                self.assertNotIn("fixture-token", failed.stdout + failed.stderr)

                calls.write_text("", encoding="ascii")
                environment["CASE_CAPI"] = "success"
                recovered = subprocess.run([*shell, "-eu", "-c", code, "crowdsec-fixture", root],
                    env=environment, text=True, encoding="utf-8", capture_output=True, timeout=5)
                self.assertEqual(recovered.returncode, 0, recovered.stderr)
                actions = calls.read_text(encoding="ascii")
                self.assertIn("capi-register\nconsole-enroll\n", actions)
                self.assertNotIn("restart ", actions)
                self.assertNotIn("stop ", actions)
                self.assertIn("core_bootstrap=already-verified", recovered.stdout)
                self.assertIn("enrollment=pending-approval", (directory / "complete").read_text())
                self.assertFalse(token.exists())
                self.assertNotIn("fixture-token", recovered.stdout + recovered.stderr)

                # Run the actual cleanup against an inert installed tree.
                # Pending console approval has the same successful bootstrap
                # marker contract as accepted Tailscale provisioning.
                target = directory / "target"
                crowd = target / "var/lib/firstboot/crowdsec"
                crowd.mkdir(parents=True)
                shutil.copyfile(directory / "complete", crowd / "complete")
                for path, content in {
                    "var/lib/firstboot/state/complete": "status=0\n",
                    "var/lib/firstboot/tailscale/complete": "status=0\n",
                    "var/lib/firstboot/bin/firstboot.sh": "inert\n",
                    "var/lib/firstboot/bin/crowdsec-firstboot": "inert\n",
                    "var/lib/firstboot/bin/tailscale-up": "inert\n",
                    "var/lib/firstboot/bin/secondboot-cleanup": "inert\n",
                    "var/lib/firstboot/lib/stage.sh": "inert\n",
                    "etc/systemd/system/firstboot.service": "inert\n",
                    "etc/systemd/system/crowdsec-firstboot.service": "inert\n",
                    "etc/systemd/system/tailscale-bootstrap.service": "inert\n",
                    "etc/systemd/system/secondboot.service": "inert\n",
                    "etc/apparmor.d/firstboot": "inert\n",
                }.items():
                    artifact = target / path
                    artifact.parent.mkdir(parents=True, exist_ok=True)
                    artifact.write_text(content, encoding="ascii")
                cleanup = subprocess.run([*shell, str(FORKY / "scripts/firstboot/assets/var/lib/firstboot/bin/secondboot-cleanup")],
                    env={"PATH": "/usr/bin:/bin", "SECONDBOOT_ROOT": str(target)},
                    text=True, encoding="utf-8", capture_output=True, timeout=5)
                self.assertEqual(cleanup.returncode, 0, cleanup.stderr)
                self.assertIn("removed completed CrowdSec bootstrap artifacts", cleanup.stdout)
                self.assertIn("removed completed Tailscale bootstrap artifacts", cleanup.stdout)
                self.assertFalse((target / "var/lib/firstboot").exists())
                self.assertFalse((target / "etc/systemd/system/secondboot.service").exists())
                self.assertIn("OnSuccess=secondboot.service", (FORKY / "scripts/firstboot/assets/etc/systemd/system/firstboot.service").read_text(encoding="utf-8"))

    def test_hub_failures_distinguish_remote_forbidden_from_local_permissions(self):
        code = source_function("run_crowdsec_command") + """
work_dir=$1
log_line() { printf 'event=%s\\n' "$*"; }
timeout() { printf '%s\\n' "$CASE_MESSAGE"; return 1; }
run_crowdsec_command optional hub-update cscli hub update || :
"""
        for message, expected in (("HTTP 403 Forbidden", "remote-forbidden"),
                                  ("open /etc/crowdsec: permission denied", "local-permission-denied"),
                                  ("network timeout", "command-failed")):
            with self.subTest(message=message), tempfile.TemporaryDirectory() as root:
                result = subprocess.run(["/bin/dash", "-eu", "-c", code,
                    "crowdsec-fixture", root], env={"PATH": "/usr/bin:/bin",
                    "CASE_MESSAGE": message}, text=True, encoding="utf-8",
                    capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("hub-update=failed reason=" + expected, result.stdout)
                self.assertNotIn(message, result.stdout + result.stderr)

    def test_console_distinguishes_invalid_key_from_forbidden_and_keeps_output_private(self):
        code = source_function("enroll_console") + """
work_dir=$1
CROWDSEC_ENROLL_ATTEMPTS=1
CROWDSEC_ENROLL_RETRY_DELAY_SECONDS=10
log_line() { printf 'event=%s\\n' "$*"; }
timeout() {
  printf 'attempt\\n' >>"$work_dir/calls"
  printf '%s\\n' "$@" >"$work_dir/arguments"
  printf '%s\\n' "$CASE_MESSAGE"
  return 1
}
if enroll_console fixture-token fixture-host; then
  printf 'result=0\\n'
else
  printf 'result=%s\\n' "$?"
fi
"""
        cases = (
            ("the attachment key provided is not valid", 2),
            ('API error: Forbidden; fixture-token', 3),
            ("bad HTTP code 403", 3),
            ("connection reset by peer", 1),
        )
        for label, shell in SHELLS:
            for message, expected in cases:
                with self.subTest(shell=label, response=message), tempfile.TemporaryDirectory() as root:
                    result = subprocess.run(
                        [*shell, "-eu", "-c", code, "crowdsec-fixture", root],
                        env={"PATH": "/usr/bin:/bin", "CASE_MESSAGE": message},
                        text=True, encoding="utf-8", capture_output=True, timeout=5,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn(f"result={expected}\n", result.stdout)
                    self.assertEqual((Path(root) / "calls").read_text(encoding="ascii"), "attempt\n")
                    self.assertEqual((Path(root) / "arguments").read_text(encoding="ascii").splitlines()[-2:],
                                     ['--', 'fixture-token'])
                    self.assertNotIn("fixture-token", result.stdout + result.stderr)

    def test_verified_core_retry_does_not_update_hub_or_restart_services(self):
        start = SOURCE.index('if [ -f "$CROWDSEC_CORE_READY_FILE" ] &&')
        end = SOURCE.index("\n# Remote availability", start)
        # Only the absolute verifier is replaced; all other shell control flow
        # runs from the production source against inert command fixtures.
        body = SOURCE[start:end].replace(
            "/usr/local/libexec/crowdsec-bouncer-verify >/dev/null 2>&1",
            "bouncer_verify >/dev/null 2>&1",
        )
        code = """
CROWDSEC_CORE_READY_FILE=$1
systemctl() {
  case "$1" in
    is-enabled|is-active)
      printf 'checked=%s:%s\\n' "$1" "$3"
      return 0
      ;;
  esac
  printf 'unexpected-systemctl=%s\\n' "$*"
  return 1
}
timeout() { return 0; }
bouncer_verify() { return 0; }
log_line() { printf 'event=%s\\n' "$*"; }
""" + body
        for label, shell in SHELLS:
            with self.subTest(shell=label), tempfile.TemporaryDirectory() as root:
                marker = Path(root) / "core-ready"
                marker.write_text("ready\n", encoding="ascii")
                result = subprocess.run(
                    [*shell, "-eu", "-c", code, "crowdsec-fixture", str(marker)],
                    env={"PATH": "/usr/bin:/bin"}, text=True, encoding="utf-8",
                    capture_output=True, timeout=5,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("core_bootstrap=already-verified", result.stdout)
                for action in ("is-enabled", "is-active"):
                    for unit in ("crowdsec.service", "crowdsec-firewall-bouncer.service"):
                        self.assertIn(f"checked={action}:{unit}", result.stdout)
                self.assertNotIn("hub_update=true", result.stdout)
                self.assertNotIn("restarting_services=true", result.stdout)

    def test_missing_bouncer_state_rechecks_core_before_retrying_console(self):
        start = SOURCE.index('if [ -f "$CROWDSEC_CORE_READY_FILE" ] &&')
        end = SOURCE.index("\n# Remote availability", start)
        body = SOURCE[start:end].replace(
            "/usr/local/libexec/crowdsec-bouncer-verify >/dev/null 2>&1",
            "bouncer_verify >/dev/null 2>&1",
        )
        code = """
CROWDSEC_CORE_READY_FILE=$1
systemctl() {
  case "$1" in
    is-enabled|is-active)
      [ "$1:$3" != "$FAIL_CHECK" ]
      return $?
      ;;
    *) return 0 ;;
  esac
}
timeout() { return 0; }
bouncer_verify() { return 0; }
wait_for_unit() { return 0; }
wait_for_lapi() { return 0; }
run_optional_crowdsec_command() { return 0; }
run_required_crowdsec_command() { return 0; }
ensure_capi_registration() { return 0; }
ensure_bouncer_api_key() { return 0; }
write_core_ready_marker() { return 0; }
log_line() { printf 'event=%s\\n' "$*"; }
""" + body
        with tempfile.TemporaryDirectory() as root:
            marker = Path(root) / "core-ready"
            marker.write_text("ready\n", encoding="ascii")
            for failure in ("is-enabled:crowdsec-firewall-bouncer.service",
                            "is-active:crowdsec-firewall-bouncer.service"):
                with self.subTest(failure=failure):
                    result = subprocess.run(
                        ["/bin/dash", "-eu", "-c", code, "crowdsec-fixture", str(marker)],
                        env={"PATH": "/usr/bin:/bin", "FAIL_CHECK": failure},
                        text=True, encoding="utf-8", capture_output=True, timeout=5,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("hub_update=true", result.stdout)
                    self.assertIn("core_bootstrap=complete", result.stdout)
                    self.assertNotIn("core_bootstrap=already-verified", result.stdout)

    def test_core_ready_marker_is_atomic_and_private(self):
        code = source_function("write_core_ready_marker") + "\nCROWDSEC_CORE_READY_FILE=$1\nwrite_core_ready_marker\n"
        for label, shell in SHELLS:
            with self.subTest(shell=label), tempfile.TemporaryDirectory() as root:
                marker = Path(root) / "core-ready"
                result = subprocess.run(
                    [*shell, "-eu", "-c", code, "crowdsec-fixture", str(marker)],
                    env={"PATH": "/usr/bin:/bin"}, text=True, encoding="utf-8",
                    capture_output=True, timeout=5,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(marker.read_text(encoding="ascii"), "ready\n")
                self.assertEqual(os.stat(marker).st_mode & 0o777, 0o600)
                self.assertEqual(list(Path(root).iterdir()), [marker])

    def test_retry_unit_and_cleanup_preserve_core_and_token_contract(self):
        self.assertIn("Environment=CROWDSEC_ENROLL_ATTEMPTS=1", UNIT)
        self.assertIn("RestartSec=65min", UNIT)
        self.assertNotIn("RestartSteps=", UNIT)
        self.assertNotIn("RestartMaxDelaySec=", UNIT)
        self.assertIn("RestartPreventExitStatus=2", UNIT)
        self.assertNotIn("StartLimitIntervalSec=infinity", UNIT)
        self.assertLess(SOURCE.index("systemctl enable crowdsec.service"),
                        SOURCE.index("write_core_ready_marker || {"))
        self.assertLess(SOURCE.index("write_core_ready_marker || {"),
                        SOURCE.index("enrollment_status=skipped"))
        cleanup = (FORKY / "scripts/firstboot/assets/var/lib/firstboot/bin/secondboot-cleanup").read_text(encoding="utf-8")
        self.assertIn('"${crowdsec_state_dir}/core-ready"', cleanup)
        self.assertIn('"${crowdsec_state_dir}/capi-activated"', cleanup)
        engine_retry = (FORKY / 'hooks/target/etc/systemd/system/crowdsec.service.d/20-capi-retry.conf').read_text(encoding='utf-8')
        self.assertIn('RestartSec=65min', engine_retry)
        self.assertIn('/etc/systemd/system/crowdsec.service.d/20-capi-retry.conf 0644', LATE)

    def test_console_retries_do_not_reload_unchanged_capi_credentials(self):
        code = source_function('ensure_capi_registration') + '\n' + source_function('write_core_ready_marker') + """
umask 077
CROWDSEC_CORE_READY_FILE=$1/core-ready
CROWDSEC_CAPI_ACTIVATED_FILE=$1/capi-activated
CASE_CREDENTIALS=$1/credentials.yaml
crowdsec_config_path() { printf '%s\\n' "$CASE_CREDENTIALS"; }
capi_credentials_configured() { return 0; }
verify_capi_enabled() { return 0; }
run_required_crowdsec_command() { printf 'unexpected-register\\n'; return 1; }
wait_for_lapi() { return 0; }
log_line() { printf '%s\\n' "$*"; }
systemctl() { [ "$1" != reload ] || printf 'reload\\n' >>"$CASE_CALLS"; }
printf 'fixture-private-credentials\\n' >"$CASE_CREDENTIALS"
ensure_capi_registration
ensure_capi_registration
[ "$(wc -l <"$CASE_CALLS")" -eq 1 ]
printf 'changed-private-credentials\\n' >"$CASE_CREDENTIALS"
ensure_capi_registration
[ "$(wc -l <"$CASE_CALLS")" -eq 2 ]
"""
        for label, shell in SHELLS:
            with self.subTest(shell=label), tempfile.TemporaryDirectory() as directory:
                result = subprocess.run([*shell, '-eu', '-c', code, 'crowdsec-fixture', directory],
                    env={'PATH': '/usr/bin:/bin', 'CASE_CALLS': str(Path(directory) / 'calls')},
                    text=True, encoding='utf-8', capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('capi_registration=already-activated', result.stdout)
                self.assertNotIn('private-credentials', result.stdout + result.stderr)
                marker = Path(directory) / 'capi-activated'
                self.assertEqual(marker.stat().st_mode & 0o777, 0o600)
                self.assertEqual(marker.stat().st_size, 65)
                self.assertNotIn('cscli capi status', SOURCE)


if __name__ == "__main__":
    unittest.main()
