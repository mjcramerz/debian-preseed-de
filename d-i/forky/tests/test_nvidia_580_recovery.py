"""Exercise recovery orchestration with a fake chroot; no host packages changed."""
from __future__ import annotations
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_nvidia_legacy_dkms import wrapper_text

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / 'tools/repair_nvidia_580.sh'

@unittest.skipUnless(os.geteuid() == 0, 'recovery ownership tests require root')
class Nvidia580RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='nv580-recovery-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / 'target'
        self.kernel = '7.2.4-x64v3-xanmod1'
        for name in ['etc', 'usr/sbin', 'dev', 'proc', 'sys/class',
                     f'lib/modules/{self.kernel}/build']:
            (self.target / name).mkdir(parents=True, exist_ok=True)
        (self.target / 'etc/debian_version').write_text('forky/sid\n')
        (self.target / f'lib/modules/{self.kernel}/build/Module.symvers').write_text('fixture\n')
        (self.target / 'dev/null').symlink_to('/dev/null')
        (self.target / 'proc/self').symlink_to('/proc/self')
        for name in ('dkms', 'dkms.distrib'):
            (self.target / f'usr/sbin/{name}').write_text('#!/bin/sh\nexit 0\n')
            (self.target / f'usr/sbin/{name}').chmod(0o755)
        bindir = self.root / 'bin'
        bindir.mkdir()
        stub = bindir / 'chroot'
        stub.write_text(r'''#!/bin/sh
set -eu
shift
printf '%s\t' "$@" >> "$RECOVERY_LOG"
printf '\n' >> "$RECOVERY_LOG"
kind=$1
[ "$1" != /usr/sbin/dkms ] || kind=$2
[ "$kind" != "${RECOVERY_FAIL:-}" ] || exit 37
case $1 in
  dpkg-query)
    case " $* " in
      *' -f=${Version} '*) printf '%s\n' "${RECOVERY_VERSION:-580.142-1}" ;;
      *' -f=${Status} '*) printf '%s\n' "${RECOVERY_STATUS:-install ok installed}" ;;
      *) printf '%s\n' 'nvidia-dkms-580 580.142-1' ;;
    esac ;;
  modinfo)
    case " $* " in
      *' -F vermagic '*) printf '%s\n' "${RECOVERY_VERMAGIC:-7.2.4-x64v3-xanmod1 SMP preempt mod_unload modversions}" ;;
      *) printf '%s\n' "${RECOVERY_MODVERSION:-580.142}" ;;
    esac ;;
esac
''')
        stub.chmod(0o755)
        self.log = self.root / 'calls.jsonl'
        self.env = {**os.environ, 'PATH': str(bindir)+os.pathsep+os.environ['PATH'],
                    'RECOVERY_LOG': str(self.log)}

    def run_repair(self, **env):
        p = subprocess.run(['/bin/sh', str(SCRIPT), str(self.target), self.kernel],
                           env={**self.env, **env}, capture_output=True, text=True, timeout=20)
        calls = [line.rstrip('\t').split('\t') for line in self.log.read_text().splitlines()] if self.log.exists() else []
        return p, calls

    def test_success_uses_identical_wrapper_explicit_kernel_and_verifies_modules(self):
        old = (self.target / 'usr/sbin/dkms').read_bytes()
        p, calls = self.run_repair()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual((self.target / 'usr/sbin/dkms').read_text(), wrapper_text()+'\n')
        self.assertEqual(list((self.target / 'usr/sbin').glob('dkms.before-r2.*'))[0].read_bytes(), old)
        self.assertFalse(list((self.target / 'usr/sbin').glob('dkms.r2.*')))
        build = ['/usr/sbin/dkms', 'build', '-m', 'nvidia', '-v', '580.142', '-k', self.kernel, '--force']
        install = build.copy(); install[1] = 'install'
        self.assertIn(build, calls)
        self.assertIn(install, calls)
        configure = ['/usr/bin/env', 'DEBIAN_FRONTEND=noninteractive', 'dpkg', '--configure', '-a']
        for mod in ('nvidia', 'nvidia-modeset', 'nvidia-drm', 'nvidia-uvm'):
            check = ['modinfo', '-k', self.kernel, '-F', 'version', mod]
            self.assertIn(check, calls)
            self.assertLess(calls.index(check), calls.index(configure))
        self.assertIn(['update-initramfs', '-u', '-k', self.kernel], calls)
        self.assertIn('retry package installation', p.stdout)

    def test_build_failure_is_not_hidden_and_configuration_does_not_run(self):
        p, calls = self.run_repair(RECOVERY_FAIL='build')
        self.assertEqual(p.returncode, 37)
        self.assertEqual(calls[-1][1], 'build')
        self.assertFalse(any('dpkg' in c or 'install' in c for c in calls))

    def test_install_failure_is_not_hidden(self):
        p, calls = self.run_repair(RECOVERY_FAIL='install')
        self.assertEqual(p.returncode, 37)
        self.assertEqual(calls[-1][1], 'install')

    def test_wrong_module_version_blocks_package_configuration(self):
        p, calls = self.run_repair(RECOVERY_MODVERSION='590.1')
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('expected', p.stderr)
        self.assertFalse(any('dpkg' in c for c in calls))

    def test_wrong_kernel_identity_blocks_package_configuration(self):
        p, calls = self.run_repair(RECOVERY_VERMAGIC='6.12.94+deb13-amd64 SMP')
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('kernel identity', p.stderr)
        self.assertFalse(any('dpkg' in c for c in calls))

    def test_unconfigured_package_is_not_reported_as_success(self):
        p, calls = self.run_repair(RECOVERY_STATUS='install ok half-configured')
        self.assertNotEqual(p.returncode, 0)
        self.assertNotIn('repair completed', p.stdout)

    def test_rejects_different_driver_branch_before_wrapper_change(self):
        original = (self.target / 'usr/sbin/dkms').read_bytes()
        p, _ = self.run_repair(RECOVERY_VERSION='590.1-1')
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual((self.target / 'usr/sbin/dkms').read_bytes(), original)

    def test_epoch_and_package_revision_are_not_part_of_dkms_version(self):
        p, calls = self.run_repair(RECOVERY_VERSION='1:580.142-2~local')
        self.assertEqual(p.returncode, 0, p.stderr)
        build = next(c for c in calls if len(c)>1 and c[1]=='build')
        self.assertEqual(build[build.index('-v')+1], '580.142')

    def test_missing_headers_stop_before_any_chroot(self):
        (self.target / f'lib/modules/{self.kernel}/build/Module.symvers').unlink()
        p, calls = self.run_repair()
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(calls, [])

    def test_invalid_kernel_is_rejected_before_any_chroot(self):
        self.kernel = '../wrong;touch BAD'
        p, calls = self.run_repair()
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(calls, [])

if __name__ == '__main__':
    unittest.main()
