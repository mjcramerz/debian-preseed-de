"""Unexecuted release fixtures: fresh shell, hash gate, target call and cleanup.

Vendor transfer is replaced with a private-file copy. Target extraction maps
only the reviewed wallpaper operation into the fixture tree. Theme target
execution is a recording stub, not an extraction or native tar check. No
network, chroot, service, device or installed management helper is used.
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
    match = re.search(r'^' + re.escape(name) + r'\(\) [({]\n.*?^[)}];?\n',
                      text, re.M | re.S)
    if match is None:
        raise AssertionError('missing shell definition: ' + name)
    return match[0]


class DesktopReleaseDownloads(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='desktop-release-fixture-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        for relative in ('home', 'bin', 'scratch', 'runtime', 'source', 'target/tmp',
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
            ('scripts/desktop/components/appearance.sh', 'desktop_extract_theme_release'),
        ]
        self.definitions = self.root / 'definitions.sh'
        self.definitions.write_text('''installer_fatal() {
  printf 'fatal: %s\\n' "$*" >&2
  exit 1
}
desktop_log() { printf '%s\\n' "$*" >>"$FIXTURE_ROOT/events.log"; }
target_asset_host_path() {
  case "$1" in
    /tmp/installer-desktop-wallpapers.tar.gz|/tmp/installer-desktop-themes.tar.gz)
      printf '%s/target%s\\n' "$FIXTURE_ROOT" "$1" ;;
    *) return 93 ;;
  esac
}
run_in_target() { printf 'unexpected target call\\n' >&2; return 94; }
attempt_in_target() { printf 'unexpected target attempt\\n' >&2; return 94; }
''' + '\n'.join(function_source(*definition) for definition in definitions))

    def invoke(self, body: str, *, expected_sha256: str | None = None,
               maximum: int = 1048576, transport_status: int = 0):
        # No inherited HOME, session sockets, credentials or environment/PATH.
        environment = {
            'PATH': str(self.root / 'bin') + ':/usr/bin:/bin',
            'LC_ALL': 'C', 'HOME': str(self.root / 'home'),
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

    def use_http_transport(self, redirect: str, second_redirect: str = ''):
        # The real HTTP/redirect functions run against a fake wget that never
        # opens a socket. Diagnostics and clock/supervisor hooks are private.
        # These fixtures do not establish native wget/TLS or timeout behavior.
        names = ('installer_bounded_seconds', 'source_validate_url', 'source_effective_url',
                 'source_http_get', 'source_validate_relative', 'source_fetch_external')
        self.transport.write_text('''source_fetch() { return 96; }
source_error() { printf 'transport: %s\\n' "$*" >&2; return 1; }
source_insecure() { return 1; }
source_monotonic_seconds() { printf '100\\n'; }
installer_run_bounded() { shift; "$@"; }
''' + '\n'.join(function_source('scripts/common/source.sh', name) for name in names))
        (self.root / 'redirect').write_text(redirect + '\n')
        (self.root / 'second-redirect').write_text(second_redirect + '\n' if second_redirect else '')
        wget = self.root / 'bin/wget'
        wget.write_text('''#!/bin/sh
set -eu
if [ "$#" -eq 1 ] && [ "$1" = --help ]; then
  printf '%s\\n' '--max-redirect'
  exit 0
fi
output=
url=
while [ "$#" -gt 0 ]; do
  case "$1" in
    -O) output=$2; shift 2 ;;
    -T) shift 2 ;;
    --no-config|-S|--tries=1|--max-redirect=0) shift ;;
    https://*|http://*|ftp://*) url=$1; shift ;;
    *) exit 2 ;;
  esac
done
case "$output" in "$FIXTURE_ROOT"/*) ;; *) exit 93 ;; esac
[ -n "$url" ] || exit 2
printf '%s\\n' "$url" >>"$FIXTURE_ROOT/requests.log"
: >"$output"
location=
case "$url" in
  https://github.com/*)
    IFS= read -r location <"$FIXTURE_ROOT/redirect"
    ;;
  https://release-assets.githubusercontent.com/*)
    if [ -s "$FIXTURE_ROOT/second-redirect" ]; then
      IFS= read -r location <"$FIXTURE_ROOT/second-redirect"
    fi
    ;;
esac
if [ -n "$location" ]; then
  printf '  HTTP/1.1 302 Found\\n  Location: %s\\n' "$location" >&2
  exit 8
fi
printf '  HTTP/1.1 200 OK\\n' >&2
cp -- "$FIXTURE_ARCHIVE" "$output"
''')
        wget.chmod(0o755)

    def test_both_release_downloads_accept_exact_github_asset_hosts(self):
        expected = []
        for host in ('release-assets.githubusercontent.com', 'objects.githubusercontent.com',
                     'github-releases.githubusercontent.com'):
            redirect = 'https://' + host + '/asset?signature=fixture&name=release.tar.gz'
            self.use_http_transport(redirect)
            for filename in ('wallpapers.tar.gz', 'desktop-themes.tar.gz'):
                with self.subTest(host=host, filename=filename):
                    result = self.download(filename)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual((self.root / 'download.tar.gz').read_bytes(),
                                     self.archive.read_bytes())
                    expected.extend([
                        'https://github.com/mjcramerz/themes/releases/download/themes-v0.0.1/' + filename,
                        redirect,
                    ])
        self.assertEqual((self.root / 'requests.log').read_text().splitlines(), expected)

    def test_unsafe_redirect_is_rejected_before_contact_or_destination_replacement(self):
        destination = self.root / 'download.tar.gz'
        destination.write_bytes(b'previous owned download')
        for redirect in ('http://release-assets.githubusercontent.com/asset',
                         'ftp://release-assets.githubusercontent.com/asset',
                         'https://user:password@release-assets.githubusercontent.com/asset',
                         'https://release-assets.githubusercontent.com.example.invalid/asset',
                         'https://example.invalid/asset'):
            with self.subTest(redirect=redirect):
                self.use_http_transport(redirect)
                (self.root / 'requests.log').write_text('')
                result = self.download('wallpapers.tar.gz')
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual((self.root / 'requests.log').read_text().splitlines(), [
                    'https://github.com/mjcramerz/themes/releases/download/themes-v0.0.1/wallpapers.tar.gz'])
                self.assertEqual(destination.read_bytes(), b'previous owned download')
                self.assertFalse((self.root / 'events.log').exists())
                self.assertEqual(list(self.root.glob('download.tar.gz.external.*')), [])

    def test_redirect_from_approved_asset_host_is_checked_again(self):
        first = 'https://release-assets.githubusercontent.com/asset'
        self.use_http_transport(first, 'https://example.invalid/escape')
        result = self.download('wallpapers.tar.gz')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.root / 'requests.log').read_text().splitlines(), [
            'https://github.com/mjcramerz/themes/releases/download/themes-v0.0.1/wallpapers.tar.gz',
            first,
        ])
        self.assertFalse((self.root / 'download.tar.gz').exists())

    def test_repository_scope_still_rejects_github_asset_authority(self):
        self.use_http_transport('https://release-assets.githubusercontent.com/asset')
        result = self.invoke('''installer_load_source_library "$INSTALLER_SOURCE_ROOT"
source_http_get \
  https://github.com/mjcramerz/themes/releases/download/themes-v0.0.1/wallpapers.tar.gz \
  "$FIXTURE_DESTINATION"
''')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('repository redirect leaves its approved authority', result.stderr)
        self.assertEqual(len((self.root / 'requests.log').read_text().splitlines()), 1)
        self.assertFalse((self.root / 'download.tar.gz').exists())

    def test_non_release_github_url_does_not_receive_asset_host_exception(self):
        self.use_http_transport('https://release-assets.githubusercontent.com/asset')
        result = self.invoke('''installer_load_source_library "$INSTALLER_SOURCE_ROOT"
source_fetch_external https://github.com/mjcramerz/themes/raw/main \
  wallpapers.tar.gz "$FIXTURE_DESTINATION" 0600
''')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('external redirect leaves its approved authority', result.stderr)
        self.assertEqual(len((self.root / 'requests.log').read_text().splitlines()), 1)

    def test_redirected_archive_still_requires_its_configured_sha256(self):
        self.use_http_transport('https://release-assets.githubusercontent.com/asset')
        result = self.download('desktop-themes.tar.gz', expected_sha256='0' * 64)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SHA-256 mismatch', result.stderr)
        self.assertEqual(len((self.root / 'requests.log').read_text().splitlines()), 2)
        self.assertFalse((self.root / 'events.log').exists())

    def extract_wallpapers(self, **options):
        # Validate the exact target command and replace both target paths.
        # The reviewed body invokes only install/tar/find/chmod/rm on these
        # private paths; input archives below contain only a fixture member.
        return self.invoke('''attempt_in_target() {
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

    def extract_themes(self, **options):
        # Record the target command without executing it. The destination is
        # private even if a regression sends it to installer-side tools.
        stage = self.root / 'target/usr/local/share/labwc-appearance/.installer-themes'
        stage.mkdir(parents=True, exist_ok=True)
        (stage / 'retained-evidence').write_bytes(b'previous staging evidence')
        return self.invoke('''attempt_in_target() {
  [ "$#" -eq 8 ] || return 94
  [ "$1" = 'extract pinned desktop theme release archive' ] || return 94
  [ "$2" = /bin/sh ] && [ "$3" = -eu ] && [ "$4" = -c ] || return 94
  [ "$6" = sh ] || return 94
  [ "$7" = /tmp/installer-desktop-themes.tar.gz ] || return 94
  [ "$8" = "$FIXTURE_ROOT/target/usr/local/share/labwc-appearance/.installer-themes" ] || return 94
  [ -f "$FIXTURE_ROOT/target/tmp/installer-desktop-themes.tar.gz" ] || return 94
  printf '%s\\n' "$5" >"$FIXTURE_ROOT/theme-target-command.sh"
  [ ! -f "$FIXTURE_ROOT/fail-target" ] || return 73
  rm -f -- "$FIXTURE_ROOT/target/tmp/installer-desktop-themes.tar.gz"
}
FIXTURE_DESTINATION="$TMP_ENV_DIR/desktop-themes.tar.gz"
export FIXTURE_DESTINATION
LABWC_DESKTOP_THEMES_TAG=themes-v0.0.1
LABWC_DESKTOP_THEMES_URL=https://github.com/mjcramerz/themes/releases/download/themes-v0.0.1/desktop-themes.tar.gz
LABWC_DESKTOP_THEMES_SHA256=$FIXTURE_SHA256
LABWC_DESKTOP_THEMES_MAXIMUM_BYTES=$FIXTURE_MAXIMUM
desktop_extract_theme_release "$FIXTURE_ROOT/target/usr/local/share/labwc-appearance/.installer-themes"
''', **options)

    def test_theme_extraction_delegates_to_target_and_cleans_both_archives(self):
        result = self.extract_themes()
        self.assertEqual(result.returncode, 0, result.stderr)
        command = (self.root / 'theme-target-command.sh').read_text()
        self.assertIn('/usr/bin/tar -xzf "$archive" -C "$destination"', command)
        self.assertIn('--strip-components=1', command)
        self.assertFalse((self.root / 'target/tmp/installer-desktop-themes.tar.gz').exists())
        self.assertEqual(list((self.root / 'scratch').iterdir()), [])
        self.assertIn('extracted_verified_release label=desktop-themes',
                      (self.root / 'events.log').read_text())

    def test_theme_target_failure_cleans_archives_and_retains_staging_evidence(self):
        (self.root / 'fail-target').write_bytes(b'injected target failure')
        result = self.extract_themes()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('desktop theme release extraction failed', result.stderr)
        stage = self.root / 'target/usr/local/share/labwc-appearance/.installer-themes'
        self.assertEqual((stage / 'retained-evidence').read_bytes(), b'previous staging evidence')
        self.assertFalse((self.root / 'target/tmp/installer-desktop-themes.tar.gz').exists())
        self.assertEqual(list((self.root / 'scratch').iterdir()), [])
        self.assertNotIn('extracted_verified_release', (self.root / 'events.log').read_text())

    def test_theme_sha_failure_stops_before_target_extraction(self):
        result = self.extract_themes(expected_sha256='0' * 64)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SHA-256 mismatch', result.stderr)
        self.assertFalse((self.root / 'theme-target-command.sh').exists())
        self.assertFalse((self.root / 'target/tmp/installer-desktop-themes.tar.gz').exists())
        self.assertEqual(list((self.root / 'scratch').iterdir()), [])


if __name__ == '__main__':
    unittest.main()
