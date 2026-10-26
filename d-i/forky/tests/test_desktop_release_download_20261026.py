"""Unexecuted release-download fixtures: fresh shell, hash gate and cleanup.

Vendor transfer is replaced with a private-file copy. Target extraction maps
only the reviewed wallpaper operation into the fixture tree. No network,
chroot, service, device or installed management helper is used.
"""
from __future__ import annotations

from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
from isolation import require_test_isolation as _require_test_isolation
_require_test_isolation()

import hashlib
import io
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import unittest

SEED = Path(__file__).resolve().parents[1]


def function_source(relative: str, name: str) -> str:
    """Copy a reviewed shell definition as data; never load a repository module."""
    text = (SEED / relative).read_text()
    match = re.search(r'^' + re.escape(name) + r'\(\) [({]\n.*?^[)}]\n',
                      text, re.M | re.S)
    if match is None:
        raise AssertionError('missing shell definition: ' + name)
    return match[0]


class DesktopReleaseDownloads(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='desktop-release-fixture-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        for relative in ('home', 'scratch', 'runtime', 'source', 'target/tmp',
                         'target/usr/share/backgrounds/desktop'):
            (self.root / relative).mkdir(parents=True, exist_ok=True)
        self.archive = self.root / 'input.tar.gz'
        self.archive.write_bytes(b'inert release bytes\n')
        self.transport = self.root / 'transport.sh'
        self.transport.write_text('''source_fetch() { return 96; }
source_fetch_external() (
  set -eu
  [ "$#" -eq 4 ] && [ "$3" = "$FIXTURE_DESTINATION" ] || exit 92
  printf '%s|%s|%s\\n' "$1" "$2" "$4" >>"$FIXTURE_ROOT/transfer.log"
  [ "$FIXTURE_TRANSPORT_STATUS" = 0 ] || exit "$FIXTURE_TRANSPORT_STATUS"
  cp -- "$FIXTURE_ARCHIVE" "$3"
  chmod "$4" "$3"
)
''')
        definitions = [
            ('scripts/common/modules/context-target.sh', 'installer_load_source_library'),
            ('scripts/common/modules/repository-apt.sh', 'installer_fetch_url'),
            ('scripts/desktop/components/release-assets.sh', 'desktop_validate_release_pin'),
            ('scripts/desktop/components/release-assets.sh', 'desktop_download_release_archive'),
            ('scripts/desktop/components/artifacts-identities.sh',
             'desktop_extract_role_wallpaper_archive'),
        ]
        self.definitions = self.root / 'definitions.sh'
        self.definitions.write_text('''installer_fatal() {
  printf 'fatal: %s\\n' "$*" >&2
  exit 1
}
desktop_log() { printf '%s\\n' "$*" >>"$FIXTURE_ROOT/events.log"; }
target_asset_host_path() {
  [ "$1" = /tmp/installer-desktop-wallpapers.tar.gz ] || return 93
  printf '%s/target/tmp/installer-desktop-wallpapers.tar.gz\\n' "$FIXTURE_ROOT"
}
run_in_target() { printf 'unexpected target call\\n' >&2; return 94; }
''' + '\n'.join(function_source(*definition) for definition in definitions))

    def invoke(self, body: str, *, expected_sha256: str | None = None,
               maximum: int = 1048576, transport_status: int = 0):
        # No inherited HOME, session sockets, credentials or environment/PATH.
        environment = {
            'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'HOME': str(self.root / 'home'),
            'FIXTURE_ROOT': str(self.root), 'FIXTURE_ARCHIVE': str(self.archive),
            'FIXTURE_DESTINATION': str(self.root / 'download.tar.gz'),
            'FIXTURE_TRANSPORT_STATUS': str(transport_status),
            'FIXTURE_SHA256': expected_sha256 or hashlib.sha256(self.archive.read_bytes()).hexdigest(),
            'FIXTURE_MAXIMUM': str(maximum),
            'INSTALLER_RUNTIME_DIR': str(self.root / 'runtime'),
            'INSTALLER_SOURCE_ROOT': str(self.root / 'source'),
            'INSTALLER_SOURCE_LIBRARY': str(self.transport),
            'TMP_ENV_DIR': str(self.root / 'scratch'),
        }
        # The role's original failure occurs with no transport functions in
        # the fresh shell. Only installer_fetch_url may load the fixture one.
        script = '''. "$1"
if command -v source_fetch_external >/dev/null 2>&1; then exit 95; fi
''' + body
        return subprocess.run(['/bin/sh', '-eu', '-c', script, 'fixture', str(self.definitions)],
                              cwd=self.root, env=environment, text=True,
                              capture_output=True, timeout=10)

    def download(self, filename: str, **options):
        # Only these fixed fixture filenames may enter the command text.
        self.assertIn(filename, ('wallpapers.tar.gz', 'desktop-themes.tar.gz'))
        return self.invoke('''desktop_download_release_archive fixture themes-v0.0.1 \
  "https://github.com/mjcramerz/themes/releases/download/themes-v0.0.1/''' + filename + '''" \
  "$FIXTURE_SHA256" ''' + filename + ''' "$FIXTURE_DESTINATION" "$FIXTURE_MAXIMUM"
''', **options)

    def test_both_releases_load_transport_in_a_fresh_role_shell(self):
        for filename in ('wallpapers.tar.gz', 'desktop-themes.tar.gz'):
            with self.subTest(filename=filename):
                result = self.download(filename)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((self.root / 'download.tar.gz').read_bytes(), self.archive.read_bytes())
                self.assertEqual((self.root / 'download.tar.gz').stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.root / 'transfer.log').read_text().splitlines(), [
            'https://github.com/mjcramerz/themes/releases/download/themes-v0.0.1|' + name + '|0600'
            for name in ('wallpapers.tar.gz', 'desktop-themes.tar.gz')])

    def test_transport_failure_preserves_previous_download_and_stops(self):
        destination = self.root / 'download.tar.gz'
        destination.write_bytes(b'previous owned download')
        result = self.download('wallpapers.tar.gz', transport_status=72)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('failed to download fixture release archive', result.stderr)
        self.assertNotIn('not found', result.stderr)
        self.assertEqual(destination.read_bytes(), b'previous owned download')
        self.assertFalse((self.root / 'events.log').exists())

    def test_hash_and_size_failures_never_report_a_verified_release(self):
        for options, message in (({'expected_sha256': '0' * 64}, 'SHA-256 mismatch'),
                                 ({'maximum': 1}, 'exceeds 1 bytes')):
            with self.subTest(message=message):
                result = self.download('desktop-themes.tar.gz', **options)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
                self.assertFalse((self.root / 'events.log').exists())

    def extract_wallpapers(self, **options):
        # Validate the exact target command and replace both target paths.
        # The reviewed body invokes only install/tar/find/chmod/rm on these
        # private paths; input archives below contain only a fixture member.
        return self.invoke('''run_in_target() {
  [ "$#" -eq 8 ] || return 94
  [ "$1" = 'extract managed desktop wallpaper archive' ] || return 94
  [ "$2" = /bin/sh ] && [ "$3" = -eu ] && [ "$4" = -c ] || return 94
  [ "$6" = sh ] || return 94
  [ "$7" = /tmp/installer-desktop-wallpapers.tar.gz ] || return 94
  [ "$8" = /usr/share/backgrounds/desktop ] || return 94
  printf '%s\\n' "$5" >"$FIXTURE_ROOT/extract.sh"
  /bin/sh -eu "$FIXTURE_ROOT/extract.sh" \
    "$FIXTURE_ROOT/target/tmp/installer-desktop-wallpapers.tar.gz" \
    "$FIXTURE_ROOT/target/usr/share/backgrounds/desktop"
}
FIXTURE_DESTINATION="$TMP_ENV_DIR/desktop-wallpapers.$$.tar.gz"
export FIXTURE_DESTINATION
LABWC_WALLPAPERS_TAG=themes-v0.0.1
LABWC_WALLPAPERS_URL=https://github.com/mjcramerz/themes/releases/download/themes-v0.0.1/wallpapers.tar.gz
LABWC_WALLPAPERS_SHA256=$FIXTURE_SHA256
LABWC_WALLPAPERS_MAXIMUM_BYTES=$FIXTURE_MAXIMUM
desktop_extract_role_wallpaper_archive
''', **options)

    def test_successful_extraction_removes_both_temporary_archives(self):
        with tarfile.open(self.archive, 'w:gz') as archive:
            member = tarfile.TarInfo('fixture-wallpaper.jpg')
            member.size = len(b'fixture wallpaper')
            archive.addfile(member, io.BytesIO(b'fixture wallpaper'))
        result = self.extract_wallpapers()
        self.assertEqual(result.returncode, 0, result.stderr)
        wallpaper = self.root / 'target/usr/share/backgrounds/desktop/fixture-wallpaper.jpg'
        self.assertEqual(wallpaper.read_bytes(), b'fixture wallpaper')
        self.assertEqual(wallpaper.stat().st_mode & 0o777, 0o644)
        self.assertFalse((self.root / 'target/tmp/installer-desktop-wallpapers.tar.gz').exists())
        self.assertEqual(list((self.root / 'scratch').iterdir()), [])
        self.assertIn('extracted_wallpaper_archive', (self.root / 'events.log').read_text())

    def test_extraction_failure_cleans_archives_and_preserves_existing_wallpaper(self):
        previous = self.root / 'target/usr/share/backgrounds/desktop/previous.jpg'
        previous.write_bytes(b'previous wallpaper')
        result = self.extract_wallpapers()  # SHA-valid bytes, invalid tar.
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('failed to extract the verified desktop wallpaper release archive', result.stderr)
        self.assertEqual(previous.read_bytes(), b'previous wallpaper')
        self.assertFalse((self.root / 'target/tmp/installer-desktop-wallpapers.tar.gz').exists())
        self.assertEqual(list((self.root / 'scratch').iterdir()), [])
        self.assertNotIn('extracted_wallpaper_archive', (self.root / 'events.log').read_text())


if __name__ == '__main__':
    unittest.main()
