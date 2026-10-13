"""Template/map contracts; executable fixtures require the disposable test image."""
from __future__ import annotations

# Refuse host execution before importing runtime helpers or creating fixtures.
from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
_isolation_sys.path.insert(0, '/workspace/repository/tools')
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest

SEED = Path(__file__).resolve().parents[1]
TARGET = SEED / 'hooks/target'
COMPONENTS = SEED / 'scripts/desktop/components'
# Adjacent tokens must remain separate, particularly network optional blocks.
INSTALLER_TOKEN = re.compile(r'__INSTALLER_([A-Z0-9_]+?)__')
DESKTOP_CALL = re.compile(r'\s*desktop_render_(?:role|shared)_target_template(?:_deferred)?\s+')


def commands(text):
    """Read continued command records as data; do not source installer code."""
    lines = iter(enumerate(text.splitlines(), 1))
    for number, line in lines:
        record = line
        while record.rstrip().endswith('\\'):
            _, line = next(lines)
            record = record.rstrip()[:-1] + ' ' + line
        yield number, record


def template_keys(path):
    return set(INSTALLER_TOKEN.findall(path.read_text(encoding='utf-8')))


def shell_functions():
    result = {}
    for path in (SEED / 'scripts').rglob('*.sh*'):
        text = path.read_text(encoding='utf-8')
        definitions = list(re.finditer(r'^([a-z][a-z0-9_]*)\(\)\s*[{(]', text, re.M))
        for index, definition in enumerate(definitions):
            end = definitions[index + 1].start() if index + 1 < len(definitions) else len(text)
            result[definition[1]] = text[definition.start():end]
    return result


def declared_map_keys(functions, name, seen=None):
    """Inspect literal records, fixed loop inventories and composed map calls."""
    seen = set() if seen is None else seen
    if name in seen:
        return set()
    seen.add(name)
    text = functions[name]
    keys = set(re.findall(r'\b([A-Z][A-Z0-9_]+)=', text))
    keys.update(re.findall(r'write_shell_config_var ([A-Z][A-Z0-9_]+)', text))
    keys.update(re.findall(r'^\s+(PROXY3_[A-Z0-9_]+)\s+"', text, re.M))
    for inventory in re.findall(r'for (?:name|var_name) in\s+(.+?)\n\s*do\b', text, re.S):
        keys.update(re.findall(r'\b[A-Z][A-Z0-9_]+\b', inventory))
    if name == 'app_veth_identity_placeholder_map':
        keys.update(re.findall(r'values\["(APP_VETH_[A-Z0-9_]+)"\]', text))
        keys.update(re.findall(r'^\s+(APP_VETH_[A-Z0-9_]+)\s+"', text, re.M))
    for child in functions:
        if child != name and child.endswith('placeholder_map') and re.search(r'\b' + child + r'\b', text):
            keys.update(declared_map_keys(functions, child, seen))
    return keys


class PlaceholderDetectionTests(unittest.TestCase):
    def inspect(self, directory, path):
        program = '''set -eu
. "$1"
installer_fatal() { printf '%s\\n' "$*" >&2; return 1; }
installer_assert_no_unresolved_installer_placeholders "$2" fixture-template
'''
        return subprocess.run(
            ['/bin/sh', '-eu', '-c', program, 'placeholder-fixture',
             str(SEED / 'scripts/common/modules/files-logging.sh'), str(path)],
            env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'HOME': str(directory)},
            capture_output=True, text=True, encoding='utf-8', timeout=5,
        )

    def test_runtime_prefix_guard_is_accepted_without_rewriting_it(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'session'
            payload = (TARGET / 'usr/local/libexec/labwc-proxy-session').read_bytes()
            path.write_bytes(payload)
            self.assertIn(b'b"__INSTALLER_"', payload)
            result = self.inspect(directory, path)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(path.read_bytes(), payload)

    def test_named_and_malformed_markers_are_rejected_with_their_names(self):
        for token in ('__INSTALLER_ACCOUNT_USERNAME__', '__INSTALLER_MISSING__',
                      '__INSTALLER_ACCOUNT_USERNAME', '__INSTALLER_bad_name__'):
            with self.subTest(token=token), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'config'
                path.write_text('value=' + token + '\n', encoding='utf-8')
                result = self.inspect(directory, path)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(token, result.stderr)
                self.assertNotIn('unknown placeholder', result.stderr)

    def test_missing_input_is_an_error(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.inspect(directory, Path(directory) / 'missing')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('cannot inspect installer placeholders', result.stderr)


class TemplateMapContracts(unittest.TestCase):
    def test_selected_network_security_and_storage_maps_cover_their_assets(self):
        functions = shell_functions()
        contracts = {
            'etc/app-veth.json.tmpl': 'app_veth_placeholder_map',
            'etc/apparmor.d/app-veth.tmpl': 'app_veth_identity_placeholder_map',
            'etc/apparmor.d/local/abstractions/desktop-user-media.tmpl': 'apparmor_document_media_placeholder_map',
            'etc/NetworkManager/conf.d/70-app-veth.conf.tmpl': 'app_veth_identity_placeholder_map',
            'etc/dnsmasq-app-veth.conf.tmpl': 'app_veth_dns_placeholder_map',
            'etc/systemd/resolved.conf.d/60-app-veth.conf.tmpl': 'app_veth_dns_placeholder_map',
            'etc/stubby/stubby.yml.tmpl': 'app_veth_dns_placeholder_map',
            'etc/nftables/policy.conf.tmpl': 'nftables_default_placeholder_map',
            'etc/nftables/README.md.tmpl': 'nftables_interface_placeholder_map',
            'etc/fail2ban/jail.d/10-sshd.local.tmpl': 'fail2ban_jail_placeholder_map',
            'etc/default/grub.d/07-display.cfg.tmpl': 'grub_display_placeholder_map',
            'etc/default/grub.d/50-os-prober.cfg.tmpl': 'grub_os_prober_placeholder_map',
            'etc/secure-boot.conf.tmpl': 'secure_boot_config_placeholder_map',
            'etc/swap-fallback.conf.tmpl': 'swap_fallback_placeholder_map',
            'etc/timeshift/timeshift.json.tmpl': 'timeshift_placeholder_map',
            'etc/dbus-1/system-local.conf.tmpl': 'dbus_broker_placeholder_map',
        }
        for path in (TARGET / 'etc/systemd').glob('**/dbus-broker.*/*.tmpl'):
            contracts[path.relative_to(TARGET).as_posix()] = 'dbus_broker_placeholder_map'
        for path in (TARGET / 'etc/nftables/profiles').glob('*.tmpl'):
            contracts[path.relative_to(TARGET).as_posix()] = 'nftables_app_veth_profile_placeholder_map'
        # Read the actual production case table instead of duplicating it.
        selector = functions['stage_target_nftables_service_assets']
        selected = {}
        for names, provider in re.findall(r'([a-z*-]+(?:\|[a-z-]+)*)\) placeholder_map=([a-z_]+)', selector):
            selected.update((name, provider) for name in names.split('|'))
        self.assertIn('*', selected)
        for path in (TARGET / 'etc/nftables/services').glob('*.tmpl'):
            name = path.name.removesuffix('.yml.tmpl')
            contracts[path.relative_to(TARGET).as_posix()] = selected.get(name, selected['*'])
        logging = set(re.findall(r'^(LOG_[A-Z0-9_]+)=',
                                (SEED / 'hosts/logging/observability.env').read_text(), re.M))
        for path in (TARGET / 'etc/labwc/3proxy').glob('*.tmpl'):
            contracts[path.relative_to(TARGET).as_posix()] = 'proxy3_placeholder_map'
        for path in (TARGET / 'etc').glob('**/policies/managed/3proxy.json.tmpl'):
            contracts[path.relative_to(TARGET).as_posix()] = 'proxy3_placeholder_map'
        contracts['usr/lib/mullvad-browser/distribution/policies.json.tmpl'] = 'proxy3_placeholder_map'
        contracts['etc/app-veth.nft.tmpl'] = 'proxy3_placeholder_map'
        for relative, provider in contracts.items():
            with self.subTest(template=relative, provider=provider):
                self.assertFalse(template_keys(TARGET / relative) -
                                 declared_map_keys(functions, provider) - logging)
        network_input = SEED / 'scripts/late/templates/network-input.env.tmpl'
        self.assertFalse(template_keys(network_input) -
                         declared_map_keys(functions, 'network_input_placeholder_map'))

    def test_all_explicit_desktop_calls_cover_their_template_keys(self):
        count = 0
        deferred = {'LABWC_WORKSPACE_NAME_LINES', 'LABWC_WORKSPACE_KEYBIND_LINES',
                    'LABWC_RECORDING_KEYBIND_LINES'}
        for source in sorted(COMPONENTS.glob('*.sh*')):
            text = source.read_text(encoding='utf-8')
            for line, record in commands(text):
                if not DESKTOP_CALL.match(record):
                    continue
                args = shlex.split(record)
                if '$' in args[1]:
                    continue  # Enumerated by the dynamic map contract below.
                path = TARGET / args[1]
                if not path.is_file():
                    path = path.with_name(path.name + '.tmpl')
                with self.subTest(source=source.name, line=line, template=args[1]):
                    keys = {arg for arg in args[4:] if re.fullmatch(r'[A-Z][A-Z0-9_]*', arg)}
                    if args[0].endswith('_deferred'):
                        for key in deferred:
                            self.assertIn('"__INSTALLER_' + key + '__"', text)
                        keys |= deferred
                    self.assertFalse(template_keys(path) - keys)
                count += 1
        self.assertGreaterEqual(count, 40)

    def test_dynamic_desktop_maps_cover_every_selected_template(self):
        core = (COMPONENTS / 'core-renderers.sh.tmpl').read_text(encoding='utf-8')
        config_call = next(record for _, record in commands(core)
                           if record.strip().startswith('desktop_render_waybar_asset config '))
        keys = {arg for arg in shlex.split(config_call)[2:]
                if re.fullmatch(r'[A-Z][A-Z0-9_]*', arg)}
        for line in (SEED / 'scripts/desktop/waybar-geometry.tsv').read_text().splitlines():
            if not line or line.startswith('#'):
                continue
            key = line.split('\t', 1)[0]
            keys.update('LABWC_WAYBAR_' + kind + '_' + key for kind in ('INTERNAL', 'EXTERNAL'))
        for path in (TARGET / 'etc/skel-desktop/.config/waybar').glob('*.tmpl'):
            with self.subTest(template=str(path.relative_to(TARGET))):
                self.assertFalse(template_keys(path) - keys)
        for kind in (3, 4):
            path = TARGET / f'etc/skel-desktop/.config/gtk-{kind}.0/settings.ini.tmpl'
            self.assertFalse(template_keys(path) - {'LABWC_GTK_FONT_SIZE', 'LABWC_GTK_CURSOR_SIZE'})
        for path in (TARGET / 'etc/systemd/user').glob('pipewire*.d/20-no-greeter.conf.tmpl'):
            self.assertFalse(template_keys(path) - {'LABWC_GREETER_USER'})
        for path in (TARGET / 'etc/skel-desktop/.config/fuzzel').glob('*.tmpl'):
            self.assertFalse(template_keys(path))

    def test_shared_catalogs_supply_all_logging_and_theme_references(self):
        logging = set(re.findall(r'^(LOG_[A-Z0-9_]+)=',
                                (SEED / 'hosts/logging/observability.env').read_text(), re.M))
        themes = set()
        for path in (SEED / 'hosts/themes').glob('*.env'):
            themes.update(re.findall(r'^([A-Z][A-Z0-9_]+)=', path.read_text(), re.M))
        schema = {line.split('\t')[1] for line in
                  (SEED / 'hosts/themes/theme-schema.tsv').read_text().splitlines()
                  if line and not line.startswith('#')}
        for directory in ('hooks', 'scripts'):
            for path in (SEED / directory).rglob('*.tmpl'):
                text = path.read_text(encoding='utf-8')
                with self.subTest(template=str(path.relative_to(SEED))):
                    self.assertFalse({key for key in template_keys(path) if key.startswith('LOG_')} - logging)
                    keys = {key.removeprefix('TARGET_PATH_') for key in
                            re.findall(r'__THEME_([A-Z0-9_]+?)__', text)}
                    self.assertFalse(keys - themes)
                    self.assertFalse(keys - schema)


if __name__ == '__main__':
    unittest.main()
