"""Actual source/rendering, publication safety and child-lifecycle regressions.

No target reboot or Wayland compositor is simulated as live acceptance.
"""
from __future__ import annotations
import contextlib
import io
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock
from payload_fixture import logging_text, read_text
from waybar_fixture import FORKY, TARGET, profiles, rendered_assets, style

class SourceLayout(unittest.TestCase):
    def test_native_persistent_sources_exist(self):
        for name in ('etc/syncthing/service.conf.tmpl','etc/default/tailscaled.tmpl',
                     'etc/system-runtime.conf.tmpl','etc/secure-boot.conf.tmpl',
                     'etc/chatgpt/package-policy.conf','etc/codex/app-server.env',
                     'etc/default/grub-profiles.tmpl','etc/grub.d/40_custom.tmpl',
                     'etc/fstab.tmpl','etc/crypttab.tmpl','etc/network/host.conf.tmpl'):
            self.assertTrue((TARGET/name).is_file(),name)
    def test_install_only_assets_are_outside_persistent_tree(self):
        forbidden=('firstboot.service','secondboot.service','crowdsec-firstboot',
                   'tailscale-bootstrap.service','tailscale-up','tpm2-enroll.sh',
                   'ssh-install.py','ssh-install-askpass','bootstrap.env')
        for p in TARGET.rglob('*'):
            if p.is_file(): self.assertNotIn(p.name.removesuffix('.tmpl'),forbidden,str(p))
        self.assertTrue((FORKY/'scripts/firstboot/assets/etc/systemd/system/firstboot.service').is_file())
        self.assertTrue((FORKY/'scripts/late/ssh/clone.conf.tmpl').is_file())
    def test_observability_source_and_consumers(self):
        self.assertTrue((FORKY/'hosts/logging/observability.env').is_file())
        self.assertFalse((FORKY/'hosts/installer/logging.env').exists())
        for folder in ('scripts','hosts','hooks'):
            for p in (FORKY/folder).rglob('*'):
                if p.is_file() and p.suffix != '.pyc':
                    data=p.read_bytes()
                    if b'\0' not in data:
                        self.assertNotIn(b'hosts/installer/logging.env',data,str(p))
    def test_power_path_has_no_journal_export(self):
        for name in ('power-log.service.tmpl','power-log-capture.service.tmpl'):
            self.assertFalse((TARGET/'etc/systemd/system'/name).exists())
        worker=read_text(TARGET/'usr/local/libexec/labwc-admin-action-worker')
        self.assertNotIn('journalctl',worker)
        self.assertNotIn('power-log-capture',worker)
        unit=read_text(TARGET/'etc/systemd/system/labwc-admin-action@.service')
        self.assertIn('StandardOutput=append:/var/lib/journal/power/action-%i.log',unit)
        self.assertIn('StandardError=inherit',unit)
        self.assertIn('sync="on"',read_text(TARGET/'etc/rsyslog.d/19-power.conf'))
    def test_firstboot_import_is_after_real_mounts(self):
        unit=read_text(FORKY/'scripts/firstboot/assets/etc/systemd/system/firstboot.service')
        self.assertIn('After=local-fs.target systemd-tmpfiles-setup.service',unit)
        self.assertIn('/var/lib/firstboot/lib/import-initramfs.py',read_text(FORKY/'scripts/firstboot/02-collect.sh'))
        cleanup=read_text(FORKY/'scripts/firstboot/assets/var/lib/firstboot/bin/secondboot-cleanup')
        for name in ('/var/lib/firstboot/lib','/etc/apparmor.d/firstboot','/run/initramfs-health'):
            self.assertIn(name,cleanup)

class OutputGeometry(unittest.TestCase):
    def test_all_profiles_have_complete_independent_literal_sizing(self):
        keys=[line.split('\t')[0] for line in (FORKY/'scripts/desktop/waybar-geometry.tsv').read_text().splitlines() if line and not line.startswith('#')]
        self.assertEqual(len(profiles()),10)
        for p in profiles():
            assignments=dict(re.findall(r'^(LABWC_WAYBAR_[A-Z0-9_]+)="([^"\n]*)"$',p.read_text(),re.M))
            for cls in ('INTERNAL','EXTERNAL'):
                for key in keys:
                    name='LABWC_WAYBAR_'+cls+'_'+key
                    self.assertIn(name,assignments)
                    self.assertNotIn('$',assignments[name])
            for key in keys:self.assertNotIn('LABWC_WAYBAR_'+key,assignments)
    def test_rendered_native_configs_and_popup_styles_for_both_classes(self):
        for p in profiles():
            assets=rendered_assets(p)
            self.assertEqual([bar['name'] for bar in json.loads(assets['config'])],
                             ['internal','external'])
            sheet=assets['style.css']
            self.assertNotIn('@import',sheet)
            for cls in ('internal','external'):
                self.assertIn('window#waybar.'+cls,sheet)
            self.assertIn('tooltip label {',sheet)
            self.assertIn('menu',sheet)
            self.assertNotIn('__INSTALLER_',sheet)
            self.assertNotIn('__THEME_',sheet)
    def test_shared_css_contains_no_fixed_length_geometry(self):
        common=(TARGET/'etc/skel-desktop/.config/waybar/style.css.tmpl').read_text()
        self.assertNotRegex(common,r'(?<![A-Za-z])\d+(?:\.\d+)?(?:px|pt|em|rem)\b')
        self.assertIn('LABWC_WAYBAR_INTERNAL_',common)
        self.assertIn('LABWC_WAYBAR_EXTERNAL_',common)
        self.assertNotRegex(common, r'window#waybar\.(internal|external) (?:menu|tooltip)')
    def test_distinct_sizes_survive_real_render_without_cross_class_inheritance(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'profile.env';text=profiles()[0].read_text()
            for cls,height,font in (('INTERNAL',39,13),('EXTERNAL',61,23)):
                for key,value in (('HEIGHT',height),('FONT_SIZE',font)):
                    text=re.sub(r'^LABWC_WAYBAR_'+cls+'_'+key+r'="[^"]*"$',f'LABWC_WAYBAR_{cls}_{key}="{value}"',text,flags=re.M)
            p.write_text(text);assets=rendered_assets(p)
            bars={bar['name']:bar for bar in json.loads(assets['config'])}
            for cls,height,font in (('internal',39,13),('external',61,23)):
                self.assertEqual(bars[cls]['height'],height)
                self.assertRegex(assets['style.css'],rf'window#waybar\.{cls}[^{{]*\{{[^}}]*font-size: {font}px;')
    def test_detached_native_popup_divergence_is_rejected_not_silently_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'profile.env'
            p.write_text(re.sub(r'^LABWC_WAYBAR_EXTERNAL_TOOLTIP_FONT_SIZE="[^"]*"$',
                               'LABWC_WAYBAR_EXTERNAL_TOOLTIP_FONT_SIZE="21"',profiles()[0].read_text(),flags=re.M))
            with self.assertRaises(subprocess.CalledProcessError): rendered_assets(p)
    def test_invalid_geometry_is_rejected_before_publishing(self):
        for value in ('-1','012','20000','1; touch /tmp/unsafe','12px',''):
            with self.subTest(value=value),tempfile.TemporaryDirectory() as tmp:
                p=Path(tmp)/'profile.env'
                p.write_text(re.sub(r'^LABWC_WAYBAR_INTERNAL_HEIGHT="[^"]*"$',f'LABWC_WAYBAR_INTERNAL_HEIGHT="{value}"',profiles()[0].read_text(),flags=re.M))
                with self.assertRaises(subprocess.CalledProcessError):rendered_assets(p)
    def test_hotplug_refresh_reuses_native_service_lifecycle(self):
        service=read_text(TARGET/'etc/skel-desktop/.config/systemd/user/waybar.service')
        self.assertIn('ExecStart=/usr/bin/waybar -c %h/.config/waybar/config -s %h/.config/waybar/style.css',service)
        self.assertNotIn('labwc-panel-run',service)
        panel=read_text(TARGET/'usr/local/libexec/labwc-panel-run')
        self.assertNotIn('companion',panel)
        watcher=read_text(TARGET/'usr/local/libexec/labwc-output-watch')
        refresh=watcher.split('sub refresh_waybar',1)[1].split('\nsub ',1)[0]
        self.assertNotIn("'restart'",refresh)
        self.assertIn("'start', 'waybar.service'",refresh)

@unittest.skipUnless(os.geteuid()==0,'root-owned publication contract')
class InitramfsImport(unittest.TestCase):
    def setUp(self):
        # The imported entry point deliberately sets a private process umask.
        # Restore it after each in-process test, including failing imports.
        previous_umask = os.umask(0o077)
        os.umask(previous_umask)
        self.addCleanup(os.umask, previous_umask)
        self.mod=types.ModuleType('initramfs_fixture')
        text=logging_text((FORKY/'scripts/firstboot/import-initramfs.py.tmpl').read_text())
        exec(compile(text,'initramfs_fixture','exec'),self.mod.__dict__)
        self.tmp=tempfile.TemporaryDirectory(prefix='initramfs-test-',dir='/var/lib');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.src=self.root/'source';self.src.mkdir(mode=0o700)
        self.dest=self.root/'destination'
        self.mod.SOURCES=(self.src,);self.mod.DESTINATION=self.dest;self.mod.MAX_BYTES=4096
        for name in self.mod.NAMES:
            p=self.src/name;p.write_bytes(b'initramfs fixture\n');p.chmod(0o600)
    def execute(self):
        with contextlib.redirect_stdout(io.StringIO()):return self.mod.main()
    def test_import_is_complete_bounded_and_private(self):
        self.assertEqual(self.execute(),0)
        self.assertEqual({p.name for p in self.dest.iterdir()},set(self.mod.NAMES))
        for p in self.dest.iterdir():
            self.assertEqual(p.read_bytes(),(self.src/p.name).read_bytes())
            self.assertEqual(p.stat().st_mode & 0o777,0o600)
        self.assertEqual(self.dest.stat().st_mode & 0o777,0o700)
        self.assertEqual(self.execute(),0)
    def test_source_symlink_is_not_followed(self):
        name=self.src/self.mod.NAMES[0];name.unlink();name.symlink_to(self.src/self.mod.NAMES[1])
        with self.assertRaises(OSError):self.execute()
    def test_hardlinked_source_is_rejected(self):
        os.link(self.src/self.mod.NAMES[0],self.root/'alias')
        with self.assertRaises(PermissionError):self.execute()
    def test_writable_ancestor_is_rejected(self):
        self.src.chmod(0o777)
        with self.assertRaises(PermissionError):self.execute()
    def test_public_source_is_rejected(self):
        (self.src/self.mod.NAMES[0]).chmod(0o644)
        with self.assertRaises(PermissionError):self.execute()
    def test_oversize_and_empty_sources_are_rejected(self):
        for data in (b'',b'x'*4097):
            (self.src/self.mod.NAMES[0]).write_bytes(data)
            with self.assertRaises(ValueError):self.execute()
    def test_destination_symlink_is_rejected(self):
        self.dest.symlink_to(self.src,target_is_directory=True)
        with self.assertRaises(OSError):self.execute()
    def test_existing_foreign_link_is_preserved(self):
        self.dest.mkdir(mode=0o700);p=self.dest/self.mod.NAMES[0];p.symlink_to(self.src/self.mod.NAMES[1])
        with self.assertRaises(PermissionError):self.execute()
        self.assertTrue(p.is_symlink())
    def test_missing_and_ambiguous_spools_fail_closed(self):
        for sources in ((self.root/'missing',),(self.src,self.src)):
            self.mod.SOURCES=sources
            with self.assertRaises(FileNotFoundError):self.execute()
    def test_unprivileged_entry_is_rejected(self):
        with mock.patch.object(self.mod.os,'geteuid',return_value=1000),self.assertRaises(PermissionError):self.execute()
    def test_fifo_is_rejected_without_blocking(self):
        p=self.src/self.mod.NAMES[0];p.unlink();os.mkfifo(p,0o600)
        with self.assertRaises(PermissionError):self.execute()

class PanelLifecycle(unittest.TestCase):
    def command(self, child):
        code="import runpy,sys; m=runpy.run_path(sys.argv[1]); raise SystemExit(m['supervise']([sys.executable,'-c',sys.argv[2]],set()))"
        return [sys.executable,'-B','-c',code,str(TARGET/'usr/local/libexec/labwc-panel-run'),child]
    def run_supervisor(self, child):
        return subprocess.run(self.command(child),capture_output=True,text=True,timeout=12)
    def test_successful_dock_exit_preserves_status(self):
        result=self.run_supervisor('print("dock")')
        self.assertEqual(result.returncode,0);self.assertIn('dock',result.stdout)
    def test_failed_dock_exit_preserves_failure(self):
        self.assertEqual(self.run_supervisor('raise SystemExit(19)').returncode,19)
    def test_nonterminating_dock_is_killed_within_shutdown_budget(self):
        child='import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);print("ready",flush=True);time.sleep(60)'
        process=subprocess.Popen(self.command(child),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(),'ready')
            process.send_signal(signal.SIGTERM)
            process.communicate(timeout=8)
            self.assertEqual(process.returncode,247)  # supervise returns the child's -SIGKILL
        finally:
            if process.poll() is None: process.kill();process.communicate(timeout=2)
    def test_closed_pipe_is_not_confused_with_process_exit(self):
        child='import os,time;os.close(1);os.close(2);time.sleep(.3);raise SystemExit(13)'
        self.assertEqual(self.run_supervisor(child).returncode,13)

if __name__=='__main__':unittest.main()
