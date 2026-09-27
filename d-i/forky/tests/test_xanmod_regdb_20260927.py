"""Offline alternatives fixtures; never alter host firmware or kernel state."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'scripts/late/storage-maintenance.sh'


class XanmodRegdbTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.firmware = self.root / 'firmware'
        self.firmware.mkdir()
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.db = self.firmware / 'regulatory.db'
        self.sig = self.firmware / 'regulatory.db.p7s'
        self.upstream = self.firmware / 'regulatory.db-upstream'
        self.upstream_sig = self.firmware / 'regulatory.db.p7s-upstream'
        self.upstream.write_bytes(b'packaged database fixture')
        self.upstream_sig.write_bytes(b'packaged signature fixture')
        (self.firmware / 'regulatory.db-debian').write_bytes(b'debian database fixture')
        (self.firmware / 'regulatory.db.p7s-debian').write_bytes(b'debian signature fixture')
        self.db.symlink_to(self.firmware / 'regulatory.db-debian')
        self.sig.symlink_to(self.firmware / 'regulatory.db.p7s-debian')
        (self.bin / 'dpkg-query').write_text('''#!/bin/sh
[ "$*" = '-W -f=${db:Status-Status} wireless-regdb' ] || exit 2
printf '%s' "${FIXTURE_PACKAGE_STATUS:-installed}"
''')
        (self.bin / 'update-alternatives').write_text('''#!/bin/sh
case "$1" in
  --query) printf 'Alternative: %s\\n' "$FIXTURE_ALTERNATIVE" ;;
  --set)
    [ "$2" = regulatory.db ] && [ "$3" = "$FIXTURE_ALTERNATIVE" ] || exit 2
    ln -sfn "$3" "$FIXTURE_DB_LINK"
    if [ "${FIXTURE_BAD_SIGNATURE:-0}" = 1 ]; then
      ln -sfn "$FIXTURE_DEBIAN_SIGNATURE" "$FIXTURE_SIG_LINK"
    else
      ln -sfn "${3%-upstream}.p7s-upstream" "$FIXTURE_SIG_LINK"
    fi ;;
  *) exit 2 ;;
esac
''')
        for executable in self.bin.iterdir():
            executable.chmod(0o755)

        function = SOURCE.read_text().split('configure_target_xanmod_regulatory_database() {', 1)[1].split('\n}\n', 1)[0]
        function = ('configure_target_xanmod_regulatory_database() {' + function + '\n}\n')
        function = function.replace('/usr/lib/firmware/', str(self.firmware) + '/')
        function = function.replace('/lib/firmware/', str(self.firmware) + '/')
        self.script = '''set -eu
require_in_target() { :; }
run_in_target() { shift; "$@"; }
''' + function + '\nconfigure_target_xanmod_regulatory_database\n'

    def run_policy(self, *, selected=True, registered=True, status='installed', bad_signature=False):
        env = dict(os.environ)
        env.update(PATH=str(self.bin) + ':' + env.get('PATH', '/usr/bin:/bin'),
                   INSTALLER_PKGSEL_INCLUDE='smartmontools linux-xanmod-x64v3' if selected else 'linux-image-amd64',
                   FIXTURE_ALTERNATIVE=str(self.upstream if registered else self.firmware / 'unknown'),
                   FIXTURE_PACKAGE_STATUS=status,
                   FIXTURE_BAD_SIGNATURE='1' if bad_signature else '0',
                   FIXTURE_DB_LINK=str(self.db), FIXTURE_SIG_LINK=str(self.sig),
                   FIXTURE_DEBIAN_SIGNATURE=str(self.firmware / 'regulatory.db.p7s-debian'))
        return subprocess.run(['/bin/sh', '-c', self.script], env=env,
                              capture_output=True, text=True, timeout=10)

    def test_xanmod_selects_packaged_database_and_paired_signature(self):
        result = self.run_policy()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.db.resolve(), self.upstream)
        self.assertEqual(self.sig.resolve(), self.upstream_sig)

    def test_other_kernels_keep_debian_package_default(self):
        self.assertEqual(self.run_policy(selected=False).returncode, 0)
        self.assertEqual(self.db.resolve(), self.firmware / 'regulatory.db-debian')

    def test_missing_package_or_signature_or_alternative_fails_closed(self):
        for change in ('package', 'signature', 'alternative'):
            with self.subTest(change=change):
                if change == 'signature':
                    self.upstream_sig.unlink()
                result = self.run_policy(status='unpacked' if change == 'package' else 'installed',
                                         registered=change != 'alternative')
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.db.resolve(), self.firmware / 'regulatory.db-debian')
                if change == 'signature':
                    self.upstream_sig.write_bytes(b'packaged signature fixture')

    def test_mismatched_signature_link_is_detected(self):
        self.assertNotEqual(self.run_policy(bad_signature=True).returncode, 0)

    def test_both_storage_families_select_before_kernel_image_repair(self):
        for family in ('btrfs', 'f2fs'):
            text = (ROOT / f'scripts/late/{family}-family.sh').read_text()
            self.assertLess(text.index('repair_target_pkgsel_include_packages\n'
                                       'configure_target_xanmod_regulatory_database'),
                            text.index('repair_target_installed_kernels'))


if __name__ == '__main__':
    unittest.main()
