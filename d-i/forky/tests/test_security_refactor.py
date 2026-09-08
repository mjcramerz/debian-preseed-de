#!/usr/bin/env python3
"""Regression coverage for the 2026-09-06 installer/browser security repair.

All network fixtures use loopback; no real vendor or bookmarked site is visited.
CUDA lifecycle/real-APT checks are in test_cuda_legacy_apt.py.
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

    def test_nvidia_580_header_patch_adds_string_and_gpio_compat_once(self):
        text = (SEED/'hooks/installer/pre-pkgsel.d/92nvidia-legacy-dkms.sh').read_text()
        wrapper = text.split("<<'EOF'\n",1)[1].split('\nEOF',1)[0]
        patcher = wrapper[:wrapper.index('\npatch_legacy_nvidia_source_tree()')]
        script = patcher + '\npatch_nv_linux_header "$1"\n'
        with tempfile.TemporaryDirectory(prefix='nvidia-header-') as tmp:
            header = Path(tmp)/'nv-linux.h'
            header.write_text('#ifndef _NV_LINUX_H_\n#include "conftest.h"\n'
                              '#include <linux/of_gpio.h>\n#endif\n')
            header.chmod(0o640)
            first_run = subprocess.run(['/bin/sh','-eu','-c',script,'sh',str(header)],
                                       capture_output=True,text=True,timeout=5)
            self.assertEqual(first_run.returncode,0,first_run.stderr)
            first = header.read_bytes()
            second_run = subprocess.run(['/bin/sh','-eu','-c',script,'sh',str(header)],
                                        capture_output=True,text=True,timeout=5)
            self.assertEqual(second_run.returncode,0,second_run.stderr)
            self.assertEqual(header.read_bytes(),first)
            rewritten = first.decode()
            self.assertIn('#include "conftest.h"\n#include <linux/string.h>\n'
                          '/* NV_INSTALLER_NVIDIA_LEGACY_STRING_COMPAT */', rewritten)
            self.assertEqual(rewritten.count('#include <linux/string.h>'),1)
            self.assertEqual(rewritten.count('NV_INSTALLER_NVIDIA_LEGACY_STRING_COMPAT'),1)
            self.assertEqual(rewritten.count('NV_INSTALLER_NVIDIA_LEGACY_OF_GPIO_COMPAT'),1)
            self.assertEqual(rewritten.count('#include <linux/gpio/consumer.h>'),1)
            self.assertEqual(stat.S_IMODE(header.stat().st_mode),0o640)
            self.assertEqual(list(header.parent.glob('nv-linux.h.tmp.*')),[])

    def test_nvidia_580_header_patch_fails_closed_without_known_anchor(self):
        text = (SEED/'hooks/installer/pre-pkgsel.d/92nvidia-legacy-dkms.sh').read_text()
        wrapper = text.split("<<'EOF'\n",1)[1].split('\nEOF',1)[0]
        tree_patcher = wrapper[:wrapper.index('\nreal_dkms=')]
        self.assertIn('/usr/src/nvidia-580.*',tree_patcher)
        self.assertIn('/usr/src/nvidia-current-580.*',tree_patcher)
        self.assertNotIn('/usr/src/nvidia-*',tree_patcher)
        self.assertNotIn('/var/lib/dkms/nvidia/*/',tree_patcher)
        with tempfile.TemporaryDirectory(prefix='nvidia-header-invalid-') as tmp:
            source = Path(tmp)/'nvidia-580.142'
            header = source/'common/inc/nv-linux.h'
            header.parent.mkdir(parents=True)
            original = '#include <linux/of_gpio.h>\n'
            header.write_text(original)
            replacements = {
                '/usr/src/nvidia-580.*': str(Path(tmp)/'nvidia-580.*'),
                '/usr/src/nvidia-current-580.*': str(Path(tmp)/'missing-current-580.*'),
                '/var/lib/dkms/nvidia/580.*/source': str(Path(tmp)/'missing-dkms-580.*/source'),
                '/var/lib/dkms/nvidia/580.*/build': str(Path(tmp)/'missing-dkms-580.*/build'),
            }
            for installed,fixture in replacements.items():
                tree_patcher = tree_patcher.replace(installed,fixture)
            result = subprocess.run(['/bin/sh','-eu','-c',tree_patcher+'\npatch_legacy_nvidia_source_tree\n'],
                                    capture_output=True,text=True,timeout=5)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('cannot transform recognized NVIDIA 580 header',result.stderr)
            self.assertIn('failed to patch NVIDIA 580 source header before DKMS compilation',result.stderr)
            self.assertEqual(header.read_text(),original)
            self.assertEqual(list(header.parent.glob('nv-linux.h.tmp.*')),[])

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
        # Ordinary repositories must retain signature and fingerprint checks.
        # CUDA's explicit trust exception must not alter their verifier policy.
        import hashlib
        import email.utils
        import datetime
        with tempfile.TemporaryDirectory(prefix='apt-signed-fixture-') as tmp:
            root = Path(tmp); root.chmod(0o755)
            keyhome = root/'gnupg'; keyhome.mkdir(mode=0o700)
            gpg = ['gpg','--homedir',str(keyhome),'--batch','--yes','--pinentry-mode','loopback','--passphrase','']
            subprocess.run(gpg+['--faked-system-time','1740000000','--cert-digest-algo','SHA256',
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
                config = root/'apt.conf'; config.write_text('')
                command = ['apt-get','-o','Dir::Etc::main=-','-o','Dir::Etc::parts=-',
                           '-o','Dir::Etc::sourcelist='+str(source),'-o','Dir::Etc::sourceparts=-',
                           '-o','Dir::State::lists='+str(root/'lists'),'-o','Dir::Cache='+str(root/'cache'),
                           '-o','APT::Update::Error-Mode=any','-o','Debug::NoLocking=1',
                           '-o','APT::Get::List-Cleanup=0','-o','APT::Sandbox::User=root','update']
                def update():
                    env = {**os.environ, 'LC_ALL': 'C', 'APT_CONFIG': str(config)}
                    env.pop('APT_SEQUOIA_CRYPTO_POLICY', None)
                    env.pop('SEQUOIA_CRYPTO_POLICY', None)
                    return subprocess.run(command, env=env, capture_output=True, text=True, timeout=15)
                result = update()
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                # A valid signature made by a key not selected in Signed-By
                # must still fail; a TLS key download is not the trust anchor.
                source.write_text(f'deb [arch=amd64 signed-by={key},{"0"*40}] file:{repo} /\n')
                self.assertNotEqual(update().returncode,0)
            finally:
                subprocess.run(['gpgconf','--homedir',str(keyhome),'--kill','gpg-agent'],capture_output=True,timeout=10)


if __name__ == '__main__':
    unittest.main()
