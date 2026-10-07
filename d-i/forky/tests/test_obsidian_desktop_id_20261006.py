"""Current Obsidian desktop ID across installer, update worker and launcher sync.

Debian archives are synthetic fixtures. Native package inspection is real;
APT/chroot installation, prevalidated release metadata, HTTP transport and
vendor-root ownership are explicit test doubles.
No vendor executable, maintainer script, host service or network request runs.
"""
from __future__ import annotations

import configparser
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import types
import unittest
from unittest import mock

from payload_fixture import logging_text

SEED = Path(__file__).resolve().parents[1]
TARGET = SEED / 'hooks/target'
DESKTOP_ID = 'md.obsidian.Obsidian.desktop'
DESKTOP_PATH = '/usr/share/applications/' + DESKTOP_ID
DESKTOP_TEXT = '''[Desktop Entry]
Type=Application
Name=Obsidian
Exec=/opt/Obsidian/obsidian %U
Icon=obsidian
Terminal=false
StartupWMClass=md.obsidian.Obsidian
MimeType=text/markdown;x-scheme-handler/obsidian;
Categories=Office;
'''


@unittest.skipUnless(shutil.which('dpkg-deb'), 'native dpkg-deb unavailable')
class ObsidianPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.library_temporary = tempfile.TemporaryDirectory(prefix='obsidian-perl-')
        cls.addClassCleanup(cls.library_temporary.cleanup)
        cls.library = Path(cls.library_temporary.name)
        perl_source = TARGET / 'usr/local/lib/perl5/site_perl'
        for name in ('apt-repo-local', 'runtime'):
            shutil.copytree(perl_source / name, cls.library / name, symlinks=True)
        for template in cls.library.rglob('*.pm.tmpl'):
            destination = template.with_name(template.name[:-5])
            if destination.exists():
                raise AssertionError('ambiguous copied Perl template')
            destination.write_text(logging_text(template.read_text(encoding='utf-8')), encoding='utf-8')
            template.unlink()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='obsidian-deb-layout-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.target = self.root / 'target'
        self.target.mkdir()
        self.tree = self.root / 'package'
        (self.tree / 'DEBIAN').mkdir(parents=True)
        (self.tree / 'DEBIAN').chmod(0o755)
        (self.tree / 'DEBIAN/control').write_text(
            'Package: obsidian\nVersion: 1.14.4\nArchitecture: amd64\n'
            'Maintainer: Fixture <fixture@example.invalid>\nDescription: layout fixture\n', encoding='utf-8')
        (self.tree / 'DEBIAN/control').chmod(0o644)
        for name, content, mode in (
            ('opt/Obsidian/obsidian', '#!/bin/sh\nexit 94\n', 0o755),
            ('opt/Obsidian/libffmpeg.so', 'fixture library; never loaded\n', 0o644),
            (DESKTOP_PATH.lstrip('/'), DESKTOP_TEXT, 0o644),
        ):
            path = self.tree / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
            path.chmod(mode)
        self.archive = self.target / 'fixture.deb'
        self.marker = self.root / 'apt-called'
        self.software = (SEED / 'scripts/late/software.sh.tmpl').read_text(encoding='utf-8')

    def build_archive(self):
        result = subprocess.run(['dpkg-deb', '--build', '--root-owner-group', str(self.tree), str(self.archive)],
                                capture_output=True, text=True, encoding='utf-8', timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def run_installer(self, source=None):
        source = self.software if source is None else source
        definitions = source[:source.index('software_validate_abs_path "target root"')]
        for name in ('software_deb_contains_path', 'software_install_deb'):
            start = source.index(name + '() {')
            definitions += '\n' + source[start:source.index('\n}\n', start) + 2]
        start = source.index('software_install_deb \\\n  "Obsidian"')
        block = source[start:source.index('# Bootstrap only the profile-pinned Tomat', start)]
        # Execute both payload and post-install checks, but replace root/chroot
        # and APT mutations with a strict fixture command dispatcher.
        fixture = r'''
chroot() {
  [ "$1" = "$FIXTURE_ROOT" ] || return 90
  shift
  if [ "$1" = /usr/bin/env ]; then
    shift
    [ "$1" != -i ] || shift
    while [ "$#" -gt 0 ]; do
      case "$1" in *=*) shift ;; *) break ;; esac
    done
  fi
  fixture_command=$1
  shift
  case "$fixture_command" in
    /usr/bin/dpkg-deb)
      fixture_operation=$1; fixture_package=$2; shift 2
      /usr/bin/dpkg-deb "$fixture_operation" "${FIXTURE_ROOT}${fixture_package}" "$@" ;;
    /usr/bin/dpkg)
      [ "$1" = --validate-version ] || return 91
      /usr/bin/dpkg "$@" ;;
    /usr/bin/apt-get)
      printf 'fixture APT\n' >"$FIXTURE_MARKER"
      /usr/bin/dpkg-deb --extract "$FIXTURE_ROOT/fixture.deb" "$FIXTURE_ROOT" ;;
    /usr/bin/dpkg-query)
      if [ "$2" = '-f=${Status}' ]; then printf 'install ok installed'; else printf '1.14.4\n'; fi ;;
    /usr/bin/test)
      /usr/bin/test "$1" "${FIXTURE_ROOT}$2" ;;
    /usr/bin/sha256sum)
      /usr/bin/sha256sum "${FIXTURE_ROOT}$1" ;;
    /usr/bin/desktop-file-validate)
      /usr/bin/desktop-file-validate "${FIXTURE_ROOT}$1" ;;
    /usr/bin/update-desktop-database)
      /usr/bin/update-desktop-database "${FIXTURE_ROOT}$1" ;;
    *) printf 'unexpected fixture command: %s\n' "$fixture_command" >&2; return 92 ;;
  esac
}
software_store_managed_deb_archive() { managed_archive_path=/fixture.deb; }
software_refresh_managed_deb_repository() { :; }
target_root=$FIXTURE_ROOT
obsidian_deb=/fixture.deb
obsidian_version=1.14.4
'''
        script = definitions + '\n' + fixture + '\n' + block
        return subprocess.run(['/bin/sh', '-eu', '-c', script], text=True, encoding='utf-8',
                              capture_output=True, timeout=15,
                              env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C',
                                   'FIXTURE_ROOT': str(self.target), 'FIXTURE_MARKER': str(self.marker)})

    def validate_worker_spec(self):
        code = r'''
use strict; use warnings;
use JSON::PP qw(encode_json);
use APTRepoLocal::Servicing::CLI;
use APTRepoLocal::Servicing::Deb;
my ($spec) = grep { $_->{name} eq 'obsidian' } APTRepoLocal::Servicing::CLI->_release_deb_specs();
defined $spec or die "missing Obsidian package specification\n";
my $deb = APTRepoLocal::Servicing::Deb->new(repository => bless({}, 'FixtureUnused'));
print encode_json($deb->validate_spec($ARGV[0], $spec)), "\n";
'''
        return subprocess.run(['perl', '-I', str(self.library / 'apt-repo-local'),
                               '-I', str(self.library / 'runtime'), '-e', code, str(self.archive)],
                              text=True, encoding='utf-8', capture_output=True, timeout=15,
                              env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})

    def validate_download_adapter(self):
        # The unchanged GitHub metadata size floor is not the contract under
        # test. Supply prevalidated fixture metadata, then run the actual
        # adapter's digest/size and native Debian payload validation.
        code = r'''
use strict; use warnings;
use JSON::PP qw(encode_json);
use Digest::SHA;
use APTRepoLocal::Servicing::Obsidian;
use APTRepoLocal::Servicing::Deb;
{
    package FixtureHTTP;
    use File::Copy qw(copy);
    sub download {
        my ($self, %args) = @_;
        if ($args{label} eq 'Obsidian release metadata') {
            open my $file, '>', $args{destination} or die "fixture metadata open: $!\n";
            print {$file} "{}\n" or die "fixture metadata write: $!\n";
            close $file or die "fixture metadata close: $!\n";
        } elsif ($args{label} eq 'Obsidian' && $args{url} eq $self->{release}{url}) {
            copy($self->{archive}, $args{destination}) or die "fixture archive copy: $!\n";
        } else {
            die "unexpected fixture HTTP request\n";
        }
    }
    package FixtureObsidian;
    use parent 'APTRepoLocal::Servicing::Obsidian';
    sub _release { return $_[0]->http()->{release}; }
}
my ($archive, $work) = @ARGV;
open my $file, '<:raw', $archive or die "fixture archive open: $!\n";
my $sha256 = Digest::SHA->new(256)->addfile($file)->hexdigest;
close $file or die "fixture archive close: $!\n";
my $http = bless {archive => $archive, release => {
    version => '1.14.4', size => -s $archive, sha256 => $sha256,
    url => 'https://github.com/obsidianmd/obsidian-releases/releases/download/v1.14.4/obsidian_1.14.4_amd64.deb',
}}, 'FixtureHTTP';
my $deb = APTRepoLocal::Servicing::Deb->new(repository => bless({}, 'FixtureUnused'));
my $result = FixtureObsidian->new(http => $http, deb => $deb)->download($work);
print encode_json($result->{metadata}), "\n";
'''
        work = self.root / 'download-work'
        work.mkdir()
        return subprocess.run(['perl', '-I', str(self.library / 'apt-repo-local'),
                               '-I', str(self.library / 'runtime'), '-e', code,
                               str(self.archive), str(work)], text=True, encoding='utf-8',
                              capture_output=True, timeout=15,
                              env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})

    @unittest.skipUnless(shutil.which('desktop-file-validate') and shutil.which('update-desktop-database'),
                         'native desktop-file-utils unavailable')
    def test_current_desktop_id_passes_installer_and_post_install_checks(self):
        self.build_archive()
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.marker.exists())
        self.assertTrue((self.target / DESKTOP_PATH.lstrip('/')).is_file())

    def test_old_installer_assumption_reproduces_the_reported_failure(self):
        self.build_archive()
        previous = self.software.replace(DESKTOP_ID, 'obsidian.desktop')
        result = self.run_installer(previous)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('payload is missing desktop entry: /usr/share/applications/obsidian.desktop', result.stderr)
        self.assertFalse(self.marker.exists())

    def test_missing_current_desktop_is_refused_before_installation(self):
        (self.tree / DESKTOP_PATH.lstrip('/')).rename(self.tree / 'usr/share/applications/obsidian.desktop')
        self.build_archive()
        result = self.run_installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('payload is missing desktop entry: ' + DESKTOP_PATH, result.stderr)
        self.assertFalse(self.marker.exists())

    def test_update_worker_spec_accepts_current_package_layout(self):
        self.build_archive()
        result = self.validate_worker_spec()
        self.assertEqual(result.returncode, 0, result.stderr)
        metadata = json.loads(result.stdout.splitlines()[-1])
        self.assertEqual(metadata, {'package': 'obsidian', 'version': '1.14.4', 'architecture': 'amd64'})

    def test_update_worker_keeps_the_desktop_payload_gate(self):
        (self.tree / DESKTOP_PATH.lstrip('/')).unlink()
        self.build_archive()
        result = self.validate_worker_spec()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('missing its expected desktop entry', result.stderr)

    def test_download_adapter_accepts_current_payload_after_digest_validation(self):
        self.build_archive()
        result = self.validate_download_adapter()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout.splitlines()[-1]),
                         {'package': 'obsidian', 'version': '1.14.4', 'architecture': 'amd64'})

    def test_download_adapter_rejects_missing_desktop_payload(self):
        (self.tree / DESKTOP_PATH.lstrip('/')).unlink()
        self.build_archive()
        result = self.validate_download_adapter()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('missing its expected desktop entry', result.stderr)


class ObsidianLauncherTests(unittest.TestCase):
    def setUp(self):
        original_umask = os.umask(0o077)
        os.umask(original_umask)
        self.addCleanup(os.umask, original_umask)
        temporary = tempfile.TemporaryDirectory(prefix='obsidian-launcher-layout-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.vendor = self.root / 'vendor'
        self.local = self.root / 'local'
        self.home = self.root / 'home'
        for directory in (self.vendor, self.local, self.home):
            directory.mkdir()
        path = TARGET / 'usr/local/bin/labwc-sync-application-launchers.tmpl'
        self.sync = types.ModuleType('obsidian_launcher_fixture')
        self.sync.__file__ = str(path)
        source = path.read_text(encoding='utf-8').replace(
            '__INSTALLER_LABWC_MANAGED_APP_DEFAULT_EXEC__', '/usr/local/bin/labwc-app auto')
        exec(compile(source, str(path), 'exec'), self.sync.__dict__)
        self.sync.SYSTEM_APPLICATION_DIR = str(self.vendor)
        self.sync.LOCAL_APPLICATION_DIR = str(self.local)
        self.config = next(value for value in self.sync.APP_CONFIG if value['action_app'] == 'obsidian')

    def test_current_id_is_preferred_and_legacy_vendor_entry_is_discoverable(self):
        (self.vendor / 'obsidian.desktop').write_text(DESKTOP_TEXT, encoding='utf-8')
        self.assertEqual(self.sync.find_desktop_file(self.config['desktop_names'])[0], 'obsidian.desktop')
        (self.vendor / DESKTOP_ID).write_text(DESKTOP_TEXT, encoding='utf-8')
        self.assertEqual(self.sync.find_desktop_file(self.config['desktop_names'])[0], DESKTOP_ID)

    def test_sync_preserves_native_id_mime_and_window_class_under_managed_wrapper(self):
        (self.vendor / DESKTOP_ID).write_text(DESKTOP_TEXT, encoding='utf-8')
        uid, gid = os.getuid(), os.getgid()
        with mock.patch.object(self.sync, 'APP_CONFIG', (self.config,)), \
             mock.patch.object(self.sync, 'validate_account_context', return_value=(uid, gid)), \
             mock.patch.object(self.sync, 'load_acceleration_availability', return_value={'intel': True, 'nvidia': True}), \
             mock.patch.object(self.sync, 'read_system_desktop_text',
                               side_effect=lambda path: self.sync.read_regular_text(path, {uid})), \
             mock.patch.object(self.sync, 'remove_unmanaged_tuta_launchers', return_value=0), \
             mock.patch.object(self.sync, 'synchronize_bitwarden_autostart', return_value=False), \
             mock.patch.object(self.sync.sys, 'argv', ['sync', 'fixture', str(self.home)]), \
             mock.patch.dict(os.environ, {'XDG_DATA_HOME': str(self.home / '.local/share')}), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.sync.main(), 0)
        destination = self.home / '.local/share/applications' / DESKTOP_ID
        self.assertTrue(destination.is_file())
        self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
        settings = configparser.ConfigParser(interpolation=None)
        settings.optionxform = str
        settings.read(destination, encoding='utf-8')
        entry = settings['Desktop Entry']
        self.assertEqual(entry['Exec'], '/usr/local/bin/labwc-app auto obsidian %U')
        self.assertEqual(entry['StartupWMClass'], 'md.obsidian.Obsidian')
        self.assertEqual(entry['MimeType'], 'text/markdown;x-scheme-handler/obsidian;')
        self.assertEqual(entry['Icon'], 'obsidian')
        self.assertEqual(settings['Desktop Action IntelAccelerated']['Exec'],
                         '/usr/local/bin/labwc-app intel obsidian %U')
        self.assertFalse((destination.parent / 'obsidian.desktop').exists())


if __name__ == '__main__':
    unittest.main()
