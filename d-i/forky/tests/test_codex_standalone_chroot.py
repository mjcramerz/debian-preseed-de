#!/usr/bin/env python3
'''Fresh real shell installation in a chroot without /run/user or networking.

Only curl and its downloaded payload are fixtures. Package validation,
transactional publication, profile isolation, permission checks, and scratch
cleanup are real.
'''
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
    def fixture(self, root, *, curl_error=False, payload_error=False):
        make_chroot(root)
        root.chmod(0o755)
        for name in (
            'usr/bin',
            'home/account/.profile.d',
            'data/codex/usr/home',
            'data/codex/packages',
            'run/codex-installer/65534.fixture',
        ):
            (root / name).mkdir(parents=True, exist_ok=True)
        for name in (
            'readlink', 'stat', 'id', 'grep', 'find', 'mktemp', 'wc', 'tr',
            'chmod', 'rm', 'mv', 'ln', 'mkdir', 'rmdir', 'cat', 'touch',
        ):
            for directory in ('bin', 'usr/bin'):
                command = root / directory / name
                if not command.exists():
                    command.symlink_to('/bin/busybox')

        helper = root / 'installer'
        helper.write_text(
            (FORKY / 'hooks/target/usr/local/bin/codex-standalone-install').read_text()
        )
        helper.chmod(0o755)
        profile = root / 'home/account/.profile.d/71-devops-de.sh'
        profile.write_text('''devops_de_apply_environment() {
 printf sourced > "$HOME/profile-was-sourced"
 return 89
}
''')
        profile.chmod(0o644)

        for top in (
            'home/account',
            'data/codex/usr',
            'data/codex/packages',
            'run/codex-installer/65534.fixture',
        ):
            for entry in [root / top, *(root / top).rglob('*')]:
                os.chown(entry, 65534, 65534, follow_symlinks=False)
                if entry.is_dir():
                    entry.chmod(0o700)
        codex_root = root / 'data/codex'
        os.chown(codex_root, 0, 65534)
        codex_root.chmod(0o3770)
        packages_link = root / 'data/codex/usr/home/packages'
        packages_link.symlink_to('/data/codex/packages')
        os.chown(packages_link, 65534, 65534, follow_symlinks=False)
        (root / 'dev/null').chmod(0o666)

        payload = r'''#!/bin/sh
set -eu
[ "$CODEX_NON_INTERACTIVE" = 1 ]
[ "$#" -eq 0 ]
[ "${CODEX_RELEASE+x}" != x ]
[ "${CODEX_INSTALLER_USE_RELEASES_OPENAI_COM+x}" != x ]
case "$CODEX_HOME" in
  /data/codex/.standalone-install.*/home) ;;
  *) exit 91 ;;
esac
[ "$CODEX_INSTALL_DIR" = "${CODEX_HOME%/home}/bin" ]
case ":$PATH:" in *":$CODEX_INSTALL_DIR:"*) exit 92 ;; esac
printf 'export PATH="%s:$PATH"\n' "$CODEX_INSTALL_DIR" > "$HOME/.zshrc"
mkdir -p "$CODEX_INSTALL_DIR"
cat > "$CODEX_INSTALL_DIR/codex" <<'VISIBLE'
#!/bin/sh
exit 93
VISIBLE
chmod 0755 "$CODEX_INSTALL_DIR/codex"
mkdir -p "$CODEX_HOME/packages/standalone/releases/0.153.3-x86_64-unknown-linux-musl"
'''
        if payload_error:
            payload += 'exit 42\n'
        else:
            payload += r'''cat > "$CODEX_HOME/packages/standalone/releases/0.153.3-x86_64-unknown-linux-musl/codex" <<'BINARY'
#!/bin/sh
printf 'codex-cli 0.153.3\n'
BINARY
chmod 0755 "$CODEX_HOME/packages/standalone/releases/0.153.3-x86_64-unknown-linux-musl/codex"
ln -s releases/0.153.3-x86_64-unknown-linux-musl "$CODEX_HOME/packages/standalone/current"
'''

        curl = root / 'usr/bin/curl'
        curl_body = r'''#!/bin/sh
set -eu
printf '%s\n' "$*" >> /home/account/curl.args
[ -d "$XDG_RUNTIME_DIR" ]
[ "$XDG_RUNTIME_DIR" = /run/codex-installer/65534.fixture ]
'''
        if curl_error:
            curl_body += 'exit 22\n'
        else:
            curl_body += r'''while [ "$#" -gt 0 ]; do
  if [ "$1" = --output ]; then
    output=$2
    shift 2
  else
    shift
  fi
done
cat > "$output" <<'PAYLOAD'
''' + payload + 'PAYLOAD\n'
        curl.write_text(curl_body)
        curl.chmod(0o755)

    def execute(self, root):
        return subprocess.run(
            [
                shutil.which('chroot'), '--userspec=65534:65534', str(root),
                '/bin/sh', '/installer', 'https://chatgpt.com/codex/install.sh',
                '1048576', '/data/codex/usr/home', '/data/codex/packages',
            ],
            env={
                'PATH': '/usr/bin:/bin',
                'HOME': '/home/account',
                'XDG_RUNTIME_DIR': '/run/codex-installer/65534.fixture',
                'LC_ALL': 'C',
            },
            text=True,
            capture_output=True,
            timeout=15,
        )

    def test_fresh_install_then_repeat_with_no_run_user_tree(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            self.fixture(root)
            self.assertFalse((root / 'run/user').exists())
            for _ in range(2):
                result = self.execute(root)
                self.assertEqual(result.returncode, 0, result.stderr)
            packages = root / 'data/codex/packages'
            self.assertFalse((root / 'run/user').exists())
            self.assertEqual(
                (root / 'data/codex/usr/home/packages').readlink(),
                Path('/data/codex/packages'),
            )
            self.assertEqual(stat.S_IMODE(packages.stat().st_mode), 0o700)
            self.assertEqual(packages.stat().st_uid, 65534)
            self.assertTrue(
                (
                    packages
                    / 'standalone/releases/0.153.3-x86_64-unknown-linux-musl/codex'
                ).is_file()
            )
            self.assertFalse((root / 'home/account/.zshrc').exists())
            self.assertFalse((root / 'home/account/.local/bin/codex').exists())
            self.assertFalse((root / 'home/account/profile-was-sourced').exists())
            self.assertEqual(list((root / 'data/codex').glob('.standalone-install.*')), [])
            self.assertEqual(len((root / 'home/account/curl.args').read_text().splitlines()), 1)
            self.assertEqual(list((root / 'run/codex-installer/65534.fixture').iterdir()), [])

    def test_failed_payload_does_not_publish_partial_package(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            self.fixture(root, payload_error=True)
            result = self.execute(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('official Codex standalone installer failed', result.stderr)
            self.assertEqual(list((root / 'data/codex/packages').iterdir()), [])
            self.assertEqual(
                (root / 'data/codex/usr/home/packages').readlink(),
                Path('/data/codex/packages'),
            )
            self.assertEqual(list((root / 'data/codex').glob('.standalone-install.*')), [])
            self.assertEqual(list((root / 'run/codex-installer/65534.fixture').iterdir()), [])

    def test_download_failure_cleans_scratch_without_publish(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            self.fixture(root, curl_error=True)
            result = self.execute(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('failed to download', result.stderr)
            self.assertEqual(list((root / 'data/codex/packages').iterdir()), [])
            self.assertEqual(list((root / 'data/codex').glob('.standalone-install.*')), [])
            self.assertEqual(list((root / 'run/codex-installer/65534.fixture').iterdir()), [])


if __name__ == '__main__':
    unittest.main()
