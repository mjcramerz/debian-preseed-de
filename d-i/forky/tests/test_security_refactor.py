#!/usr/bin/env python3
"""Regression coverage for the 2026-09-06 installer/browser security repair.

All network fixtures use loopback; no real vendor or bookmarked site is visited.
Crypto checks generate disposable keys and invoke actual GnuPG and Sequoia.
"""
from __future__ import annotations
import argparse
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import ssl
import stat
import subprocess
import tempfile
import unittest

from test_repository_transport import TransportFixture

SEED = Path(__file__).resolve().parents[1]
ROOT = SEED.parents[1]
TARGET = SEED / 'hooks/target'
LIB = SEED / 'scripts/common/lib.sh'
SOURCE = SEED / 'scripts/common/source.sh'
EXPORT = TARGET / 'usr/local/share/browser-imports'
FP = 'EB693B3035CD5710E231E123A4B469963BF863CC'
REPO = 'https://developer.download.nvidia.com/compute/cuda/repos/debian12/x86_64/'
KEYRING = '/etc/apt/keyrings/cuda-legacy-archive-key.asc'


def module(name, file):
    loader = importlib.machinery.SourceFileLoader(name, str(file))
    spec = importlib.util.spec_from_loader(name, loader)
    result = importlib.util.module_from_spec(spec)
    loader.exec_module(result)
    return result


def shell(text, env=None):
    return subprocess.run(['/bin/sh', '-eu', '-c', f'. {shlex.quote(str(LIB))}\n' + text],
                          env={**os.environ, **(env or {})}, text=True,
                          capture_output=True, timeout=25)


class ExternalVendorTransportTests(TransportFixture):
    def setUp(self):
        super().setUp()
        if not all(shutil.which(p) for p in ('openssl', 'wget')):
            self.skipTest('openssl and wget are required for verified TLS fixtures')
        cert, key = self.root/'cert.pem', self.root/'key.pem'
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1',
                        '-subj','/CN=localhost','-addext','subjectAltName=IP:127.0.0.1',
                        '-keyout',str(key),'-out',str(cert)], check=True,
                        capture_output=True, timeout=15)
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(cert, key)
        self.web = self.endpoint(tls=tls)
        bindir = self.root/'bin'; bindir.mkdir()
        wget = bindir/'wget'
        wget.write_text('#!/bin/sh\nexec ' + shlex.quote(shutil.which('wget')) +
                        ' --ca-certificate=' + shlex.quote(str(cert)) + ' "$@"\n')
        wget.chmod(0o755)
        self.trusted_env = {'PATH':str(bindir)+':'+os.environ['PATH']}
        (self.runtime/'bootstrap').mkdir(parents=True)
        (self.runtime/'bootstrap/payload.ready').write_text('validated fixture\n')

    def test_external_verified_https_survives_ready_marker(self):
        dst = self.root/'vendor-key'
        result = self.shell(f'. {shlex.quote(str(LIB))}\ninstaller_fetch_url '
                            f'{self.web.base} repo.env {dst} 0644', env=self.trusted_env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(dst.read_bytes(), (SEED/'repo.env').read_bytes())
        self.assertEqual(stat.S_IMODE(dst.stat().st_mode), 0o644)
        self.assertEqual(sum(self.web.counts.values()), 1)

    def test_payload_member_missing_still_fails_closed(self):
        result = self.shell(f'source_fetch {self.web.base} 3bf863cc.pub {self.root}/out',
                            env=self.trusted_env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('file absent from validated payload', result.stderr)
        self.assertEqual(sum(self.web.counts.values()), 0)

    def test_external_ignores_explicit_repository_tls_bypass(self):
        result = self.shell(f'source_fetch_external {self.web.base} repo.env {self.root}/out',
                            env={'INSTALLER_CMDLINE':'allow_unauthenticated_ssl=true'})
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root/'out').exists())

    def test_external_disallows_http_traversal_and_executable_mode(self):
        for base, rel, mode in [(self.web.base.replace('https:','http:'),'repo.env','0600'),
                                (self.web.base,'../repo.env','0600'),
                                (self.web.base,'repo.env','0755')]:
            with self.subTest(base=base, rel=rel, mode=mode):
                result = self.shell(f'source_fetch_external {base} {shlex.quote(rel)} '
                                    f'{self.root}/out {mode}', env=self.trusted_env)
                self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sum(self.web.counts.values()), 0)

    def test_failed_external_download_preserves_destination(self):
        dst = self.root/'out'; dst.write_text('do not replace')
        result = self.shell(f'source_fetch_external {self.web.base} missing {dst}', env=self.trusted_env)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(dst.read_text(), 'do not replace')
        self.assertFalse(list(self.root.glob('out.external.*')))


class CudaLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='cuda-regression-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = {'INSTALLER_TARGET_DIR':str(self.root)}
        (self.root/'usr/share/apt').mkdir(parents=True)
        self.baseline = self.root/'usr/share/apt/default-sequoia.config'
        self.baseline.write_text('[hash_algorithms]\nsha1.second_preimage_resistance = 2026-02-01\nsha224 = 2026-02-01\n')

    def test_source_uses_full_fingerprint_and_no_authentication_bypass(self):
        result = shell(f'installer_cuda_source_line {KEYRING} {REPO} /')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f'signed-by={KEYRING},{FP}', result.stdout)
        for bad in ('trusted=yes','allow-insecure','allow-weak','http://'):
            self.assertNotIn(bad, result.stdout)
        for repo in (REPO.replace('https:','http:'), REPO.replace('debian12','debian13')):
            self.assertNotEqual(shell(f'installer_cuda_source_line {KEYRING} {repo} /').returncode, 0)

    def test_key_download_rejects_unknown_origin_before_fetch(self):
        result = shell('installer_fetch_url() { exit 88; }; '
                       f'installer_fetch_cuda_key https://example.invalid/key.asc {self.root}/key 0644')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotEqual(result.returncode, 88)
        self.assertFalse((self.root/'key').exists())

    def test_key_download_rejects_html_without_replacing_old_key(self):
        dst = self.root/'key'; dst.write_text('existing')
        result = shell('installer_fetch_url() { printf "<html>error</html>" >"$3"; }; '
                       f'installer_fetch_cuda_key {REPO}3bf863cc.pub {dst} 0644')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(dst.read_text(), 'existing')

    def test_compat_policy_preserves_other_rules_and_fails_unknown_baseline(self):
        output = self.root/'compat'
        result = shell(f'installer_cuda_compat_policy {self.baseline} {output}')
        self.assertEqual(result.returncode, 0, result.stderr)
        text = output.read_text()
        self.assertIn('sha224 = 2026-02-01', text)
        self.assertIn('sha1.collision_resistance = 1970-01-01', text)
        self.assertIn('sha1.second_preimage_resistance = 2027-02-01', text)
        self.baseline.write_text('[hash_algorithms]\nsha256 = "always"\n')
        self.assertNotEqual(shell(f'installer_cuda_compat_policy {self.baseline} {output}').returncode, 0)
        self.assertFalse(output.exists())

    def refresh(self, strict_error, strict_status=1):
        log = self.root/'calls'
        script = f'''run_in_target() {{
  printf '%s\\n' "$*" >>{shlex.quote(str(log))}
  case "$1" in
    *default*) printf '%s\\n' {shlex.quote(strict_error)}; exit {strict_status} ;;
    *) case "$*" in *APT_SEQUOIA_CRYPTO_POLICY=*) : ;; *) exit 66;; esac ;;
  esac
}}
installer_cuda_refresh_target_apt
'''
        return shell(script, self.env), log

    def test_retry_isolated_from_run_in_target_exit_and_scoped_to_cuda(self):
        result, log = self.refresh(f'{FP}: SHA1 rejected PositiveCertification binding signature')
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        calls = log.read_text().splitlines()
        self.assertEqual(len(calls), 2)
        self.assertNotIn('APT_SEQUOIA_CRYPTO_POLICY', calls[0])
        self.assertIn('Dir::Etc::sourceparts=-', calls[1])
        self.assertIn('Dir::Etc::sourcelist=/etc/apt/sources.list.d/cuda-legacy-temp.list', calls[1])
        self.assertIn('Acquire::AllowInsecureRepositories=false', calls[1])
        self.assertFalse(list((self.root/'run').glob('cuda-legacy-verify.*')))

    def test_strict_success_does_not_use_exception(self):
        result, log = self.refresh('metadata authenticated normally', 0)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(log.read_text().splitlines()), 1)

    def test_tls_wrong_key_expiry_and_tampering_do_not_trigger_exception(self):
        for reason in ('TLS certificate rejected', FP+': bad signature',
                       'WRONGKEY SHA1 PositiveCertification', FP+': key expired'):
            with self.subTest(reason=reason):
                (self.root/'calls').unlink(missing_ok=True)
                result, log = self.refresh(reason)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(len(log.read_text().splitlines()), 1)
                self.assertFalse(list((self.root/'run').glob('cuda-legacy-verify.*')))

    def test_general_refresh_restores_cuda_source_on_success_and_exit(self):
        source = self.root/'etc/apt/sources.list.d/cuda-legacy-temp.list'
        source.parent.mkdir(parents=True)
        source.write_text('reviewed CUDA source\n')
        for status in (0, 7):
            result = shell(f'''. {shlex.quote(str(SEED/'scripts/late/storage-maintenance.sh'))}
run_in_target() {{
  [ ! -e {shlex.quote(str(source))} ] || exit 81
  [ -f {shlex.quote(str(source))}.installer-disabled ] || exit 82
  exit {status}
}}
refresh_non_cuda_target_metadata apt-get update
''', self.env)
            self.assertEqual(result.returncode, status, result.stderr)
            self.assertEqual(source.read_text(), 'reviewed CUDA source\n')
            self.assertFalse(Path(str(source)+'.installer-disabled').exists())


class RealSignatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('gpg') or not shutil.which('sqv'):
            raise unittest.SkipTest('GnuPG and Sequoia sqv are required for actual cryptographic verification')
        if '--policy-as-of' not in subprocess.run(['sqv','--help'],capture_output=True,text=True).stdout:
            raise unittest.SkipTest('sqv version lacks deterministic policy-date testing')
        cls.temp = tempfile.TemporaryDirectory(prefix='cuda-crypto-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name); cls.root.chmod(0o700)
        cls.gpg = ['gpg','--homedir',str(cls.root),'--batch','--yes',
                   '--pinentry-mode','loopback','--passphrase','']
        subprocess.run(cls.gpg+['--faked-system-time','1740000000','--cert-digest-algo','SHA1',
                       '--quick-generate-key','Offline fixture <nobody@example.invalid>','rsa3072','sign','0'],
                       check=True, capture_output=True, timeout=30)
        cls.addClassCleanup(subprocess.run, ['gpgconf','--homedir',str(cls.root),'--kill','gpg-agent'],
                            capture_output=True, timeout=10)
        cls.release = cls.root/'Release'; cls.release.write_text('Origin: Offline fixture\nSuite: test\n')
        for digest in ('SHA256','SHA1'):
            subprocess.run(cls.gpg+['--digest-algo',digest,'--detach-sign','-o',
                           str(cls.root/digest),str(cls.release)], check=True,
                           capture_output=True, timeout=15)
        key = subprocess.run(cls.gpg+['--armor','--export'],check=True,capture_output=True).stdout
        (cls.root/'key.asc').write_bytes(key)
        cls.baseline = cls.root/'strict.config'
        cls.baseline.write_text('[hash_algorithms]\nsha1.second_preimage_resistance = 2026-02-01\n')
        cls.compat = cls.root/'compat.config'
        result = shell(f'installer_cuda_compat_policy {cls.baseline} {cls.compat}')
        if result.returncode:
            raise RuntimeError(result.stderr)

    def verify(self, digest='SHA256', compat=True, data=None, date='2026-09-06'):
        return subprocess.run(['sqv','--policy-as-of',date,'--keyring',str(self.root/'key.asc'),
                               '--signature-file',str(self.root/digest),str(data or self.release)],
                              env={**os.environ,'SEQUOIA_CRYPTO_POLICY':str(self.compat if compat else self.baseline)},
                              capture_output=True,text=True,timeout=10)

    def test_actual_sha1_certificate_rejected_by_strict_policy(self):
        result = self.verify(compat=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SHA1', result.stderr)

    def test_sha256_release_with_legacy_certificate_authenticates(self):
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_sha1_release_data_signature_still_rejected(self):
        result = self.verify('SHA1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SHA1', result.stderr)

    def test_modified_release_rejected(self):
        tampered = self.root/'tampered'; tampered.write_text('Origin: Attacker\nSuite: test\n')
        self.assertNotEqual(self.verify(data=tampered).returncode, 0)

    def test_certificate_exception_expires(self):
        self.assertNotEqual(self.verify(date='2027-02-02').returncode, 0)


class BrowserConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.builder = module('browser_build_security_test', ROOT/'tools/build_browser_config.py')
        cls.products = cls.builder.generate()
        cls.ns = json.loads(cls.products[EXPORT/'noscript_data.txt'])
        cls.ub = json.loads(cls.products[EXPORT/'my-ubol-settings.json'])
        cls.pb = json.loads(cls.products[EXPORT/cls.builder.PB_FILE])
        cls.coverage = json.loads(cls.products[EXPORT/'bookmark-coverage.json'])

    def test_generated_files_are_reproducible_and_current(self):
        self.assertEqual(self.products, self.builder.generate())
        for path, data in self.products.items():
            self.assertEqual(path.read_bytes(), data, str(path))

    def test_all_bookmarks_accounted_for_with_nested_exclusions(self):
        counts = self.coverage['counts']
        self.assertEqual(counts, {'bookmark_entries':691,'included_web_entries':543,
                         'included_web_origins':338,'excluded_folder_entries':100,
                         'internal_or_non_web_entries':48,'live_tested_entries':0})
        for row in self.coverage['entries']:
            excluded = bool({'entertainment','imported'} & {x.casefold() for x in row['folders']})
            self.assertEqual(row['status']=='excluded-folder', excluded)
            self.assertFalse(row['live_tested'])
            if row['status']=='configured-unverified':
                top = row['origin']
                caps = self.ns['policy']['sites']['custom'][top]['contextual'][top]['capabilities']
                self.assertIn('script', caps)
                self.assertNotIn('lan', caps)
                self.assertNotIn('ping', caps)
                self.assertNotIn('object', caps)

    def test_no_blanket_trust_and_no_clone_of_noscript_instance_uuid(self):
        self.assertEqual(self.ns['policy']['sites']['trusted'], [])
        self.assertNotIn('uuid', self.ns['local'])
        self.assertFalse(self.ns['policy']['autoAllowTop'])
        self.assertTrue(self.ns['sync']['xss'])
        self.assertTrue(self.ns['sync']['clearclick'])
        for rule in self.ns['policy']['sites']['custom'].values():
            self.assertNotIn('script', rule['capabilities'])
            self.assertTrue(rule['contextual'])

    def test_ubol_uses_real_rulesets_and_no_unprotected_bookmarks(self):
        self.assertEqual(self.ub['filteringModes'], {'none':[],'basic':[],'optimal':['all-urls'],'complete':[]})
        self.assertEqual({x[1:] for x in self.ub['rulesets']}, set(self.builder.EXTRA_RULESETS))
        self.assertNotIn('+default', self.ub['rulesets'])
        self.assertFalse(self.ub['popupBlockMode'])

    def test_no_fabricated_badger_observations_or_signal(self):
        settings = self.pb['settings_map']
        for key in ('sendDNTSignal','checkForDNTPolicy','learnLocally','learnInIncognito'):
            self.assertFalse(settings[key])
        self.assertEqual(settings['disabledSites'], [])
        for key in ('snitch_map','tracking_map','fp_scripts'):
            self.assertEqual(self.pb[key], {})
        self.assertEqual(len(self.pb['action_map']), 29)
        self.assertTrue(all(v['userAction']=='user_block' for v in self.pb['action_map'].values()))

    def test_devtools_and_extension_settings_are_available(self):
        for family in ('etc/vivaldi','etc/chromium','etc/opt/edge','etc/opt/chrome'):
            security = json.loads(self.products[TARGET/family/'policies/managed/security.json'])
            self.assertEqual(security['DeveloperToolsAvailability'], 1)
            self.assertTrue(security['RemoteDebuggingAllowed'])
            self.assertEqual(security['ExtensionDeveloperModeSettings'], 0)
        ext = json.loads(self.products[TARGET/'etc/vivaldi/policies/managed/extensions.json'])
        for setting in ext['ExtensionSettings'].values():
            self.assertEqual(setting['installation_mode'], 'normal_installed')
            self.assertNotIn('blocked_permissions', setting)
        self.assertNotIn('jplgfhpmjnbigmhklmmbgecoobifkmpa', ext['ExtensionSettings'])
        ub = ext['3rdparty']['extensions'][self.builder.UBOL]
        for key in ('disabledFeatures','rulesets','defaultFilteringMode','noFiltering'):
            self.assertNotIn(key, ub)

    def test_only_recommendable_policies_and_no_invented_dnt_policy(self):
        allowed = {'BackgroundModeEnabled','BlockThirdPartyCookies','NetworkPredictionOptions',
                   'SearchSuggestEnabled','AutofillAddressEnabled','AutofillCreditCardEnabled','PasswordManagerEnabled'}
        for path, data in self.products.items():
            if path.name == 'defaults.json':
                self.assertLessEqual(json.loads(data).keys(), allowed)
            if '/policies/' in str(path):
                self.assertNotIn('EnableDoNotTrack', json.loads(data))
        for profile in ('vivaldi','microsoft-edge','chromium'):
            prefs = json.loads(self.products[TARGET/'etc/skel/.config'/profile/'Default/Preferences'])
            self.assertFalse(prefs['enable_do_not_track'])

    def test_native_urls_are_not_web_origins(self):
        for value in ('chrome://policy','vivaldi://extensions','chrome-extension://abcdef/dashboard.html'):
            self.assertIsNone(self.builder.origin(value))
        self.assertEqual(self.builder.origin('https://EXAMPLE.com:443/path'), 'https://example.com')
        with self.assertRaises(ValueError):
            self.builder.origin('https://user:password@example.com/')


class ImportPublisherTests(unittest.TestCase):
    def setUp(self):
        self.pub = module('import_publisher_security_test', TARGET/'usr/local/libexec/install-browser-imports')
        self.temp = tempfile.TemporaryDirectory(prefix='browser-publish-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fd = os.open(self.root, os.O_RDONLY|os.O_DIRECTORY)
        self.addCleanup(os.close, self.fd)

    def test_private_owned_idempotent_publication(self):
        name = self.pub.publish(self.fd, 'test.json', b'new data', os.getuid(), os.getgid())
        self.assertEqual(name, 'test.json')
        info = (self.root/name).stat()
        self.assertEqual(stat.S_IMODE(info.st_mode), 0o600)
        self.assertEqual(info.st_uid, os.getuid())
        self.assertEqual(self.pub.publish(self.fd, name, b'new data', os.getuid(), os.getgid()), name)
        self.assertFalse(list(self.root.glob('.browser-import-*')))

    def test_user_edits_preserved_and_update_not_clobbered(self):
        (self.root/'test.json').write_text('user edits')
        self.assertEqual(self.pub.publish(self.fd,'test.json',b'new',os.getuid(),os.getgid()), 'test.json.install-update')
        with self.assertRaises(ValueError):
            self.pub.publish(self.fd,'test.json',b'newer',os.getuid(),os.getgid())
        self.assertEqual((self.root/'test.json').read_text(), 'user edits')
        self.assertEqual((self.root/'test.json.install-update').read_bytes(), b'new')

    def test_symlinks_and_fifos_rejected(self):
        for name in ('symlink','fifo'):
            if name == 'symlink': (self.root/name).symlink_to('/etc/passwd')
            else: os.mkfifo(self.root/name)
            with self.assertRaises(ValueError):
                self.pub.publish(self.fd,name,b'new',os.getuid(),os.getgid())
        self.assertFalse(list(self.root.glob('.browser-import-*')))

    def test_root_home_rejected(self):
        with self.assertRaises(ValueError):
            self.pub.install(self.root,self.root,0,0)

    @unittest.skipUnless(os.geteuid()==0, 'cross-account ownership fixture requires root')
    def test_full_install_uses_owned_downloads_and_rejects_download_symlink(self):
        home = self.root/'home'; home.mkdir(); os.chown(home, 65534, 65534)
        source = self.root/'source'; source.mkdir()
        for name in self.pub.FILES:
            (source/name).write_text('{}\n'); (source/name).chmod(0o600)
        names = self.pub.install(source,home,65534,65534)
        self.assertEqual(set(names), set(self.pub.FILES))
        self.assertEqual(stat.S_IMODE((home/'Downloads').stat().st_mode),0o700)
        for name in names:
            self.assertEqual((home/'Downloads'/name).stat().st_uid,65534)
        shutil.rmtree(home/'Downloads')
        (home/'Downloads').symlink_to(source)
        with self.assertRaises(OSError):
            self.pub.install(source,home,65534,65534)


class DebugLauncherTests(unittest.TestCase):
    def setUp(self):
        self.debug = module('browser_debug_security_test', TARGET/'usr/local/bin/browser-devtools')
        self.temp = tempfile.TemporaryDirectory(prefix='browser-debug-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_port_range(self):
        self.assertEqual(self.debug.port_number('9222'), 9222)
        for port in ('0','80','65536'):
            with self.assertRaises(argparse.ArgumentTypeError): self.debug.port_number(port)

    def test_profile_is_separate_private_and_rejects_symlink(self):
        profile = self.debug.private_profile(self.root,'vivaldi',os.getuid())
        self.assertEqual(profile, self.root/'.local/state/browser-devtools/vivaldi')
        self.assertEqual(stat.S_IMODE(profile.stat().st_mode),0o700)
        profile.rmdir(); profile.symlink_to(self.root)
        with self.assertRaises(ValueError): self.debug.private_profile(self.root,'vivaldi',os.getuid())

    @unittest.skipUnless(os.geteuid()==0, 'root-refusal fixture requires root')
    def test_root_execution_rejected(self):
        result = subprocess.run(['python3',str(TARGET/'usr/local/bin/browser-devtools'),'chromium','--dry-run'],
                                capture_output=True,text=True,timeout=10)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('without sudo',result.stderr)

    def test_command_has_no_sandbox_disable_or_wildcard_listener(self):
        text = (TARGET/'usr/local/bin/browser-devtools').read_text()
        self.assertIn('--remote-debugging-address=127.0.0.1', text)
        self.assertIn('--user-data-dir=',text)
        self.assertNotIn('--no-sandbox',text)
        self.assertNotIn('--remote-allow-origins',text)
        self.assertNotIn('0.0.0.0',text)

# Additional production-path regressions discovered during integration review.
class AdditionalProductionRegressions(unittest.TestCase):
    def test_dkms_wrapper_fails_instead_of_recursing_and_preserves_arguments(self):
        text = (SEED/'hooks/installer/pre-pkgsel.d/92nvidia-legacy-dkms.sh').read_text()
        self.assertIn('--rename --add /usr/sbin/dkms', text)
        wrapper = text.split("<<'EOF'\n",1)[1].split('\nEOF',1)[0]
        tail = wrapper[wrapper.index('real_dkms='):]
        with tempfile.TemporaryDirectory(prefix='dkms-wrapper-') as tmp:
            real = Path(tmp)/'dkms.distrib'
            script = 'patch_legacy_nvidia_source_tree() { :; }\n' + tail.replace('/usr/sbin/dkms.distrib',str(real))
            result = subprocess.run(['/bin/sh','-eu','-c',script,'sh','test argument'],capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,127)
            real.write_text('#!/bin/sh\nprintf "%s\\n" "$1"\n'); real.chmod(0o755)
            result = subprocess.run(['/bin/sh','-eu','-c',script,'sh','test argument'],capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stdout,'test argument\n')

    def test_secret_files_harden_read_bits_but_reject_other_writers(self):
        with tempfile.TemporaryDirectory(prefix='private-preseed-') as tmp:
            file = Path(tmp)/'preseed.env'
            marker = Path(tmp)/'executed'
            file.write_text(f'touch {marker}\nPRESEED_ROOT_PASSWORD=fixture-only\n')
            for script,prefix in [(LIB,'installer'),(SEED/'scripts/runtime/common.sh','runtime')]:
                for mode,expected in [(0o644,True),(0o660,False),(0o600,True),(0o400,True)]:
                    marker.unlink(missing_ok=True); file.chmod(mode)
                    result = subprocess.run(['/bin/sh','-eu','-c',f'. {script}; {prefix}_preseed_env_value root_password'],
                                            env={**os.environ,'INSTALLER_PRESEED_ENV_FILE':str(file)},
                                            text=True,capture_output=True,timeout=5)
                    self.assertEqual(result.returncode==0,expected,result.stderr)
                    self.assertEqual(marker.exists(),expected)
                    if mode == 0o644:
                        self.assertEqual(file.stat().st_mode & 0o777, 0o600)

    def test_apparmor_allows_only_each_browsers_dedicated_debug_state(self):
        for file,browser in [('chromium','chromium'),('microsoft-edge-stable','edge'),('vivaldi-bin','vivaldi')]:
            text = (TARGET/'etc/apparmor.d/local'/file).read_text()
            self.assertIn(f'owner @{{HOME}}/.local/state/browser-devtools/{browser}/** rwkl,',text)
            self.assertNotIn('@{HOME}/.local/state/**',text)
            self.assertNotIn(f'browser-devtools/{browser}/** m',text)
        text = (TARGET/'etc/apparmor.d/local/vivaldi-bin').read_text()
        self.assertEqual(text.count('browser-devtools/vivaldi/** rwkl,'),2)

    @unittest.skipUnless(os.geteuid()==0 and shutil.which('apt-get') and shutil.which('gpg') and shutil.which('sqv'),
                         'isolated APT/Sequoia integration fixture requires root and apt/gpg/sqv')
    def test_actual_apt_signed_by_full_fingerprint_and_strong_signature(self):
        # RealSignatureTests owns the temporary key; create a separate fixture
        # here rather than relying on unittest class execution order.
        import hashlib
        import email.utils
        import datetime
        with tempfile.TemporaryDirectory(prefix='apt-signed-fixture-') as tmp:
            root = Path(tmp); root.chmod(0o755)
            keyhome = root/'gnupg'; keyhome.mkdir(mode=0o700)
            gpg = ['gpg','--homedir',str(keyhome),'--batch','--yes','--pinentry-mode','loopback','--passphrase','']
            subprocess.run(gpg+['--faked-system-time','1740000000','--cert-digest-algo','SHA1',
                           '--quick-generate-key','APT fixture <test@example.invalid>','rsa3072','sign','0'],
                           check=True,capture_output=True,timeout=30)
            try:
                repo = root/'repo'; repo.mkdir(); (repo/'Packages').write_bytes(b'')
                release = ('Origin: OfflineFixture\nSuite: test\nCodename: test\nDate: '+
                           email.utils.format_datetime(datetime.datetime.now(datetime.timezone.utc),usegmt=True)+
                           '\nArchitectures: amd64\nSHA256:\n '+hashlib.sha256(b'').hexdigest()+' 0 Packages\n')
                (repo/'Release').write_text(release)
                subprocess.run(gpg+['--digest-algo','SHA256','--clearsign','-o',str(repo/'InRelease'),str(repo/'Release')],
                               check=True,capture_output=True,timeout=15)
                key = root/'key.asc'; key.write_bytes(subprocess.check_output(gpg+['--armor','--export']))
                listing = subprocess.check_output(gpg+['--with-colons','--list-keys'],stderr=subprocess.DEVNULL,text=True)
                fingerprint = next(line.split(':')[9] for line in listing.splitlines() if line.startswith('fpr:'))
                source = root/'sources.list'
                source.write_text(f'deb [arch=amd64 signed-by={key},{fingerprint}] file:{repo} /\n')
                (root/'lists/partial').mkdir(parents=True)
                (root/'cache/archives/partial').mkdir(parents=True)
                strict = root/'strict'; strict.write_text('[hash_algorithms]\nsha1.second_preimage_resistance = 1970-01-01\n')
                compat = root/'compat'
                self.assertEqual(shell(f'installer_cuda_compat_policy {strict} {compat}').returncode,0)
                command = ['apt-get','-o','Dir::Etc::sourcelist='+str(source),'-o','Dir::Etc::sourceparts=-',
                           '-o','Dir::State::lists='+str(root/'lists'),'-o','Dir::Cache='+str(root/'cache'),
                           '-o','APT::Update::Error-Mode=any','-o','Debug::NoLocking=1',
                           '-o','APT::Get::List-Cleanup=0','-o','APT::Sandbox::User=root','update']
                def update(policy):
                    return subprocess.run(command,env={**os.environ,'LC_ALL':'C',
                                          'APT_SEQUOIA_CRYPTO_POLICY':str(policy),'SEQUOIA_CRYPTO_POLICY':str(policy)},
                                          capture_output=True,text=True,timeout=15)
                strict_result = update(strict)
                self.assertNotEqual(strict_result.returncode,0)
                result = update(compat)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                # A valid signature made by a key not selected in Signed-By
                # must still fail; a TLS key download is not the trust anchor.
                source.write_text(f'deb [arch=amd64 signed-by={key},{"0"*40}] file:{repo} /\n')
                self.assertNotEqual(update(compat).returncode,0)
            finally:
                subprocess.run(['gpgconf','--homedir',str(keyhome),'--kill','gpg-agent'],capture_output=True,timeout=10)


if __name__ == '__main__':
    unittest.main()
