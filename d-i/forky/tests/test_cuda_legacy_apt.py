#!/usr/bin/env python3
"""CUDA-legacy regression tests, including real APT and disposable signing keys.

Only loopback repositories and private APT directories are used. Test packages
are downloaded, never installed. Set CUDA_TEST_APT_ROOT to an extracted Debian
APT/libapt-pkg tree to repeat the same tests with a different APT version.
"""
from __future__ import annotations

import email.utils
import functools
import hashlib
import http.server
import os
from pathlib import Path
import pwd
import shlex
import shutil
import stat
import subprocess
import tempfile
import threading
import time
import unittest

SEED = Path(__file__).resolve().parents[1]
LIB = SEED / 'scripts/common/lib.sh'
REPO = 'https://developer.download.nvidia.com/compute/cuda/repos/debian12/x86_64/'
SOURCE_PATH = 'etc/apt/sources.list.d/cuda-legacy-temp.list'
FINGERPRINT = 'EB693B3035CD5710E231E123A4B469963BF863CC'
KEY_PATH = '/etc/apt/keyrings/cuda-legacy-archive-key.asc'
REQUIRED = ('arch=amd64', 'signed-by=' + KEY_PATH + ',' + FINGERPRINT)


def shell(text: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(['/bin/sh', '-eu', '-c', '. ' + shlex.quote(str(LIB)) + '\n' + text],
                          env={**os.environ, **(env or {})}, capture_output=True,
                          text=True, timeout=20)


def rendered_source() -> str:
    result = shell(f'installer_cuda_source_line {REPO} /')
    if result.returncode:
        raise RuntimeError(result.stderr)
    return result.stdout


class CudaLifecycleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='cuda-lifecycle-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.env = {'INSTALLER_TARGET_DIR': str(self.root)}
        self.source = self.root / SOURCE_PATH

    def test_source_scoped_signed_by_pins_the_full_nvidia_fingerprint(self):
        line = rendered_source()
        for option in REQUIRED:
            self.assertIn(option, line)
        for forbidden in ('trusted=yes', 'allow-insecure', 'allow-weak', 'allow-downgrade', 'check-date=no', 'check-valid-until=no'):
            self.assertNotIn(forbidden, line)
        self.assertEqual(line.count(REPO), 1)
        self.assertEqual(len(line.splitlines()), 1)

    def test_source_policy_cannot_be_reused_for_another_origin_suite_or_components(self):
        cases = [(REPO.replace('https:', 'http:'), '/', ''),
                 (REPO.replace('debian12', 'debian13'), '/', ''),
                 (REPO+'evil/', '/', ''), (REPO, 'forky', ''),
                 (REPO, '/', 'main'), (REPO+'\ndeb bad', '/', '')]
        for args in cases:
            with self.subTest(args=args):
                self.assertNotEqual(shell('installer_cuda_source_line ' + shlex.join(args)).returncode, 0)

    def test_stage_fetches_key_and_publishes_repeatably(self):
        key = self.root/KEY_PATH.lstrip('/')
        key.parent.mkdir(parents=True)
        key.write_text('previous key')
        for _ in range(2):
            result = shell(f'installer_fetch_cuda_key() {{ printf "fixture key\\n" >"$INSTALLER_TARGET_DIR{KEY_PATH}"; }}\n'
                           f'installer_cuda_stage_target_source {REPO} /', self.env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.source.read_text(), rendered_source())
            self.assertEqual(stat.S_IMODE(self.source.stat().st_mode), 0o644)
            self.assertEqual(key.read_text(), 'fixture key\n')
            self.assertFalse(list(self.source.parent.glob('.cuda-legacy.*')))
        self.assertFalse((self.root/'usr/share/apt/default-sequoia.config').exists())

    def test_key_fetch_failure_never_publishes_a_new_source(self):
        self.source.parent.mkdir(parents=True)
        self.source.write_text('old source\n')
        result = shell(f'installer_fetch_cuda_key() {{ return 71; }}\n'
                       f'installer_cuda_stage_target_source {REPO} /', self.env)
        self.assertEqual(result.returncode, 71, result.stderr)
        self.assertEqual(self.source.read_text(), 'old source\n')

    def test_invalid_input_does_not_change_existing_source(self):
        self.source.parent.mkdir(parents=True)
        self.source.write_text('previous source\n')
        result = shell('installer_cuda_stage_target_source https://evil.invalid/ /', self.env)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.source.read_text(), 'previous source\n')

    def test_failed_atomic_publish_preserves_old_file_and_cleans_temporary(self):
        self.source.parent.mkdir(parents=True)
        self.source.write_text('old\n')
        result = shell(f'installer_fetch_cuda_key() {{ :; }}\nmv() {{ return 73; }}\ninstaller_cuda_stage_target_source {REPO} /', self.env)
        self.assertEqual(result.returncode, 73, result.stderr)
        self.assertEqual(self.source.read_text(), 'old\n')
        self.assertFalse(list(self.source.parent.glob('.cuda-legacy.*')))

    def test_symlink_source_is_refused(self):
        self.source.parent.mkdir(parents=True)
        victim = self.root/'victim'; victim.write_text('untouched')
        self.source.symlink_to(victim)
        result = shell(f'installer_cuda_stage_target_source {REPO} /', self.env)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(victim.read_text(), 'untouched')

    def test_refresh_runs_once_without_crypto_baseline_or_global_relaxation(self):
        for status in (0, 100):
            with self.subTest(status=status):
                calls = self.root/'calls'
                result = shell(f'''run_in_target() {{
  printf '%s\\n' "$*" >{shlex.quote(str(calls))}
  return {status}
}}
installer_cuda_refresh_target_apt
''', self.env)
                self.assertEqual(result.returncode, status, result.stderr)
                text = calls.read_text()
                self.assertEqual(len(text.splitlines()), 1)
                self.assertIn('Dir::Etc::sourceparts=-', text)
                self.assertIn('Dir::Etc::sourcelist=/' + SOURCE_PATH, text)
                self.assertIn('APT::Get::List-Cleanup=0', text)
                self.assertIn('-u APT_SEQUOIA_CRYPTO_POLICY -u SEQUOIA_CRYPTO_POLICY', text)
                for forbidden in ('AllowInsecureRepositories=', 'AllowWeakRepositories=',
                                  'AllowUnauthenticated=', 'Verify-Peer=false', 'sequoia.config'):
                    self.assertNotIn(forbidden, text)

    def test_selected_cuda_stack_is_not_gated_on_pci_detection(self):
        path = SEED/'scripts/preseed/answers.sh'
        definition = path.read_text().split('selected_fragment_applies_to_detected_hardware() {', 1)[1].split('\nselected_arch_class()', 1)[0]
        result = shell('selected_fragment_applies_to_detected_hardware() {' + definition +
                       '\ninstaller_nvidia_gpu_detected() { return 1; }\n'
                       'selected_fragment_applies_to_detected_hardware classes/class-addon/cuda-legacy.cfg\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        result = shell(f'''. {shlex.quote(str(SEED/'scripts/late/cuda-legacy.sh'))}
installer_cuda_legacy_selected() {{ return 0; }}
installer_nvidia_gpu_detected() {{ return 1; }}
cuda_legacy_target_apt_required
''')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unselected_class_does_not_request_late_cuda_state(self):
        result = shell(f'''. {shlex.quote(str(SEED/'scripts/late/cuda-legacy.sh'))}
installer_cuda_legacy_selected() {{ return 1; }}
cuda_legacy_target_apt_required
''')
        self.assertNotEqual(result.returncode, 0)

    def run_pre_pkgsel_hook(self, *, selected=True, apt_status=0):
        bootstrap = self.root/'bootstrap.sh'
        calls = self.root/'target-calls'
        bootstrap.write_text("""bootstrap_source_common_lib() {
  . "$CUDA_TEST_LIB"
  installer_runtime_log_file() { printf '%s/log\\n' "$INSTALLER_TARGET_DIR"; }
  installer_init_log_file() { :; }
  installer_finalize_log() { :; }
  installer_seed_base() { printf '%s\\n' "$CUDA_TEST_SEED"; }
  installer_persist_seed_source() { :; }
  installer_ensure_context_loaded() { :; }
  installer_cuda_legacy_selected() { return "$CUDA_TEST_SELECTED"; }
  installer_nvidia_gpu_detected() { return 1; }
  installer_fetch_file() { cp "$1/$2" "$3"; }
  installer_fetch_cuda_key() { :; }
  run_in_target() {
    printf '%s\\n' "$1" >>"$CUDA_TEST_CALLS"
    case "$1" in
      'refresh authenticated legacy CUDA metadata')
        grep -q 'signed-by=' "$INSTALLER_TARGET_DIR/etc/apt/sources.list.d/cuda-legacy-temp.list" || return 91
        return "$CUDA_TEST_APT_STATUS" ;;
    esac
    return 0
  }
}
bootstrap_source_common_support_libs() { :; }
""")
        env = {**os.environ, **self.env, 'INSTALLER_BOOTSTRAP_LIB': str(bootstrap),
               'INSTALLER_CUDA_PREPKGSEL_ENV_DIR': str(self.root/'hook-env'),
               'CUDA_TEST_LIB': str(LIB), 'CUDA_TEST_SEED': str(SEED),
               'CUDA_TEST_SELECTED': '0' if selected else '1',
               'CUDA_TEST_APT_STATUS': str(apt_status), 'CUDA_TEST_CALLS': str(calls)}
        result = subprocess.run(['/bin/sh', str(SEED/'hooks/installer/pre-pkgsel.d/91cuda-legacy-apt.sh')],
                                env=env, text=True, capture_output=True, timeout=15)
        return result, calls

    def test_entire_selected_pre_pkgsel_hook_stages_authenticated_source_before_refresh(self):
        for _ in range(2):
            result, calls = self.run_pre_pkgsel_hook()
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertEqual(self.source.read_text(), rendered_source())
        invocations = calls.read_text().splitlines()
        self.assertEqual(len(invocations), 4)
        self.assertIn('repair legacy CUDA target apt directories', invocations[0])
        self.assertIn('refresh authenticated legacy CUDA metadata', invocations[1])
        self.assertNotIn('signed-by', invocations[1])

    def test_entire_unselected_pre_pkgsel_hook_leaves_apt_untouched(self):
        result, calls = self.run_pre_pkgsel_hook(selected=False)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertFalse(self.source.exists())
        self.assertFalse(calls.exists())

    def test_entire_pre_pkgsel_hook_propagates_real_apt_failure(self):
        result, calls = self.run_pre_pkgsel_hook(apt_status=100)
        self.assertEqual(result.returncode, 100, result.stdout+result.stderr)
        self.assertEqual(self.source.read_text(), rendered_source())
        self.assertEqual(calls.read_text().count('refresh authenticated legacy CUDA metadata'), 1)

    def test_pre_pkgsel_and_late_use_one_authenticated_publisher(self):
        for relative in ('hooks/installer/pre-pkgsel.d/91cuda-legacy-apt.sh',
                         'scripts/late/cuda-legacy.sh'):
            text = (SEED/relative).read_text()
            self.assertIn('installer_cuda_stage_target_source', text)
            for forbidden in ('installer_fetch_cuda_key', 'installer_nvidia_gpu_detected', 'signed-by='):
                self.assertNotIn(forbidden, text)
        common = LIB.read_text()
        self.assertNotIn('installer_cuda_compat_policy()', common)
        self.assertNotIn('default-sequoia.config', common)
        self.assertNotIn('verify legacy CUDA metadata with default APT policy', common)

    def test_general_refresh_restores_cuda_source_on_success_and_failure(self):
        self.source.parent.mkdir(parents=True)
        self.source.write_text(rendered_source())
        for status in (0, 7):
            result = shell(f'''. {shlex.quote(str(SEED/'scripts/late/storage-maintenance.sh'))}
run_in_target() {{
  [ ! -e {shlex.quote(str(self.source))} ] || exit 81
  [ -f {shlex.quote(str(self.source))}.installer-disabled ] || exit 82
  exit {status}
}}
refresh_non_cuda_target_metadata apt-get update
''', self.env)
            self.assertEqual(result.returncode, status, result.stderr)
            self.assertEqual(self.source.read_text(), rendered_source())
            self.assertFalse(Path(str(self.source)+'.installer-disabled').exists())

    def test_cleanup_honors_target_root_and_preserves_unrelated_sources(self):
        self.source.parent.mkdir(parents=True)
        self.source.write_text(rendered_source())
        other = self.source.parent/'debian.sources'; other.write_text('debian policy\n')
        result = shell(f'''. {shlex.quote(str(SEED/'scripts/late/cuda-legacy.sh'))}
cuda_legacy_cleanup_target_apt_state
cuda_legacy_cleanup_target_apt_state
''', self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.source.exists())
        self.assertEqual(other.read_text(), 'debian policy\n')

    def test_no_global_authentication_or_tls_bypass_was_added(self):
        for path in (SEED/'hooks/target/etc/apt/apt.conf.d').glob('*'):
            if not path.is_file():
                continue
            text = path.read_text()
            for forbidden in ('AllowInsecureRepositories "true"', 'AllowWeakRepositories "true"',
                              'AllowUnauthenticated "true"', 'Verify-Peer "false"'):
                self.assertNotIn(forbidden, text, str(path))


class QuietHTTP(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        # Never reuse metadata in transition tests: every request gets current
        # fixture bytes even when mtimes share one filesystem timestamp tick.
        if 'If-Modified-Since' in self.headers:
            del self.headers['If-Modified-Since']
        super().do_GET()


class RealAptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not all(shutil.which(name) for name in ('apt-get', 'gpg', 'gpgconf', 'dpkg-deb')):
            raise unittest.SkipTest('APT, GnuPG and dpkg-deb are required')
        cls.temp = tempfile.TemporaryDirectory(prefix='cuda-real-apt-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name); cls.root.chmod(0o755)
        cls.gnupg = cls.root/'gnupg'; cls.gnupg.mkdir(mode=0o700)
        cls.gpg = ['gpg', '--homedir', str(cls.gnupg), '--batch', '--yes',
                   '--pinentry-mode', 'loopback', '--passphrase', '']
        cls.addClassCleanup(subprocess.run,
                            ['gpgconf', '--homedir', str(cls.gnupg), '--kill', 'gpg-agent'],
                            capture_output=True, timeout=10)
        for digest in ('SHA1', 'SHA256'):
            subprocess.run(cls.gpg + ['--faked-system-time', '1740000000',
                           '--cert-digest-algo', digest, '--quick-generate-key',
                           f'{digest} Fixture <{digest.lower()}@example.invalid>', 'rsa2048', 'sign', '0'],
                           check=True, capture_output=True, timeout=30)
            exported = subprocess.run(cls.gpg + ['--armor', '--export', digest+' Fixture'],
                                      check=True, capture_output=True).stdout
            (cls.root/(digest+'.asc')).write_bytes(exported)
        cls.fingerprints = {}
        for digest in ('SHA1', 'SHA256'):
            listing = subprocess.run(cls.gpg + ['--with-colons', '--list-keys', digest+' Fixture'],
                                     check=True, capture_output=True, text=True).stdout
            cls.fingerprints[digest] = next(line.split(':')[9] for line in listing.splitlines() if line.startswith('fpr:'))
        cls.webroot = cls.root/'www'; cls.webroot.mkdir()
        handler = functools.partial(QuietHTTP, directory=str(cls.webroot))
        cls.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
        thread = threading.Thread(target=cls.server.serve_forever, daemon=True); thread.start()
        cls.addClassCleanup(thread.join, 5)
        cls.addClassCleanup(cls.server.server_close)
        cls.addClassCleanup(cls.server.shutdown)
        cls.base = f'http://127.0.0.1:{cls.server.server_port}/'
        pkg = cls.root/'package'; (pkg/'DEBIAN').mkdir(parents=True)
        (pkg/'DEBIAN/control').write_text('Package: cuda-legacy-fixture\nVersion: 1.0\n'
                                       'Architecture: all\nMaintainer: Test <nobody@example.invalid>\n'
                                       'Description: Inert authentication regression fixture\n')
        (pkg/'usr/share/cuda-legacy-fixture').mkdir(parents=True)
        (pkg/'usr/share/cuda-legacy-fixture/fixture.txt').write_text('fixture\n')
        cls.deb = cls.root/'fixture.deb'
        subprocess.run(['dpkg-deb', '--build', '--root-owner-group', str(pkg), str(cls.deb)],
                       check=True, capture_output=True, timeout=20)
        data = cls.deb.read_bytes()
        cls.packages = ('Package: cuda-legacy-fixture\nVersion: 1.0\nArchitecture: all\n'
                        'Maintainer: Test <nobody@example.invalid>\n'
                        'Filename: fixture.deb\n' + f'Size: {len(data)}\n' +
                        f'SHA256: {hashlib.sha256(data).hexdigest()}\n'
                        'Description: Inert authentication regression fixture\n\n')

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix='case-', dir=self.root))
        self.work.chmod(0o755)
        self.repo = self.webroot/self.work.name; self.repo.mkdir()
        (self.repo/'Packages').write_text(self.packages)
        shutil.copy2(self.deb, self.repo/'fixture.deb')
        self.repo_url = self.base+self.repo.name+'/'
        self.source = self.work/'sources.list'
        self.source.write_text(rendered_source().replace(REPO, self.repo_url)
                               .replace(KEY_PATH, str(self.work/'trusted/fixture.asc'))
                               .replace(FINGERPRINT, self.fingerprints['SHA256']))
        for name in ('lists/partial', 'archives/partial', 'trusted', 'log'):
            (self.work/name).mkdir(parents=True)
        (self.work/'status').write_text('')
        (self.work/'empty.conf').write_text('')
        # Empty APT_CONFIG prevents host hooks/policy from entering the test.
        self.env = {**os.environ, 'APT_CONFIG': str(self.work/'empty.conf'), 'LC_ALL': 'C',
                    'DEBIAN_FRONTEND': 'noninteractive'}
        self.env.pop('APT_SEQUOIA_CRYPTO_POLICY', None)
        self.env.pop('SEQUOIA_CRYPTO_POLICY', None)
        self.apt = shutil.which('apt-get')
        self.options = []
        settings = {'Dir::Etc::main': '-', 'Dir::Etc::parts': '-',
                    'Dir::Etc::sourcelist': str(self.source), 'Dir::Etc::sourceparts': '-',
                    'Dir::Etc::trusted': str(self.work/'absent.gpg'),
                    'Dir::Etc::trustedparts': str(self.work/'trusted'),
                    'Dir::Etc::preferences': '-', 'Dir::Etc::preferencesparts': '-',
                    'Dir::State::lists': str(self.work/'lists'),
                    'Dir::State::status': str(self.work/'status'),
                    'Dir::State::extended_states': str(self.work/'extended_states'),
                    'Dir::Cache::archives': str(self.work/'archives'),
                    'Dir::Cache::pkgcache': '', 'Dir::Cache::srcpkgcache': '',
                    'Dir::Log': str(self.work/'log'), 'APT::Architecture': 'amd64',
                    'APT::Sandbox::User': pwd.getpwuid(os.geteuid()).pw_name,
                    'Acquire::Languages': 'none', 'Acquire::Retries': '0',
                    'Acquire::http::Proxy': 'DIRECT', 'Acquire::http::Timeout': '3',
                    'Acquire::AllowInsecureRepositories': 'false',
                    'Acquire::AllowWeakRepositories': 'false',
                    'APT::Get::AllowUnauthenticated': 'false',
                    'APT::Get::List-Cleanup': '0', 'APT::Update::Error-Mode': 'any'}
        apt_root = os.environ.get('CUDA_TEST_APT_ROOT')
        if apt_root:
            tree = Path(apt_root).resolve()
            self.apt = str(tree/'usr/bin/apt-get')
            settings['Dir::Bin::methods'] = str(tree/'usr/lib/apt/methods')
            self.env['LD_LIBRARY_PATH'] = str(tree/'usr/lib/x86_64-linux-gnu')
        for key, value in settings.items():
            self.options.extend(['-o', f'{key}={value}'])

    def release(self, *, cert='SHA256', digest='SHA256', signed=True, clear=False,
                weak_hash=False, expired=False):
        data = (self.repo/'Packages').read_bytes()
        self.release_revision = getattr(self, 'release_revision', 0) + 1
        header = (f'X-Fixture-Revision: {self.release_revision}\n' + 'Origin: CUDA fixture\nLabel: NVIDIA CUDA\nSuite: fixture\n'
                  'Architectures: amd64\nDate: '+email.utils.formatdate(time.time()-60, usegmt=True)+'\n')
        if expired:
            header += 'Valid-Until: Wed, 01 Jan 2025 00:00:00 GMT\n'
        hasher = hashlib.sha1 if weak_hash else hashlib.sha256
        header += ('SHA1' if weak_hash else 'SHA256')+':\n '+hasher(data).hexdigest()+f' {len(data)} Packages\n'
        (self.repo/'Release').write_text(header)
        for name in ('InRelease', 'Release.gpg'):
            (self.repo/name).unlink(missing_ok=True)
        if signed:
            command = ['--clearsign'] if clear else ['--armor', '--detach-sign']
            subprocess.run(self.gpg+['--local-user', cert+' Fixture', '--digest-algo', digest,
                           '--output', str(self.repo/('InRelease' if clear else 'Release.gpg')),
                           *command, str(self.repo/'Release')], check=True, capture_output=True, timeout=15)
            shutil.copy2(self.root/(cert+'.asc'), self.work/'trusted/fixture.asc')
            self.source.write_text(rendered_source().replace(REPO, self.repo_url)
                                   .replace(KEY_PATH, str(self.work/'trusted/fixture.asc'))
                                   .replace(FINGERPRINT, self.fingerprints[cert]))

    def apt_run(self, *args: str):
        return subprocess.run([self.apt, *self.options, *args], env=self.env,
                              capture_output=True, text=True, timeout=25, cwd=self.work)

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def assert_downloadable(self):
        result = self.apt_run('-y', '--download-only', '--no-install-recommends',
                              'install', 'cuda-legacy-fixture')
        self.assert_success(result)
        files = list((self.work/'archives').glob('*.deb'))
        self.assertEqual(len(files), 1, result.stdout+result.stderr)
        self.assertEqual(files[0].read_bytes(), self.deb.read_bytes())

    def test_signed_sha256_update_and_repeat_download(self):
        self.release()
        for _ in range(2):
            self.assert_success(self.apt_run('update'))
        self.assert_downloadable()

    def test_sha1_certificate_remains_rejected(self):
        self.release(cert='SHA1')
        result = self.apt_run('update')
        self.assertNotEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_sha1_release_signature_remains_rejected(self):
        self.release(digest='SHA1')
        self.assertNotEqual(self.apt_run('update').returncode, 0)

    def test_weak_clearsigned_inrelease_remains_rejected(self):
        self.release(cert='SHA1', digest='SHA1', clear=True)
        self.assertNotEqual(self.apt_run('update').returncode, 0)

    def test_unsigned_source_is_rejected(self):
        self.release(signed=False)
        self.assertNotEqual(self.apt_run('update').returncode, 0)

    def test_weak_metadata_hashes_remain_rejected(self):
        self.release(weak_hash=True)
        self.assertNotEqual(self.apt_run('update').returncode, 0)

    def test_expired_signed_metadata_remains_rejected(self):
        self.release(expired=True)
        self.assertNotEqual(self.apt_run('update').returncode, 0)

    def test_authenticated_to_unsigned_transition_is_rejected(self):
        self.release()
        self.assert_success(self.apt_run('update'))
        self.release(signed=False)
        self.assertNotEqual(self.apt_run('update').returncode, 0)

    def test_missing_key_is_rejected(self):
        self.release()
        (self.work/'trusted/fixture.asc').unlink()
        self.assertNotEqual(self.apt_run('update').returncode, 0)

    def test_valid_signature_from_wrong_fingerprint_is_rejected(self):
        self.release()
        self.source.write_text(self.source.read_text().replace(self.fingerprints['SHA256'], '0'*40))
        self.assertNotEqual(self.apt_run('update').returncode, 0)

    def test_other_unsigned_repository_still_fails_in_a_mixed_update(self):
        self.release()
        other = self.webroot/(self.repo.name+'-other'); shutil.copytree(self.repo, other)
        (other/'Release.gpg').unlink()
        with self.source.open('a') as stream:
            stream.write(f'deb [arch=amd64] {self.base}{other.name}/ /\n')
        result = self.apt_run('update')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('not signed', result.stdout+result.stderr)

    def test_missing_package_index_fails(self):
        self.release()
        (self.repo/'Packages').unlink()
        self.assertNotEqual(self.apt_run('update').returncode, 0)

    def test_corrupt_package_is_not_downloaded_as_an_authentication_workaround(self):
        self.release()
        self.assert_success(self.apt_run('update'))
        (self.repo/'fixture.deb').write_bytes(b'corrupt\n')
        result = self.apt_run('-y', '--download-only', 'install', 'cuda-legacy-fixture')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(list((self.work/'archives').glob('*.deb')))


if __name__ == '__main__':
    unittest.main()
