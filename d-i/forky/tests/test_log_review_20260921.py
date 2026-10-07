"""Log-driven runtime contracts; no service, radio, GPU or power action is run."""
from __future__ import annotations
from payload_fixture import read_text as payload_read_text
from theme_fixture import render_theme_defaults, render_theme_bytes, theme_values
import re
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

from test_wlsunset import W
from test_session_reliability_20260921 import FootResults

FORKY = Path(__file__).resolve().parents[1]
TARGET = FORKY / 'hooks/target'
AA = TARGET / 'etc/apparmor.d'


def profile(file, name):
    found = re.search(r'^profile ' + re.escape(name) + r' .*?^}',
                      render_theme_defaults(payload_read_text(AA/file)), re.M | re.S)
    assert found, name
    return found.group()


class ColourServiceBoundary(unittest.TestCase):
    def test_unprivileged_colour_service_does_not_drop_host_bounding_set(self):
        for value in W.PROPERTIES:
            self.assertFalse(value.startswith(('CapabilityBoundingSet=', 'AmbientCapabilities=')), value)
        for value in ('NoNewPrivileges=yes', 'RestrictNamespaces=yes',
                      'RestrictAddressFamilies=AF_UNIX', 'SystemCallFilter=@system-service',
                      'MemoryDenyWriteExecute=yes', 'LimitCORE=0'):
            self.assertIn(value, W.PROPERTIES)

    def test_colour_service_retains_bounded_restart_and_compositor_lifetime(self):
        for value in ('Requisite=labwc-session.target', 'PartOf=labwc-session.target',
                      'After=labwc-session.target labwc-compositor.service', 'KillMode=control-group',
                      'TimeoutStartSec=10s', 'TimeoutStopSec=5s', 'Restart=always',
                      'RestartSec=10s', 'StartLimitIntervalSec=300s', 'StartLimitBurst=3'):
            self.assertIn(value, W.PROPERTIES)
        self.assertNotIn('NoNewPrivileges=no', W.PROPERTIES)
        self.assertNotIn('BindsTo=labwc-compositor.service', W.PROPERTIES)


class LoggedPermissions(unittest.TestCase):
    def test_waybar_import_probe_is_directory_read_only(self):
        source=profile('labwc-session', 'waybar')
        self.assertIn('/usr/local/lib/python3.14/dist-packages/ r,',source)
        self.assertNotIn('/usr/local/lib/python3.14/dist-packages/**',source)

    def test_monitoring_peers_are_read_only_not_attach(self):
        source=profile('desktop-utilities', 'desktop-launcher')
        for peer in ('labwc-swaybg','tomat','labwc-notifications'):
            lines=[line.strip() for line in source.splitlines() if 'peer='+peer+',' in line]
            self.assertEqual(lines,['ptrace (read) peer='+peer+','])

    def test_zram_setup_gets_only_io_pressure_sample(self):
        source=profile('system-wrappers','zram-device-setup')
        lines=[line.strip() for line in source.splitlines() if '/proc/pressure/' in line]
        self.assertEqual(lines,['/proc/pressure/io r,'])


class NativeMenuGeometry(unittest.TestCase):
    def test_all_menus_submenus_and_rows_have_the_requested_geometry(self):
        menu_count=item_count=0
        from waybar_fixture import rendered_assets
        assets = rendered_assets(FORKY/'hosts/profiles/btrfs-de.env')
        for name, text in assets.items():
            if not name.endswith('-menu.xml'): continue
            for obj in ET.fromstring(text).iter('object'):
                props={p.get('name'):p.text for p in obj.findall('property')}
                if obj.get('class')=='GtkMenu':
                    menu_count+=1
                    self.assertEqual(props.get('reserve-toggle-size'),'False')
                elif obj.get('class')=='GtkMenuItem':
                    item_count+=1
                    self.assertEqual(props.get('visible'),'True')
                    box=obj.find('./child/object[@class="GtkBox"]')
                    self.assertIsNotNone(box)
                    self.assertEqual(box.findtext('./property[@name="spacing"]'),'8')
                    self.assertEqual(box.findtext('./property[@name="orientation"]'),'horizontal')
                    for cls in ('GtkImage','GtkLabel'):
                        self.assertEqual(len(box.findall('./child/object[@class="'+cls+'"]')),1)
                elif obj.get('class')=='GtkImage':
                    self.assertTrue(props.get('icon-name','').endswith('-symbolic'))
                    self.assertEqual(props.get('pixel-size'),'18')
                    self.assertEqual(props.get('width-request'),'20')
                    self.assertEqual(props.get('use-fallback'),'True')
                elif obj.get('class')=='GtkLabel':
                    self.assertEqual(props.get('xalign'),'0')
                    self.assertEqual(props.get('hexpand'),'True')
        self.assertEqual((menu_count,item_count),(11,48))

    def test_installer_invokes_native_menu_validation_after_user_configuration(self):
        source=render_theme_defaults(payload_read_text(FORKY/'scripts/desktop/labwc.sh'))
        self.assertLess(source.index('  desktop_install_user_config'), source.index('  desktop_verify_native_menus'))
        verify=render_theme_defaults(payload_read_text(FORKY/'scripts/desktop/verify.sh'))
        for key in ('reserve-toggle-size','width-request','use-fallback','hexpand'):
            self.assertIn('"'+key+'"',verify)

    def test_workspaces_have_distinct_idle_hover_and_active_rules(self):
        source=render_theme_defaults(payload_read_text(TARGET/'etc/skel-desktop/.config/waybar/style.css.tmpl'))
        hover=re.search(r'#workspaces button:hover:not\(\.active\):not\(\.urgent\) \{([^}]+)',source).group(1)
        self.assertIn('background: ' + theme_values()['WAYBAR_BUTTON_WORKSPACES_HOVER_BACKGROUND_COLOR'] + ';',hover)
        self.assertNotIn('linear-gradient',hover)
        self.assertIn('border-color: ' + theme_values()['WAYBAR_BUTTON_WORKSPACES_HOVER_OUTLINE_COLOR'] + ';',hover)
        active=''.join(re.findall(r'#workspaces button.active(?:\:hover)? \{([^}]+)',source))
        self.assertIn('#workspaces button.active:hover {',source)
        self.assertIn('linear-gradient(135deg, ' + theme_values()['WAYBAR_BUTTON_WORKSPACES_ACTIVE_BACKGROUND_START_COLOR'] + ', ' + theme_values()['WAYBAR_BUTTON_WORKSPACES_ACTIVE_BACKGROUND_END_COLOR'] + ')',active)


class NetworkServiceContract(unittest.TestCase):
    def test_wpa_supplicant_has_host_radio_access_without_unrelated_privileges(self):
        source=render_theme_defaults(payload_read_text(TARGET/'etc/systemd/system/wpa_supplicant.service.d/override.conf'))
        settings=dict(line.split('=',1) for line in source.splitlines() if '=' in line and not line.startswith('#'))
        self.assertEqual(set(settings['CapabilityBoundingSet'].split()),{'CAP_CHOWN','CAP_DAC_READ_SEARCH','CAP_NET_ADMIN','CAP_NET_RAW'})
        self.assertEqual(settings['ProtectHome'],'read-only')
        self.assertEqual(settings['NoNewPrivileges'],'yes')
        self.assertEqual(settings['KillMode'],'control-group')
        self.assertEqual(set(settings['RestrictAddressFamilies'].split()),{'AF_UNIX','AF_NETLINK','AF_PACKET','AF_INET','AF_INET6'})
        self.assertNotIn('PrivateNetwork',settings)
        self.assertNotIn('PrivateDevices',settings)
        self.assertIn('GROUP=netdev',settings['ExecStart'])
        self.assertNotIn(' -m ',settings['ExecStart'])

    def test_packaged_clock_client_is_installed_enabled_and_egress_already_allows_ntp(self):
        packages=render_theme_defaults(payload_read_text(FORKY/'classes/class-select/role/desktop.cfg')).split()
        self.assertEqual(packages.count('systemd-timesyncd'),1)
        source=render_theme_defaults(payload_read_text(FORKY/'scripts/desktop/components.sh'))
        self.assertIn('desktop_enable_unit_if_available systemd-timesyncd.service system',source)
        self.assertIn('allow_ntp: true',render_theme_defaults(payload_read_text(TARGET/'etc/nftables/profiles/desktop.yml')))


class GenericExecBoundary(FootResults):
    def test_preparation_is_bounded_without_killing_long_running_apps(self):
        for args in (['/usr/bin/foot'],['/usr/bin/thunar']):
            command=self.command(args)
            self.assertIn('--property=TimeoutStartSec=10s',command)
            self.assertFalse(any(x.startswith('--property=RuntimeMaxSec=') for x in command))
            for required in ('--collect','--service-type=exec','--expand-environment=no',
                             '--property=ExitType=cgroup','--property=PartOf=labwc-session.target',
                             '--property=Requisite=labwc-session.target','--property=SendSIGKILL=yes'):
                self.assertIn(required,command)
