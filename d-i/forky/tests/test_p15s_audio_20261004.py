"""Native WirePlumber rule matching and profile-specific installer staging.

No audio service is started and no hardware or installed configuration is changed.
"""
import ctypes as C
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SEED = Path(__file__).resolve().parents[1]
TARGET = SEED / 'hooks/target'
CONFIG = TARGET / 'etc/wireplumber/wireplumber.conf.d'
CARD = 'alsa_card.pci-0000_00_1f.3-platform-skl_hda_dsp_generic'
NODE = 'alsa_output.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__'


class NativeRuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        parser = shutil.which('spa-json-dump')
        if not parser:
            raise unittest.SkipTest('packaged spa-json-dump required')
        try:
            cls.wp = C.CDLL('libwireplumber-0.5.so.0')
        except OSError as exc:
            raise unittest.SkipTest('packaged WirePlumber 0.5 library required: ' + str(exc))
        for name, result, args in (
            ('wp_spa_json_new_from_string', C.c_void_p, [C.c_char_p]),
            ('wp_properties_new_string', C.c_void_p, [C.c_char_p]),
            ('wp_json_utils_match_rules_update_properties', C.c_int, [C.c_void_p, C.c_void_p]),
            ('wp_properties_get', C.c_char_p, [C.c_void_p, C.c_char_p]),
            ('wp_properties_unref', None, [C.c_void_p]),
            ('wp_spa_json_unref', None, [C.c_void_p]),
        ):
            function = getattr(cls.wp, name)
            function.restype, function.argtypes = result, args
        cls.configs = []
        for name in ('20-audio-policy.conf', '30-p15s-audio.conf'):
            parsed = subprocess.run([parser], input=(CONFIG / name).read_bytes(),
                                    capture_output=True, check=True, timeout=5)
            cls.configs.append(json.loads(parsed.stdout))

    def apply(self, section, properties, keys):
        props = self.wp.wp_properties_new_string(json.dumps(properties).encode())
        self.assertTrue(props)
        try:
            for config in self.configs:
                rules = self.wp.wp_spa_json_new_from_string(json.dumps(config.get(section, [])).encode())
                self.assertTrue(rules)
                try:
                    self.wp.wp_json_utils_match_rules_update_properties(rules, props)
                finally:
                    self.wp.wp_spa_json_unref(rules)
            return {key: self.wp.wp_properties_get(props, key.encode()) for key in keys}
        finally:
            self.wp.wp_properties_unref(props)

    def test_speaker_has_higher_effective_priority_than_headphones(self):
        priorities = {}
        for name in ('Speaker', 'Headphones'):
            value = self.apply('monitor.alsa.rules', {'node.name': NODE + name + '__sink'},
                               ['priority.session'])['priority.session']
            self.assertIsNotNone(value, 'priority action was ignored for ' + name)
            priorities[name] = int(value)
        self.assertGreater(priorities['Speaker'], priorities['Headphones'])
        self.assertLessEqual(priorities['Speaker'], 1500)
        self.assertFalse(self.configs[0]['wireplumber.settings']['node.restore-default-targets'])
        self.assertFalse(self.configs[1]['wireplumber.settings']['device.restore-profile'])

    def test_shared_hdmi_disable_and_other_audio_nodes_keep_their_policy(self):
        hdmi = self.apply('monitor.alsa.rules', {'node.name': NODE + 'HDMI1__sink'}, ['node.disabled'])
        self.assertEqual(hdmi['node.disabled'], b'true')
        for node in ('alsa_output.usb-fixture.analog-stereo', 'alsa_input.fixture.HiFi__Mic1__source'):
            with self.subTest(node=node):
                result = self.apply('monitor.alsa.rules', {'node.name': node}, ['priority.session'])
                self.assertIsNone(result['priority.session'])

    def test_profile_hook_is_required_and_loads_before_the_event_source(self):
        config = self.configs[1]
        feature = 'hooks.device.p15s-speaker-profile'
        self.assertEqual(config['wireplumber.profiles']['main'][feature], 'required')
        self.assertEqual(config['wireplumber.components'], [{
            'name': 'p15s-speaker-profile.lua', 'type': 'script/lua', 'provides': feature}])
        self.assertNotIn('device.profile.priority.rules', config)


class ProfileEventTests(unittest.TestCase):
    def test_speaker_profile_selection_on_repeated_events_and_jack_changes(self):
        # Real Lua executes the production hook; WirePlumber events/params are
        # test doubles. No daemon, audio server, sockets or ALSA device is used.
        lua = shutil.which('lua5.5') or shutil.which('lua')
        if not lua:
            self.skipTest('packaged Lua interpreter required')
        script = TARGET / 'usr/share/wireplumber/scripts/p15s-speaker-profile.lua'
        harness = r'''
local hook
package.preload["common-utils"] = function ()
  return { parseParam = function (param) return param end }
end
Constraint = function (c) return c end
EventInterest = function (i) return i end
SimpleEventHook = function (h)
  h.register = function (self) hook = self end
  return h
end
dofile (arg[1])
assert (hook.before == "device/find-preferred-profile")
assert (hook.after == "device/find-stored-profile")
local card = "alsa_card.pci-0000_00_1f.3-platform-skl_hda_dsp_generic"
local profiles = {
  { index = 1, name = "HiFi (HDMI1, HDMI2, HDMI3, Mic1, Headphones)", available = "yes", priority = 9000 },
  { index = 2, name = "HiFi (HDMI1, HDMI2, HDMI3, Mic1, Speaker)", available = "unknown", priority = 8000 },
  { index = 3, name = "HiFi (Mic1, Mic2, Speaker)", available = "yes", priority = 8100 },
}
local function select (name, routes, previous)
  local device = { properties = { ["device.name"] = name } }
  function device:iterate_params (kind)
    local rows = kind == "EnumProfile" and profiles or routes
    local index = 0
    return function () index = index + 1; return rows[index] end
  end
  local event = { selected = previous }
  function event:get_data () return self.selected end
  function event:get_subject () return device end
  function event:set_data (_, value) self.selected = value end
  hook.execute (event)
  return event.selected
end
local routes = {
  { name = "[Out] Speaker", direction = "Output", available = "unknown", profiles = { 2, 3 } },
}
-- A real Speaker name with a different Mic/HDMI combination beats headphones.
assert (select (card, routes).index == 3)
assert (select (card, routes).index == 3) -- later EnumProfile change
profiles[3].available = "no"
assert (select (card, routes).index == 2) -- unknown built-in route is usable
assert (select ("alsa_card.usb-fixture", routes) == nil)
-- An explicit application/user choice remains authoritative.
assert (select (card, routes, profiles[1]).index == 1)
-- A real unavailable Speaker route cannot be revived by HDMI availability.
routes[1].available = "no"
assert (select (card, routes) == nil)
routes[1].available = "yes"
assert (select (card, routes).index == 2) -- jack removed
-- No profile/route association is published on some older UCM devices.
assert (select (card, {}).index == 2)
profiles[2].available = "no"
assert (select (card, {}) == nil)
print ("profile policy fixtures passed")
'''
        result = subprocess.run([lua, '-', str(script)], input=harness, capture_output=True,
                                text=True, encoding='utf-8', timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)


class AudioStagingTests(unittest.TestCase):
    def test_both_p15s_profiles_receive_the_fragment_and_flex_profiles_remove_it(self):
        source = (SEED / 'scripts/desktop/components/target-assets.sh').read_text()
        start = source.index('  for audio_dir in /etc/wireplumber/wireplumber.conf.d ')
        end = source.index('\n  desktop_render_gtk_settings', start)
        loop = source[start:end].replace('"/target$audio_dir/', '"$TEST_TARGET$audio_dir/')
        stage_start = source.rfind('  case "${requested_host_profile:', 0, start)
        loop = source[stage_start:start] + loop
        script = ('set -eu\ndesktop_stage_role_asset() {\n'
                  '  install -D -m "$3" "$TEST_SOURCE/$1" "$TEST_TARGET/$2"\n}\n' + loop)
        for profile in ('btrfs-de-p15s', 'btrfs-de-p15s-duo', 'btrfs-de-flex', 'btrfs-de-flex-duo'):
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                files = [root / prefix / 'wireplumber.conf.d/30-p15s-audio.conf' for prefix in (
                    'etc/wireplumber', 'etc/skel-desktop/.config/wireplumber')]
                for path in files:
                    path.parent.mkdir(parents=True)
                    path.write_text('old managed audio fragment\n')
                env = dict(os.environ, TEST_TARGET=str(root), TEST_SOURCE=str(TARGET),
                           requested_host_profile=profile)
                result = subprocess.run(['/bin/sh', '-c', script], env=env,
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                for path in files:
                    if 'p15s' in profile:
                        self.assertEqual(path.read_bytes(), (CONFIG / '30-p15s-audio.conf').read_bytes())
                        self.assertEqual(path.stat().st_mode & 0o777, 0o644)
                    else:
                        self.assertFalse(path.exists())
                policy = root / 'usr/share/wireplumber/scripts/p15s-speaker-profile.lua'
                if 'p15s' in profile:
                    self.assertEqual(policy.read_bytes(),
                                     (TARGET / 'usr/share/wireplumber/scripts/p15s-speaker-profile.lua').read_bytes())
                else:
                    self.assertFalse(policy.exists())


if __name__ == '__main__':
    unittest.main()
