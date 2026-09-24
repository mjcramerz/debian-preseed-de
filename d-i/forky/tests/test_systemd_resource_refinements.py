"""Resource policy boundaries, conditional staging and offline systemd load checks.

No managers are started: --test prints the loaded graph and never runs units.
Synthetic fragments isolate drop-in semantics from unavailable desktop packages.
"""
from __future__ import annotations
from payload_fixture import installed_argv as payload_installed_argv, source_exists as payload_source_exists, source_is_file as payload_source_is_file, source_stat as payload_source_stat
from payload_fixture import read_bytes as payload_read_bytes, read_text as payload_read_text

import ast
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest
import uuid

import test_systemd_resource_policy as base

USER = base.USER_BASE
VENDOR = 'etc/systemd/user'
SYSTEM = 'etc/systemd/system'
VENDOR_UNITS = ('hyprpolkitagent', 'mako', 'ssh-agent', 'wireplumber',
                'pipewire', 'pipewire-pulse', 'filter-chain', 'xdg-desktop-portal')
POLICIES = sorted(p for directory in (USER, VENDOR, SYSTEM)
                  for p in (base.TARGET / directory).glob('*/*.conf*')
                  if p.name.removesuffix('.tmpl') in ('60-resource-class.conf', '60-resources.conf',
                                '70-no-core.conf', '60-poll-limit.conf',
                                '60-resource-delegation.conf'))
SUFFIX = '0123456789abcdef0123456789abcdef'


def active_lines(path):
    return [line for line in payload_read_text(path).splitlines()
            if line.strip() and not line.lstrip().startswith('#')]


class ResourceRefinementTests(unittest.TestCase):
    def setUp(self):
        # Reuse production-renderer helpers without inheriting/rerunning its tests.
        self.runner = base.ResourcePolicyTests()

    def render_policies(self, directory, enabled='true'):
        """Copy the real policy files, render with the production POSIX helper."""
        rendered = []
        for source in POLICIES:
            dest = Path(directory) / source.parent.name / source.name.removesuffix('.tmpl')
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(payload_read_bytes(source))
            dest.chmod(0o644)
            rendered.append(dest)
        commands = 'TMP_ENV_DIR=' + shlex.quote(str(directory)) + '\n'
        commands += '\n'.join('apply_systemd_resource_placeholders ' + shlex.quote(str(p))
                              for p in rendered)
        self.runner.shell(commands, override=f'SYSTEMD_DEFAULT_IOACCOUNTING_ENABLE={enabled}\nSYSTEMD_IOWEIGHT_ENABLE={enabled}')
        # Mirror installer publication modes after atomic template rendering.
        for path in rendered:
            path.chmod(0o644)
        return rendered

    def fixtures(self, directory, enabled='true'):
        directory = Path(directory)
        policies = self.render_policies(directory, enabled)
        names = set()
        for p in policies:
            name = p.parent.name[:-2]
            if name.endswith('-.service'):
                name = name.replace('-.service', '-' + SUFFIX + '.service')
            elif name.endswith('-.scope'):
                name = name.replace('-.scope', '-' + SUFFIX + '.scope')
            elif name == 'user@.service':
                name = 'user@1000.service'
            # Scopes have no static fragment and require a running manager/API.
            # Their drop-in shape is checked separately, not passed off as a
            # successful static systemd verification.
            if not name.endswith('.scope'):
                names.add(name)
        names.update(('system.slice', 'app.slice', 'session.slice', 'background.slice',
                      'labwc-unrelated.service', 'systemd-coredump@.service',
                      'waybar.service', 'crystal-dock.service', 'wireplumber.service'))
        for name in sorted(names):
            suffix = name.rsplit('.', 1)[1]
            body = '[Unit]\nDescription=Offline resource-policy fixture\nDefaultDependencies=no\n'
            if suffix == 'service':
                body += '[Service]\nExecStart=/usr/bin/true\n'
                if name in ('pipewire.service', 'pipewire-pulse.service', 'filter-chain.service', 'wireplumber.service'):
                    body += 'Slice=session.slice\n'
                if name == 'labwc-unrelated.service':
                    body += 'LimitCORE=4096\n'
            elif suffix == 'socket':
                body += '[Socket]\nListenStream=%t/resource-policy-test.socket\nAccept=yes\nMaxConnections=16\nMaxConnectionsPerSource=8\n'
            else:
                body += '[' + suffix.capitalize() + ']\n'
            (directory / name).write_text(body)
            (directory / name).chmod(0o644)
        # Include every fixture in the offline graph; no service is executed.
        (directory / 'resource-policy.target').write_text(
            '[Unit]\nDescription=Offline resource-policy graph\nDefaultDependencies=no\nWants=' +
            ' '.join(n for n in sorted(names) if '@.' not in n) + '\n')
        (directory / 'resource-policy.target').chmod(0o644)
        return names

    def test_all_available_vendor_units_get_only_their_dropins(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'target'; target.mkdir()
            units = target / 'usr/lib/systemd/user'; units.mkdir(parents=True)
            for name in (*VENDOR_UNITS, 'xdg-desktop-portal-wlr'):
                (units / f'{name}.service').write_text('[Service]\nExecStart=/usr/bin/true\n')
            for enabled in ('true', 'false'):
                self.runner.shell(self.runner.staging(tmp) + 'desktop_install_vendor_resource_policy',
                                  override=f'SYSTEMD_DEFAULT_IOACCOUNTING_ENABLE={enabled}\nSYSTEMD_IOWEIGHT_ENABLE={enabled}')
                installed = list((target / VENDOR).rglob('*.conf'))
                self.assertEqual(len(installed), 10)
                for path in installed:
                    self.assertFalse(base.TOKEN.search(payload_read_text(path)))
                    self.assertNotIn('IOWeight=', payload_read_text(path))
                    self.assertEqual(payload_source_stat(path).st_mode & 0o777, 0o644)
                for name in ('pipewire', 'pipewire-pulse', 'filter-chain'):
                    self.assertEqual(active_lines(target / VENDOR / f'{name}.service.d/60-resources.conf'),
                                     ['[Service]', 'CPUWeight=200'])
                self.assertEqual(active_lines(target / VENDOR / 'hyprpolkitagent.service.d/70-no-core.conf'),
                                 ['[Service]', 'LimitCORE=0'])

    def test_vendor_policy_does_not_install_unavailable_services(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'target'; target.mkdir()
            units = target / 'usr/lib/systemd/user'; units.mkdir(parents=True)
            (units / 'hyprpolkitagent.service').write_text('[Service]\nExecStart=/usr/bin/true\n')
            (units / 'xdg-desktop-portal-gtk.service').write_text('[Service]\nExecStart=/usr/bin/true\n')
            self.runner.shell(self.runner.staging(tmp) + 'desktop_install_vendor_resource_policy')
            installed = {str(p.relative_to(target / VENDOR)) for p in (target / VENDOR).rglob('*.conf')}
            self.assertEqual(installed, {
                'hyprpolkitagent.service.d/60-resource-class.conf',
                'hyprpolkitagent.service.d/70-no-core.conf',
                'xdg-desktop-portal-.service.d/60-resource-class.conf'})

    def test_all_policy_dropins_parse_in_both_io_modes(self):
        if not shutil.which('systemd-analyze'):
            self.skipTest('systemd-analyze unavailable')
        for enabled in ('true', 'false'):
            with self.subTest(io=enabled), tempfile.TemporaryDirectory() as tmp:
                names = self.fixtures(tmp, enabled)
                env = dict(os.environ, SYSTEMD_UNIT_PATH=tmp + ':', SYSTEMD_LOG_LEVEL='warning')
                result = subprocess.run(payload_installed_argv(['systemd-analyze', '--generators=no', '--man=no', 'verify',
                                         *(str(Path(tmp) / n) for n in sorted(names))]),
                                        env=env, text=True, capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotRegex(result.stderr, r'Unknown (key|section)|Failed to parse|Invalid argument')

    def test_offline_manager_effective_prefixes_weights_and_core_limits(self):
        executable = Path('/usr/lib/systemd/systemd')
        if not payload_source_is_file(executable):
            self.skipTest('systemd executable unavailable')
        if os.geteuid() != 0:
            self.skipTest('isolated UID test requires root to drop privileges')
        for enabled in ('true', 'false'):
            with self.subTest(io=enabled), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); root.chmod(0o755)
                units = root / 'units'; units.mkdir(mode=0o755); units.chmod(0o755)
                self.fixtures(units, enabled)
                for directory in units.iterdir():
                    if directory.is_dir():
                        directory.chmod(0o755)
                for label in ('home', 'run', 'config', 'data'):
                    p = root / label; p.mkdir(mode=0o700); os.chown(p, 65534, 65534)
                env = dict(os.environ, HOME=str(root / 'home'), XDG_RUNTIME_DIR=str(root / 'run'),
                           XDG_CONFIG_HOME=str(root / 'config'), XDG_DATA_HOME=str(root / 'data'),
                           XDG_DATA_DIRS='/usr/local/share:/usr/share',
                           SYSTEMD_UNIT_PATH=str(units) + ':',
                           SYSTEMD_LOG_LEVEL='warning', SYSTEMD_LOG_TARGET='console')
                def unprivileged():
                    os.setgroups([]); os.setgid(65534); os.setuid(65534)
                result = subprocess.run(payload_installed_argv([str(executable), '--user', '--test', '--unit=resource-policy.target']),
                    env=env, preexec_fn=unprivileged, text=True, capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotRegex(result.stderr, r'Unknown (key|section)|Failed to parse|Invalid argument')
                blocks = {}
                for part in re.split(r'\n\s*\u2192 Unit ', result.stdout)[1:]:
                    name, body = part.split(':\n', 1)
                    blocks[name] = body
                def property_of(name, key):
                    self.assertIn(name, blocks)
                    match = re.search(r'^\s*' + re.escape(key) + r': (.+)$', blocks[name], re.M)
                    self.assertIsNotNone(match, f'{name}: missing {key}')
                    return match.group(1)
                for name in ('labwc-bitwarden-' + SUFFIX, 'labwc-power-lock-' + SUFFIX,
                             'labwc-kwallet-portal', 'hyprpolkitagent'):
                    for key in ('LimitCORE', 'LimitCORESoft'):
                        self.assertEqual(property_of(name + '.service', key), '0')
                self.assertEqual(property_of('labwc-unrelated.service', 'LimitCORE'), '4096')
                self.assertNotIn('70-no-core.conf', blocks['labwc-unrelated.service'])
                self.assertEqual(property_of('labwc-compositor.service', 'Slice'), 'session.slice')
                self.assertEqual(property_of('labwc-compositor.service', 'CPUWeight'), '300')
                unset = str((1 << 64) - 1)  # systemd's dump representation of an unset weight
                self.assertEqual(property_of('labwc-compositor.service', 'IOWeight'),
                                 '300' if enabled == 'true' else unset)
                for name in ('pipewire', 'pipewire-pulse', 'filter-chain'):
                    self.assertEqual(property_of(name + '.service', 'CPUWeight'), '200')
                    self.assertEqual(property_of(name + '.service', 'IOWeight'), unset)
                    self.assertEqual(property_of(name + '.service', 'Slice'), 'session.slice')
                for name in ('apt-repo-local-' + SUFFIX, 'timeshift-' + SUFFIX,
                             'apt-daily', 'apt-daily-upgrade', 'clamav-signature-update'):
                    self.assertEqual(property_of(name + '.service', 'Slice'), 'system-maintenance.slice')
                self.assertEqual(property_of('syncthing.service', 'Slice'), 'system-background.slice')
                for cls, weight in (('maintenance', '30'), ('background', '50')):
                    self.assertEqual(property_of(f'system-{cls}.slice', 'Slice'), 'system.slice')
                    self.assertEqual(property_of(f'system-{cls}.slice', 'CPUWeight'), weight)
                    self.assertEqual(property_of(f'system-{cls}.slice', 'IOWeight'),
                                     weight if enabled == 'true' else unset)
                self.assertIn('labwc-bitwarden-.service.d/70-no-core.conf',
                              blocks['labwc-bitwarden-' + SUFFIX + '.service'])
                self.assertEqual(property_of('systemd-coredump.socket', 'MaxConnections'), '16')
                self.assertEqual(property_of('systemd-coredump.socket', 'MaxConnectionsPerSource'), '8')
                self.assertEqual(property_of('systemd-coredump.socket', 'PollLimitIntervalSec'), '2s')
                self.assertEqual(property_of('systemd-coredump.socket', 'PollLimitBurst'), '64')
                self.assertEqual(property_of('mako.service', 'Slice'), 'app.slice')
                for name in ('waybar.service', 'crystal-dock.service'):
                    self.assertEqual(property_of(name, 'Slice'), 'app.slice')
                self.assertEqual(property_of('wireplumber.service', 'Slice'), 'session.slice')

    def test_scopes_and_helpers_do_not_get_execution_or_weight_policy(self):
        self.assertEqual(active_lines(base.TARGET / USER / 'app-.scope.d/60-resource-class.conf'),
                         ['[Scope]', 'Slice=app.slice'])
        for path in POLICIES:
            if path.name == '60-resource-class.conf':
                lines = active_lines(path)
                self.assertEqual(len(lines), 2, str(path))
                self.assertRegex(lines[1], r'^Slice=[a-z.-]+\.slice$')
            if path.name == '70-no-core.conf':
                self.assertEqual(active_lines(path), ['[Service]', 'LimitCORE=0'])
            self.assertNotRegex('\n'.join(active_lines(path)), r'(?m)^(?:Startup)?IOWeight=')
            self.assertNotRegex('\n'.join(active_lines(path)),
                r'(?m)^(Memory(?:Low|Min|High|Max)|CPUQuota|TasksMax|Nice|IOSchedulingClass|'
                r'LimitRTPRIO|LimitMEMLOCK|KillMode|Restart|NoNewPrivileges)=')

    def test_runtime_service_prefixes_match_existing_launchers(self):
        app = payload_read_text(base.TARGET / 'usr/local/lib/python3.14/dist-packages/labwc_managed_app/session.py')
        locker = payload_read_text(base.TARGET / 'usr/local/libexec/labwc-admin-action-worker')
        function = next(node for node in ast.parse(app).body
                        if isinstance(node, ast.FunctionDef) and node.name == '_session_unit')
        namespace = {'re': re, 'uuid': uuid, 'fail': self.fail}
        exec(compile(ast.Module(body=[function], type_ignores=[]), '<production-unit-name>', 'exec'), namespace)
        self.assertRegex(namespace['_session_unit']('labwc-bitwarden'),
                         r'^labwc-bitwarden-[0-9a-f]{32}\.service$')
        self.assertIn('_session_unit("labwc-bitwarden")', app)
        self.assertIn('labwc-power-lock-', locker)
        self.assertIn('--slice=app.slice', app)
        for prefix in ('labwc-bitwarden-', 'labwc-power-lock-'):
            self.assertTrue(payload_source_is_file(base.TARGET / USER / f'{prefix}.service.d/70-no-core.conf'))
        self.assertFalse(payload_source_exists(base.TARGET / USER / 'labwc-.service.d/70-no-core.conf'))

    def test_storage_and_socket_controls_are_independent(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = base.TARGET / SYSTEM / 'systemd-coredump.socket.d/60-poll-limit.conf'
            dest = Path(tmp) / 'socket.conf'; dest.write_bytes(payload_read_bytes(source))
            self.runner.shell('TMP_ENV_DIR=' + shlex.quote(tmp) + '\napply_systemd_resource_placeholders ' +
                              shlex.quote(str(dest)), override='''
SYSTEMD_DEFAULT_IOACCOUNTING_ENABLE=false
SYSTEMD_COREDUMP_POLL_LIMIT_INTERVAL_SEC=5
SYSTEMD_COREDUMP_POLL_LIMIT_BURST=32
''')
            self.assertEqual(active_lines(dest), ['[Socket]', 'PollLimitIntervalSec=5s', 'PollLimitBurst=32'])
            self.assertNotIn('TriggerLimitBurst=', payload_read_text(source))
            self.assertNotIn('MaxConnectionsPerSource=', payload_read_text(source))

    def test_optional_service_assets_run_through_existing_publishers(self):
        # Exercise production publishers, not complete network/package installers.
        # Only fetching is replaced by a local copy of the real asset.
        cases = (
            ('scripts/late/software.sh',
             ('software_fatal', 'software_validate_abs_path', 'software_stage_seed_asset'),
             'software_stage_seed_asset', 'apt-repo-local-', True),
            ('scripts/late/tailscale.sh',
             ('tailscale_fatal', 'tailscale_validate_abs_target_path', 'tailscale_stage_target_asset'),
             'tailscale_stage_target_asset', 'syncthing', True),
            ('scripts/late/btrfs-family.sh',
             ('btrfs_validate_shared_target_relpath', 'btrfs_stage_shared_target_asset'),
             'btrfs_stage_shared_target_asset', 'timeshift-', False),
            ('scripts/desktop/components.sh', (),
             'desktop_stage_role_asset', 'clamav-signature-update', False),
        )
        for script, functions, publisher, unit, repo_prefix in cases:
            with self.subTest(publisher=publisher), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / 'target'; target.mkdir()
                relative = f'etc/systemd/system/{unit}.service.d/60-resource-class.conf'
                text = payload_read_text(base.SEED / script)
                definitions = []
                for name in functions:
                    match = re.search(r'^' + re.escape(name) + r'\(\) [{(]\n.*?^[})]', text, re.M | re.S)
                    self.assertIsNotNone(match, f'{script}: {name}')
                    definitions.append(match.group())
                source = 'hooks/target/' + relative if repo_prefix else relative
                command = self.runner.staging(tmp) + '\n'.join(definitions)
                command += '\ntarget_root=$INSTALLER_TARGET_DIR\ntmp_env_dir=$TMP_ENV_DIR\nseed_base=fixture\n'
                command += 'BTRFS_SHARED_TARGET_ROOT=hooks/target\n'
                command += 'bootstrap_fetch_seed_file() { cp -- ' + shlex.quote(str(base.SEED)) + '/"$2" "$3"; }\n'
                command += f'{publisher} {shlex.quote(source)} /{relative} 0644\n'
                self.runner.shell(command)
                dest = target / relative
                self.assertEqual(payload_read_bytes(dest), payload_read_bytes(base.TARGET / relative))
                self.assertEqual(payload_source_stat(dest).st_mode & 0o777, 0o644)
                self.assertEqual(payload_source_stat(dest.parent).st_mode & 0o777, 0o755)

    def test_optional_system_service_policies_have_staging_owners(self):
        pairs = {
            'scripts/late/software.sh': 'etc/systemd/system/apt-repo-local-.service.d/60-resource-class.conf',
            'scripts/late/tailscale.sh': 'etc/systemd/system/syncthing.service.d/60-resource-class.conf',
            'scripts/late/btrfs-family.sh': 'etc/systemd/system/timeshift-.service.d/60-resource-class.conf',
            'scripts/desktop/components.sh':
                'etc/systemd/system/clamav-signature-update.service.d/60-resource-class.conf',
        }
        for script, relative in pairs.items():
            with self.subTest(script=script):
                self.assertTrue(payload_source_is_file(base.TARGET / relative))
                text = payload_read_text(base.SEED / script)
                self.assertIn(relative, text)
                # The references must be in a stage operation, not just in a comment.
                normalized = text.replace('\\\n', ' ')
                self.assertTrue(re.search(r'stage_[a-z_]*asset\s+[^\n]*' + re.escape(relative), normalized),
                                f'{script}: asset lacks a staging invocation')


if __name__ == '__main__':
    unittest.main()
