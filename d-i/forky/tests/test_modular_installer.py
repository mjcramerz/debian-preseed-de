"""Exercise real modular entrypoints against the authenticated payload.

Unlike isolated function fixtures, these tests never flatten modules, replace
loader functions, or invoke installer actions against a real installation target.
"""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

SEED = Path(__file__).resolve().parents[1]
Q = shlex.quote
SHELLS = [['/bin/dash']]
if shutil.which('busybox'):
    SHELLS.append([shutil.which('busybox'), 'sh'])

class RealModuleLoader(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='real-installer-modules-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.runtime = self.root / 'runtime'
        self.env = dict(os.environ, INSTALLER_RUNTIME_DIR=str(self.runtime),
                        INSTALLER_SOURCE_ROOT=str(SEED), INSTALLER_CMDLINE='')
        archive = hashlib.sha256((SEED / 'payload.tar.gz').read_bytes()).hexdigest()
        manifest = hashlib.sha256((SEED / 'payload.manifest').read_bytes()).hexdigest()
        self.prelude = f'''. {Q(str(SEED / 'scripts/common/source.sh'))}
source_prepare_payload {Q(str(SEED))} {archive} {manifest}
source_fetch {Q(str(SEED))} scripts/common/bootstrap.sh "$INSTALLER_RUNTIME_DIR/bootstrap/bootstrap.sh" 0600
. "$INSTALLER_RUNTIME_DIR/bootstrap/bootstrap.sh"
bootstrap_persist_seed_source {Q(str(SEED))}
'''

    def run_shell(self, code, *, shell=None, prepare=True):
        return subprocess.run([*(shell or SHELLS[0]), '-eu', '-c',
                               (self.prelude if prepare else '') + code],
                              env=self.env, text=True, capture_output=True, timeout=60)

    def assert_ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_all_groups_load_in_dash_and_ash_without_changing_arguments_or_globals(self):
        for shell in SHELLS:
            with self.subTest(shell=shell):
                result = self.run_shell('''
set -- first second
module_relative=sentinel
bootstrap_source_common_lib "$INSTALLER_SOURCE_ROOT"
bootstrap_fetch_seed_file "$INSTALLER_SOURCE_ROOT" scripts/runtime/common.sh "$INSTALLER_RUNTIME_DIR/bootstrap/runtime-common.sh"
. "$INSTALLER_RUNTIME_DIR/bootstrap/runtime-common.sh"
bootstrap_fetch_seed_file "$INSTALLER_SOURCE_ROOT" scripts/desktop/components.sh "$INSTALLER_RUNTIME_DIR/bootstrap/components.sh"
. "$INSTALLER_RUNTIME_DIR/bootstrap/components.sh"
'''+''.join(f"bootstrap_source_module {Q(name)}\n" for name in self.devops_modules())+'''
[ "$1:$2" = first:second ]
[ "$module_relative" = sentinel ]
for function in installer_fetch_host_env runtime_generate_crypto_bootstrap_key desktop_normalize_system_perl_module_parents devops_main; do
  command -v "$function" >/dev/null
done
printf 'loaded\\n'
''', shell=shell)
                self.assert_ok(result)
                self.assertEqual(result.stdout, 'loaded\n')

    @staticmethod
    def devops_modules():
        import re
        return re.findall(r"^bootstrap_source_module '([^']+)'", (SEED / 'scripts/late/devops.sh.tmpl').read_text(), re.M)

    def test_cached_common_entrypoint_works_in_a_fresh_hook_process(self):
        self.assert_ok(self.run_shell('bootstrap_source_common_lib "$INSTALLER_SOURCE_ROOT"\n'))
        result = self.run_shell('''. "$INSTALLER_RUNTIME_DIR/bootstrap/common-lib.sh"
command -v installer_fetch_host_env >/dev/null
printf 'standalone-hook-loaded\\n'
''', prepare=False)
        self.assert_ok(result)
        self.assertEqual(result.stdout, 'standalone-hook-loaded\n')

    def test_missing_authenticated_module_never_falls_back_to_local_source_or_stale_copy(self):
        result = self.run_shell('''
bootstrap_source_common_lib "$INSTALLER_SOURCE_ROOT"
cache=$(source_cache_root "$INSTALLER_SOURCE_ROOT")
rm "$cache/scripts/common/modules/files-logging.sh"
if bootstrap_source_module scripts/common/modules/files-logging.sh; then exit 88; fi
printf 'rejected\\n'
''')
        self.assert_ok(result)
        self.assertIn('file absent from validated payload', result.stderr)
        self.assertEqual(result.stdout, 'rejected\n')

    def test_source_symlink_is_rejected(self):
        result = self.run_shell('''
cache=$(source_cache_root "$INSTALLER_SOURCE_ROOT")
rm "$cache/scripts/common/credentials.sh"
ln -s /etc/passwd "$cache/scripts/common/credentials.sh"
if bootstrap_source_module scripts/common/credentials.sh; then exit 88; fi
''')
        self.assert_ok(result)
        self.assertIn('symlinked repository source', result.stderr)

    def test_module_directory_symlink_cannot_write_outside_runtime(self):
        outside = self.root / 'outside'
        outside.mkdir()
        result = self.run_shell(f'''
ln -s {Q(str(outside))} "$INSTALLER_RUNTIME_DIR/bootstrap/modules"
if bootstrap_source_module scripts/common/credentials.sh; then exit 88; fi
''')
        self.assert_ok(result)
        self.assertIn('symlinked module directory', result.stderr)
        self.assertEqual(list(outside.iterdir()), [])

    def test_world_writable_module_directory_is_not_silently_repaired(self):
        result = self.run_shell('''
mkdir "$INSTALLER_RUNTIME_DIR/bootstrap/modules"
chmod 0777 "$INSTALLER_RUNTIME_DIR/bootstrap/modules"
if bootstrap_source_module scripts/common/credentials.sh; then exit 88; fi
''')
        self.assert_ok(result)
        self.assertIn('unsafe module directory', result.stderr)
        self.assertEqual((self.runtime / 'bootstrap/modules').stat().st_mode & 0o777, 0o777)

    def test_existing_hardlinked_module_destination_is_rejected(self):
        result = self.run_shell('''
bootstrap_source_module scripts/common/credentials.sh
ln "$INSTALLER_RUNTIME_DIR/bootstrap/modules/scripts/common/credentials.sh" "$INSTALLER_RUNTIME_DIR/alias"
if bootstrap_source_module scripts/common/credentials.sh; then exit 88; fi
''')
        self.assert_ok(result)

    def test_remote_loading_without_authenticated_payload_does_not_contact_network(self):
        result = self.run_shell('''
rm "$INSTALLER_RUNTIME_DIR/bootstrap/payload.ready"
bootstrap_persist_seed_source https://never-fetch.invalid/d-i/forky
source_transfer() { printf 'CONTACTED\\n'; return 99; }
if bootstrap_source_module scripts/common/credentials.sh; then exit 88; fi
''')
        self.assert_ok(result)
        self.assertNotIn('CONTACTED', result.stdout + result.stderr)
        self.assertIn('requires the authenticated payload', result.stderr)

    def test_traversal_and_unregistered_module_prefixes_are_rejected(self):
        result = self.run_shell('''
for path in ../escape.sh /etc/passwd scripts/common/../escape.sh hooks/target/run.sh; do
  if bootstrap_source_module "$path"; then exit 88; fi
done
''')
        self.assert_ok(result)

if __name__ == '__main__': unittest.main()
