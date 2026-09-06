#!/usr/bin/env python3
"""Fresh real shell installation in a chroot without /run/user or networking.

Only curl and its downloaded payload are fixtures. Package validation,
pre-created target handling, relocation, profile loading, permission checks,
and scratch cleanup are real.
"""
from __future__ import annotations
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest
from test_hardware_restore import make_chroot, FORKY


@unittest.skipUnless(os.geteuid() == 0 and shutil.which('busybox'), 'root chroot fixture')
class CodexFreshInstallTests(unittest.TestCase):
    def fixture(self, root, curl_error=False):
        make_chroot(root)
        root.chmod(0o755)
        for name in ('usr/bin', 'home/account/.profile.d', 'data/codex/usr/home',
                     'run/codex-installer/65534.fixture'):
            (root / name).mkdir(parents=True, exist_ok=True)
        for name in ('readlink', 'stat', 'id', 'grep', 'find', 'mktemp', 'wc', 'tr', 'chmod',
                     'rm', 'mv', 'ln', 'mkdir', 'cat', 'touch'):
            for directory in ('bin', 'usr/bin'):
                path = root / directory / name
                if not path.exists():
                    path.symlink_to('/bin/busybox')
        helper = root / 'installer'
        helper.write_text((FORKY / 'hooks/target/usr/local/bin/codex-standalone-install').read_text())
        helper.chmod(0o755)
        profile = root / 'home/account/.profile.d/71-devops-de.sh'
        profile.write_text('''devops_de_apply_environment() {
 CODEX_HOME=/data/codex/usr/home
 XDG_RUNTIME_DIR=/run/user/1000
 TMPDIR=/run/user/1000
 export CODEX_HOME XDG_RUNTIME_DIR TMPDIR
}
''')
        profile.chmod(0o644)
        for top in ('home/account', 'data/codex', 'run/codex-installer/65534.fixture'):
            for path in [root / top, *(root / top).rglob('*')]:
                os.chown(path, 65534, 65534, follow_symlinks=False)
                if path.is_dir():
                    path.chmod(0o700)
        (root / 'dev/null').chmod(0o666)
        curl = root / 'usr/bin/curl'
        curl.write_text('''#!/bin/sh
set -eu
printf '%s\\n' "$*" >> /home/account/curl.args
[ -d "$XDG_RUNTIME_DIR" ] && [ "$XDG_RUNTIME_DIR" = /run/codex-installer/65534.fixture ]
'''+ ('exit 22\n' if curl_error else '''
while [ "$#" -gt 0 ]; do
 if [ "$1" = --output ]; then output=$2; shift 2; else shift; fi
done
cat > "$output" <<'PAYLOAD'
#!/bin/sh
set -eu
[ "$CODEX_NON_INTERACTIVE" = 1 ]
[ "$CODEX_RELEASE" = 1.2.3 ]
[ "$1" = --release ] && [ "$2" = 1.2.3 ]
mkdir -p "$CODEX_HOME/packages/standalone/releases/1.2.3/bin"
cat > "$CODEX_HOME/packages/standalone/releases/1.2.3/bin/codex" <<'BINARY'
#!/bin/sh
printf 'codex-cli 1.2.3\\n'
BINARY
chmod 0755 "$CODEX_HOME/packages/standalone/releases/1.2.3/bin/codex"
ln -s releases/1.2.3 "$CODEX_HOME/packages/standalone/current"
PAYLOAD
'''))
        curl.chmod(0o755)

    def execute(self, root):
        return subprocess.run([shutil.which('chroot'), '--userspec=65534:65534', str(root),
            '/bin/sh', '/installer', '1.2.3', 'https://chatgpt.com/codex/install.sh',
            '1048576', '/data/codex/usr/home', '/data/codex/packages'],
            env={'PATH':'/usr/bin:/bin', 'HOME':'/home/account',
                 'XDG_RUNTIME_DIR':'/run/codex-installer/65534.fixture', 'LC_ALL':'C'},
            text=True, capture_output=True, timeout=15)

    def test_fresh_install_then_repeat_with_no_run_user_tree(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            self.fixture(root)
            self.assertFalse((root / 'run/user').exists())
            for _ in range(2):
                result = self.execute(root)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((root / 'run/user').exists())
            self.assertEqual((root / 'data/codex/usr/home/packages').readlink(), Path('/data/codex/packages'))
            self.assertEqual(stat.S_IMODE((root / 'data/codex/packages').stat().st_mode), 0o700)
            self.assertEqual((root / 'data/codex/packages').stat().st_uid, 65534)
            self.assertEqual(len((root / 'home/account/curl.args').read_text().splitlines()), 1)
            self.assertEqual(list((root / 'run/codex-installer/65534.fixture').iterdir()), [])

    def test_precreated_target_package_link_installs_in_place(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            self.fixture(root)
            packages = root / 'data/codex/packages'
            packages.mkdir(mode=0o700)
            os.chown(packages, 65534, 65534)
            source_packages = root / 'data/codex/usr/home/packages'
            source_packages.symlink_to('/data/codex/packages')

            for _ in range(2):
                result = self.execute(root)
                self.assertEqual(result.returncode, 0, result.stderr)

            self.assertEqual(source_packages.readlink(), Path('/data/codex/packages'))
            self.assertTrue((packages / 'standalone/releases/1.2.3/bin/codex').is_file())
            self.assertEqual(stat.S_IMODE(packages.stat().st_mode), 0o700)
            self.assertEqual(packages.stat().st_uid, 65534)
            self.assertEqual(len((root / 'home/account/curl.args').read_text().splitlines()), 1)
            self.assertEqual(list((root / 'run/codex-installer/65534.fixture').iterdir()), [])

    def test_download_failure_cleans_scratch_without_publish(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            self.fixture(root, curl_error=True)
            result = self.execute(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('failed to download', result.stderr)
            self.assertFalse((root / 'data/codex/packages').exists())
            self.assertEqual(list((root / 'run/codex-installer/65534.fixture').iterdir()), [])


if __name__ == '__main__':
    unittest.main()
