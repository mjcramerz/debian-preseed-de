"""R4 native logging and real installer publication; no live services or logs."""
from __future__ import annotations
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import re
import runpy
import shlex
import shutil
import signal
import stat
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from payload_fixture import installed_script, logging_text, source_path

SEED = Path(__file__).resolve().parents[1]
ROOT = SEED.parents[1]
TARGET = SEED/'hooks/target'
CHECKER = runpy.run_path(str(ROOT/'tools/check_logging.py'))
VALUES = CHECKER['load_logging']()
loader = importlib.machinery.SourceFileLoader('native_logging_under_test', str(installed_script(TARGET/'usr/local/libexec/native-logging')))
spec = importlib.util.spec_from_loader(loader.name,loader)
native = importlib.util.module_from_spec(spec)
loader.exec_module(native)

class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.env=Path(self.tmp.name)/'logging.env'
        self.original=(SEED/'hosts/logging/observability.env').read_text()
    def validate(self,text, executable=None):
        self.env.write_text(text)
        return subprocess.run((executable or ['awk'])+['-f',str(SEED/'scripts/common/logging-validate.awk'),str(SEED/'hosts/logging/observability-schema.tsv'),str(self.env)],capture_output=True,text=True,timeout=10)
    def reject(self,text):
        result=self.validate(text);self.assertNotEqual(result.returncode,0,result.stdout)
        self.assertEqual(result.stdout,'','invalid catalog must not produce a partial map')
    def test_all_paths_have_consumers_and_templates_have_suffixes(self):
        result=CHECKER['check']();self.assertGreaterEqual(result['variables'],267);self.assertEqual(result['profiles'],10)
    def test_validator_matches_busybox(self):
        baseline=self.validate(self.original);self.assertEqual(baseline.returncode,0,baseline.stderr)
        if shutil.which('busybox'):
            other=self.validate(self.original,['busybox','awk']);self.assertEqual(other.returncode,0,other.stderr);self.assertEqual(other.stdout,baseline.stdout)
    def test_duplicate_rejected(self):self.reject(self.original+'\nLOG_ROOT="/var/log/managed"\n')
    def test_unknown_rejected(self):self.reject(self.original+'\nLOG_UNKNOWN="/var/log/managed/unknown"\n')
    def test_missing_rejected(self):self.reject(re.sub(r'^LOG_ROOT=.*\n','',self.original,flags=re.M))
    def test_shell_command_and_substitution_rejected(self):
        for value in ('$(id)','`id`','/var/log/managed;id'):
            with self.subTest(value=value):self.reject(self.original.replace('LOG_ROOT="/var/log/managed"',f'LOG_ROOT="{value}"'))
    def test_path_traversal_and_metacharacters_rejected(self):
        for value in ('/var/log/../managed','/var/log/managed//bad','/var/log/a b','/var/log/a*','relative'):
            with self.subTest(value=value):self.reject(self.original.replace('LOG_ROOT="/var/log/managed"',f'LOG_ROOT="{value}"'))
    def test_forward_reference_rejected(self):self.reject(self.original.replace('LOG_ROOT="/var/log/managed"','LOG_ROOT="${LOG_SECURITY_DIR}"'))
    def test_category_collision_rejected(self):self.reject(self.original.replace('LOG_APPS_DIR="${LOG_ROOT}/apps"','LOG_APPS_DIR="${LOG_ROOT}/security"'))
    def test_invalid_queue_and_mode_rejected(self):
        for key,value in [('LOG_RSYSLOG_QUEUE_HIGH','1'),('LOG_FILE_MODE','0666')]:
            with self.subTest(key=key):self.reject(re.sub(r'^'+key+r'="[^"]*"',key+'="'+value+'"',self.original,flags=re.M))
    def test_root_relocation_propagates(self):
        result=self.validate(self.original.replace('LOG_ROOT="/var/log/managed"','LOG_ROOT="/var/log/managed-relocated"'))
        self.assertEqual(result.returncode,0,result.stderr)
        changed=dict(line.split('=',1) for line in result.stdout.splitlines())
        for key,value in VALUES.items():
            if value.startswith('/var/log/managed'):
                self.assertEqual(changed[key],value.replace('/var/log/managed','/var/log/managed-relocated',1),key)
    def test_profiles_preserve_journal_settings_separately(self):
        for path in (SEED/'hosts/profiles').glob('*.env'):
            text=path.read_text();self.assertNotRegex(text,r'^LOG_',path.name)
            self.assertEqual(re.findall(r'^SYSTEMD_JOURNAL_VOLATILE_ENABLE="(true|false)"$',text,re.M),['false'])
    def test_all_ten_composite_profiles_consume_complete_catalog(self):
        from test_repository_integrity import records
        overrides={row['Name'] for row in records() if row['Group']=='profile'}
        root=Path(self.tmp.name)
        for profile in sorted((SEED/'hosts/profiles').glob('*.env')):
            logical=('override-' if profile.stem in overrides else '')+profile.stem
            dest=root/(profile.stem+'.env')
            command='\n'.join(('. '+shlex.quote(str(SEED/'scripts/common/lib.sh')),
                'installer_ensure_repo_env "$INSTALLER_SOURCE_ROOT"','installer_classes_cache_ensure',
                'installer_fetch_host_env "$INSTALLER_SOURCE_ROOT" '+shlex.quote(logical)+' '+shlex.quote(str(dest)),
                'set -a','. '+shlex.quote(str(dest)),'env | grep "^LOG_"'))
            result=subprocess.run(['/bin/sh','-eu','-c',command],text=True,capture_output=True,timeout=45,
                env={**os.environ,'INSTALLER_SOURCE_ROOT':str(SEED),'INSTALLER_SOURCE_LIBRARY':str(SEED/'scripts/common/source.sh'),
                    'INSTALLER_RUNTIME_DIR':str(root/'runtime'),'INSTALLER_CMDLINE':'','LC_ALL':'C'})
            with self.subTest(profile=profile.name):
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(dict(line.split('=',1) for line in result.stdout.splitlines()),VALUES)
                self.assertEqual(dest.stat().st_mode&0o777,0o600)

@unittest.skipUnless(os.geteuid()==0,'root-owned native configuration fixtures require root')
class NativeWriterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.mock=patch.object(native.pwd,'getpwnam',return_value=SimpleNamespace(pw_uid=0));self.mock.start();self.addCleanup(self.mock.stop)
        self.conf=self.root/'etc/clamav/freshclam.conf';self.conf.parent.mkdir(parents=True)
        self.raw=b'DatabaseMirror database.clamav.net\nUpdateLogFile /var/log/clamav/freshclam.log\n'
        self.conf.write_bytes(self.raw);self.conf.chmod(0o640)
    def configure(self):native.configure(self.root,only='freshclam')
    def test_only_logging_keys_changed_and_native_rotation_enabled(self):
        self.configure();text=self.conf.read_text();self.assertIn('DatabaseMirror database.clamav.net',text)
        self.assertIn('UpdateLogFile '+VALUES['LOG_FRESHCLAM_FILE'],text)
        self.assertIn('LogRotate yes',text);self.assertIn('LogSyslog no',text)
        self.assertLess(text.index('LogFileMaxSize'),text.index('LogRotate'))
        self.assertEqual(self.conf.stat().st_mode&0o777,0o640)
    def test_idempotence_and_read_only_verification(self):
        self.configure();first=self.conf.stat();data=self.conf.read_bytes();self.configure()
        self.assertEqual(self.conf.stat().st_ino,first.st_ino);self.assertEqual(self.conf.read_bytes(),data)
        native.configure(self.root,only='freshclam',check=True)
    def test_check_never_modifies_unconfigured_file(self):
        with self.assertRaises(native.ConfigError):native.configure(self.root,only='freshclam',check=True)
        self.assertEqual(self.conf.read_bytes(),self.raw)
    def test_safe_package_modes_preserved(self):
        for mode in (0o400,0o440,0o444,0o600,0o640,0o644):
            self.conf.write_bytes(self.raw);self.conf.chmod(mode);self.configure();self.assertEqual(self.conf.stat().st_mode&0o777,mode)
    def test_symlink_config_rejected(self):
        saved=self.conf.with_name('saved');self.conf.rename(saved);self.conf.symlink_to(saved)
        with self.assertRaises(OSError):self.configure()
        self.assertEqual(saved.read_bytes(),self.raw)
    def test_hardlink_rejected(self):
        os.link(self.conf,self.conf.with_name('other'))
        with self.assertRaises(native.ConfigError):self.configure()
    def test_fifo_rejected_without_blocking(self):
        self.conf.unlink();os.mkfifo(self.conf,0o600)
        old=signal.signal(signal.SIGALRM,lambda *_: (_ for _ in ()).throw(AssertionError('FIFO read blocked')))
        signal.alarm(2)
        try:
            with self.assertRaises(native.ConfigError):self.configure()
        finally:signal.alarm(0);signal.signal(signal.SIGALRM,old)
    def test_writable_parent_rejected(self):
        self.conf.parent.chmod(0o777)
        with self.assertRaises(native.ConfigError):self.configure()
    def test_world_writable_file_rejected(self):
        self.conf.chmod(0o666)
        with self.assertRaises(native.ConfigError):self.configure()
    def test_nul_oversize_and_non_utf8_rejected(self):
        for raw in (b'\0',b'\xff',b'x'*(2*1024*1024+1)):
            self.conf.write_bytes(raw)
            with self.assertRaises((native.ConfigError,UnicodeError)):self.configure()
    def test_bad_markers_rejected(self):
        for raw in (native.BEGIN+'\nOtherSetting yes\n'+native.END, native.END, native.BEGIN):
            with self.assertRaises(native.ConfigError):native.render('freshclam',raw.encode())
    def test_compound_chkrootkit_assignment_rejected(self):
        for raw in ('LOG_DIR=/tmp; echo dangerous\n','if true; then LOG_DIR=/tmp; fi\n',' LOG_DIR=/tmp\n'):
            with self.assertRaises(native.ConfigError):native.render('chkrootkit',raw.encode())
    def test_prepare_all_before_publication(self):
        bad=self.root/'etc/chkrootkit/chkrootkit.conf';bad.parent.mkdir(parents=True);bad.write_text('LOG_DIR=/tmp; echo no\n');bad.chmod(0o640)
        with self.assertRaises(native.ConfigError):native.configure(self.root)
        self.assertEqual(self.conf.read_bytes(),self.raw)
    def test_failure_after_replace_rolls_back_attempted_file(self):
        original=native.publish;calls=[]
        def failure(fd,name,data,info):
            calls.append(name);original(fd,name,data,info)
            if len(calls)==1:raise OSError('injected directory fsync failure after rename')
        with patch.object(native,'publish',side_effect=failure):
            with self.assertRaises(OSError):self.configure()
        self.assertEqual(self.conf.read_bytes(),self.raw);self.assertEqual(len(calls),2)
    def test_second_publication_failure_restores_both_files(self):
        other=self.root/'etc/clamav/clamd.conf';raw=b'LogFile /var/log/clamav/clamav.log\n';other.write_bytes(raw);other.chmod(0o640)
        original=native.publish;calls=[]
        def fail(fd,name,data,info):
            calls.append(name);original(fd,name,data,info)
            if len(calls)==2:raise OSError('injected second publication failure')
        with patch.object(native,'publish',side_effect=fail):
            with self.assertRaises(OSError):native.configure(self.root)
        self.assertEqual(self.conf.read_bytes(),self.raw);self.assertEqual(other.read_bytes(),raw)
    def test_existing_native_output_symlink_rejected(self):
        log=self.root/VALUES['LOG_FRESHCLAM_FILE'].lstrip('/');log.parent.mkdir(parents=True);log.symlink_to(self.conf)
        with self.assertRaises(native.ConfigError):self.configure()
        self.assertEqual(self.conf.read_bytes(),self.raw)
    def test_existing_journal_and_mount_files_untouched(self):
        journal=self.root/'var/log/journal/old/system.journal';journal.parent.mkdir(parents=True);journal.write_bytes(b'old journal')
        fstab=self.root/'etc/fstab';fstab.write_bytes(b'old mounts');self.configure()
        self.assertEqual(journal.read_bytes(),b'old journal');self.assertEqual(fstab.read_bytes(),b'old mounts')
    def test_retirement_exact_files_is_idempotent(self):
        entries=json.loads((SEED/'tests/fixtures/logging-r3-obsolete.json').read_text())
        for absolute,text in entries.items():
            path=self.root/absolute.lstrip('/');path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text);path.chmod(0o644)
        native.retire_r3(self.root);native.retire_r3(self.root)
        for absolute in entries:self.assertFalse((self.root/absolute.lstrip('/')).exists())
    def test_retirement_preserves_modified_file_and_peer(self):
        entries=json.loads((SEED/'tests/fixtures/logging-r3-obsolete.json').read_text())
        for absolute,text in entries.items():
            path=self.root/absolute.lstrip('/');path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text);path.chmod(0o644)
        absolute=next(iter(entries));path=self.root/absolute.lstrip('/');path.write_text(path.read_text()+'# administrator\n')
        with self.assertRaises(native.ConfigError):native.retire_r3(self.root)
        self.assertTrue(all((self.root/p.lstrip('/')).exists() for p in entries))

class ActualPublisherTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.source=self.root/'source';self.source.mkdir()
        for rel in ('scripts/common/logging.sh','scripts/common/logging-validate.awk','scripts/common/logging-render.awk','hosts/logging/observability.env','hosts/logging/observability-schema.tsv'):
            dest=self.source/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(SEED/rel,dest)
        self.asset=self.source/'hooks/target/etc/example.conf.tmpl';self.asset.parent.mkdir(parents=True);self.asset.write_text('log=__INSTALLER_LOG_ADB_FILE__\n')
        self.dest=self.root/'installed.conf';self.dest.write_bytes(b'old config\n');self.dest.chmod(0o640)
    def run_publish(self,prelude=''):
        code='. '+shlex.quote(str(SEED/'scripts/common/lib.sh'))+'\n'+prelude+'\ninstaller_fetch_seed_path "$SOURCE" hooks/target/etc/example.conf "$OUTPUT" 0640'
        return subprocess.run(['/bin/sh','-eu','-c',code],capture_output=True,text=True,timeout=20,
            env={**os.environ,'SOURCE':str(self.source),'OUTPUT':str(self.dest),'INSTALLER_SOURCE_ROOT':str(self.source),
                'INSTALLER_SOURCE_LIBRARY':str(SEED/'scripts/common/source.sh'),'INSTALLER_RUNTIME_DIR':str(self.root/'runtime'),'INSTALLER_CMDLINE':''})
    def test_atomic_rendered_publication_preserves_source_and_mode(self):
        raw=self.asset.read_bytes();result=self.run_publish();self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(self.dest.read_text(),'log='+VALUES['LOG_ADB_FILE']+'\n');self.assertEqual(self.dest.stat().st_mode&0o777,0o640)
        self.assertEqual(self.asset.read_bytes(),raw);self.assertFalse(list(self.root.glob('installed.conf.*')))
    def test_unknown_token_never_replaces_destination(self):
        self.asset.write_text('__INSTALLER_LOG_UNKNOWN__\n');result=self.run_publish();self.assertNotEqual(result.returncode,0)
        self.assertEqual(self.dest.read_bytes(),b'old config\n');self.assertFalse(list(self.root.glob('installed.conf.*')))
    def test_bad_catalog_never_replaces_destination(self):
        path=self.source/'hosts/logging/observability.env';path.write_text(path.read_text()+'LOG_ROOT="/tmp"\n')
        result=self.run_publish();self.assertNotEqual(result.returncode,0);self.assertEqual(self.dest.read_bytes(),b'old config\n')
    def test_ambiguous_plain_and_template_rejected(self):
        self.asset.with_suffix('').write_text('plain\n');result=self.run_publish();self.assertNotEqual(result.returncode,0);self.assertEqual(self.dest.read_bytes(),b'old config\n')
    def test_existence_probe_does_not_poison_source_cache(self):
        result=self.run_publish('installer_load_source_library "$SOURCE"\nsource_exists "$SOURCE" hooks/target/etc/example.conf\nsource_exists "$SOURCE" hooks/target/etc/example.conf')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(self.dest.read_text(),'log='+VALUES['LOG_ADB_FILE']+'\n')
        self.assertFalse(list((self.root/'runtime').rglob('hooks/target/etc/example.conf')))
    def test_symlink_source_rejected(self):
        self.asset.unlink();self.asset.symlink_to(self.dest);result=self.run_publish();self.assertNotEqual(result.returncode,0);self.assertEqual(self.dest.read_bytes(),b'old config\n')

class NativeWiringTests(unittest.TestCase):
    def test_adb_thunar_and_debugsys_categories(self):
        self.assertTrue(VALUES['LOG_ADB_FILE'].startswith(VALUES['LOG_SYSTEM_DIR']+'/'))
        self.assertTrue(VALUES['LOG_THUNAR_FILE'].startswith(VALUES['LOG_DESKTOP_DIR']+'/'))
        for rel in ('usr/local/libexec/debugsys.py','etc/systemd/system/debugsys-boot-report.service'):
            text=logging_text(source_path(TARGET/rel).read_text());self.assertIn(VALUES['LOG_DEBUGSYS_DIR'],text);self.assertNotIn('/var/log/debugsys',text)
    def test_native_clamav_parent_is_not_collector_writable_destination(self):
        from test_managed_logging_r3 import layout
        for path in layout.PROTECTED_FILES:self.assertFalse(path.startswith(VALUES['LOG_CLAMAV_DIR']+'/'),path)
    def test_crowdsec_native_overlays_have_correct_distinct_rotation_keys(self):
        engine=logging_text(source_path(TARGET/'etc/crowdsec/config.yaml.local').read_text())
        bouncer=logging_text(source_path(TARGET/'etc/crowdsec/bouncers/crowdsec-firewall-bouncer.yaml.local').read_text())
        self.assertIn('log_max_files:',engine);self.assertNotIn('log_max_backups:',engine)
        self.assertIn('log_max_backups:',bouncer);self.assertNotIn('log_max_files:',bouncer)
        self.assertIn(VALUES['LOG_CROWDSEC_DIR'],engine);self.assertIn(VALUES['LOG_CROWDSEC_DIR'],bouncer)
    def test_native_configure_staged_before_check_and_early_crowdsec_use(self):
        text=(SEED/'scripts/late/crowdsec.sh').read_text()
        self.assertLess(text.index('native-logging --preflight'),text.index('# Native logging must be in place'))
        for unit,kind in [('clamav-freshclam','freshclam'),('clamav-daemon','clamd')]:
            text=logging_text(source_path(TARGET/f'etc/systemd/system/{unit}.service.d/40-logging.conf').read_text())
            self.assertIn('native-logging --check '+kind,text);self.assertIn('ReadWritePaths=',text)

if __name__=='__main__':unittest.main()
