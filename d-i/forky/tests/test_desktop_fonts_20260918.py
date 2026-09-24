"""Pinned-font installer tests. No released/proprietary font bytes are bundled.

Archives are local synthetic fixtures. One optional test exercises real
fontconfig as a non-root uid using an already installed system test font.
"""
from payload_fixture import copyfile as payload_copyfile, installed_argv as payload_installed_argv, source_exists as payload_source_exists, source_stat as payload_source_stat
from payload_fixture import read_bytes as payload_read_bytes, read_text as payload_read_text
import hashlib
import io
import json
import os
from pathlib import Path
import pwd
import shutil
import stat
import subprocess
import tarfile
import tempfile
import types
import unittest
from unittest import mock

FORKY = Path(__file__).resolve().parents[1]
SOURCE = FORKY / 'scripts/desktop/fonts-install.py'


def load():
    module = types.ModuleType('font_installer_fixture')
    module.__file__ = str(SOURCE)
    exec(compile(payload_read_bytes(SOURCE), str(SOURCE), 'exec'), module.__dict__)
    return module


class FontInstallTests(unittest.TestCase):
    def setUp(self):
        self.m = load()
        self.temp = tempfile.TemporaryDirectory(prefix='desktop-font-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root.chmod(0o755)
        self.cache = self.root / 'cache'; self.cache.mkdir()
        self.home = self.root / 'home'; self.home.mkdir(mode=0o700)
        self.archives = {}
        triples = []
        for name in self.m.NAMES:
            path = self.archive(name + '.tar.xz', [('font.ttf', b'fixture-font-data', tarfile.REGTYPE)])
            self.archives[name] = path
            triples.append([name, 'https://github.com/mjcramerz/fonts/releases/download/test/' + name + '.tar.xz', self.m.digest(path)])
        self.policy = self.m.validate_policy(triples)
        self.download = self.enterContext(mock.patch.object(self.m, 'download', side_effect=self.copy_archive))

    def archive(self, filename, members):
        path = self.root / filename
        with tarfile.open(path, 'w:xz') as tar:
            for name, data, kind in members:
                info = tarfile.TarInfo(name); info.type = kind
                info.mode = 0o777; info.uid = 12345; info.gid = 12345
                if kind == tarfile.REGTYPE:
                    info.size = len(data); tar.addfile(info, io.BytesIO(data))
                else:
                    info.linkname = '/etc/passwd'; tar.addfile(info)
        return path

    def copy_archive(self, url, destination, sha):
        name = Path(url).name.removesuffix('.tar.xz')
        payload_copyfile(self.archives[name], destination)

    def generation(self):
        return self.m.prepare_generation(self.cache, self.policy)

    def test_policy_has_exactly_five_unique_https_pins(self):
        self.assertEqual({x['name'] for x in self.policy}, set(self.m.NAMES))
        triples = [[x['name'], x['url'], x['sha256']] for x in self.policy]
        for broken in (triples[:-1], triples + triples[:1], triples[:-1] + triples[:1]):
            with self.assertRaises(ValueError): self.m.validate_policy(broken)
        for bad in ('http://github.com/x', 'https://github.com.evil/x', self.policy[0]['url'] + '?x', 'file:///etc/passwd'):
            rows = [row[:] for row in triples]; rows[0][1] = bad
            with self.assertRaises(ValueError): self.m.validate_policy(rows)

    def test_policy_hash_is_order_independent_after_validation(self):
        rows = [[x['name'], x['url'], x['sha256']] for x in reversed(self.policy)]
        self.assertEqual(self.m.policy_id(self.policy), self.m.policy_id(self.m.validate_policy(rows)))

    def test_sha_mismatch_rejected_before_extraction(self):
        out = self.root / 'out'; out.mkdir()
        with self.assertRaises(ValueError):
            self.m.extract_archive(self.archives['FiraCode'], out, '0' * 64)
        self.assertEqual(list(out.iterdir()), [])

    def test_unsafe_paths_rejected(self):
        for name in ('../font.ttf', '/font.ttf', 'dir/../../font.ttf', 'dir\\font.ttf', 'dir/\x1bfont.ttf'):
            with self.subTest(name=name):
                archive = self.archive('bad.tar.xz', [(name, b'x', tarfile.REGTYPE)])
                with tempfile.TemporaryDirectory(dir=self.root) as output, self.assertRaises(ValueError):
                    self.m.extract_archive(archive, Path(output), self.m.digest(archive))

    def test_links_devices_fifo_rejected(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE, tarfile.FIFOTYPE):
            archive = self.archive('bad.tar.xz', [('font.ttf', b'', kind)])
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(dir=self.root) as output, self.assertRaises(ValueError):
                self.m.extract_archive(archive, Path(output), self.m.digest(archive))

    def test_duplicates_rejected(self):
        archive = self.archive('bad.tar.xz', [('font.ttf', b'a', tarfile.REGTYPE)] * 2)
        with tempfile.TemporaryDirectory(dir=self.root) as output, self.assertRaises(ValueError):
            self.m.extract_archive(archive, Path(output), self.m.digest(archive))

    def test_archive_without_fonts_rejected(self):
        archive = self.archive('bad.tar.xz', [('README', b'not a font', tarfile.REGTYPE)])
        with tempfile.TemporaryDirectory(dir=self.root) as output, self.assertRaises(ValueError):
            self.m.extract_archive(archive, Path(output), self.m.digest(archive))

    def test_member_size_and_expansion_limits(self):
        for setting in ('MAX_MEMBER', 'MAX_EXPANDED', 'MAX_ARCHIVE'):
            with self.subTest(setting=setting), mock.patch.object(self.m, setting, 1), tempfile.TemporaryDirectory(dir=self.root) as output, self.assertRaises(ValueError):
                self.m.extract_archive(self.archives['FiraCode'], Path(output), self.m.digest(self.archives['FiraCode']))

    def test_decompressed_header_bytes_are_bounded(self):
        stream = self.m.BoundedStream(io.BytesIO(b'x' * 20), 10)
        self.assertEqual(stream.read(5), b'x' * 5)
        with self.assertRaises(ValueError): stream.read(1000)

    def test_archive_member_count_limit(self):
        with mock.patch.object(self.m, 'MAX_MEMBERS', 0), tempfile.TemporaryDirectory(dir=self.root) as output, self.assertRaises(ValueError):
            self.m.extract_archive(self.archives['FiraCode'], Path(output), self.m.digest(self.archives['FiraCode']))

    def test_modes_archive_owners_and_executable_bits_are_not_preserved(self):
        generation = self.generation()
        for path in generation.rglob('*'):
            self.assertEqual(payload_source_stat(path).st_uid, os.geteuid())
            self.assertEqual(stat.S_IMODE(payload_source_stat(path).st_mode), 0o755 if path.is_dir() else 0o644)

    def test_identical_generation_does_not_download_again(self):
        source = self.generation(); before = payload_source_stat(source).st_mtime_ns
        self.assertEqual(self.download.call_count, 5)
        self.assertEqual(source, self.generation())
        self.assertEqual(self.download.call_count, 5)
        self.assertEqual(before, payload_source_stat(source).st_mtime_ns)

    def test_bad_late_archive_never_publishes_partial_generation(self):
        self.archives['ProFont'] = self.archive('bad.tar.xz', [('../font.ttf', b'x', tarfile.REGTYPE)])
        with self.assertRaises(ValueError): self.generation()
        self.assertEqual(list((self.cache / 'releases').iterdir()), [])
        self.assertFalse(list(self.cache.glob('.font-stage-*')))

    def test_modified_cache_generation_is_preserved_and_rejected(self):
        generation = self.generation(); font = generation / 'FiraCode/font.ttf'; font.write_bytes(b'admin')
        with self.assertRaises(ValueError): self.generation()
        self.assertEqual(payload_read_bytes(font), b'admin')

    def test_source_symlink_and_hardlink_rejected(self):
        for kind in ('symlink', 'hardlink'):
            with self.subTest(kind=kind):
                generation = self.generation(); font = generation / 'FiraCode/font.ttf'; link = generation / 'extra.ttf'
                if kind == 'symlink': link.symlink_to(font)
                else: os.link(font, link)
                with self.assertRaises(ValueError): self.m.verify_generation(generation, self.policy)
                link.unlink()

    def test_user_and_skeleton_publish_two_closed_groups_without_fontconfig(self):
        source = self.generation()
        for name in ('user-home', 'skel-desktop'):
            home = self.root / name; home.mkdir()
            currents, changed = self.m.publish(home, source, self.policy)
            self.assertTrue(changed)
            for current, group in zip(currents, ('terminal', 'microsoft')):
                self.assertEqual(current, home / self.m.PUBLICATION_ROOTS[group] / 'current')
                self.assertTrue(current.is_symlink())
                self.assertEqual({p.name for p in current.iterdir()}, set(self.m.GROUPS[group]) | {self.m.MANIFEST})
            self.assertFalse(payload_source_exists(home / '.config'))

    def test_unchanged_publication_and_font_cache_are_noop(self):
        source = self.generation(); current, changed = self.m.publish(self.home, source, self.policy)
        with mock.patch.object(self.m.subprocess, 'run') as run:
            self.m.font_cache(self.home, current, self.home / '.cache', self.m.policy_id(self.policy), changed)
            self.assertEqual(run.call_count, 1)
            before = {str(p): p.lstat().st_mtime_ns for p in self.home.rglob('*')}
            current, changed = self.m.publish(self.home, source, self.policy)
            self.assertFalse(changed)
            self.m.font_cache(self.home, current, self.home / '.cache', self.m.policy_id(self.policy), changed)
            self.assertEqual(run.call_count, 1)
            self.assertEqual(before, {str(p): p.lstat().st_mtime_ns for p in self.home.rglob('*')})

    def test_failed_font_cache_is_retried(self):
        source = self.generation(); current, changed = self.m.publish(self.home, source, self.policy)
        with mock.patch.object(self.m.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'fc-cache')):
            with self.assertRaises(subprocess.CalledProcessError):
                self.m.font_cache(self.home, current, self.home / '.cache', self.m.policy_id(self.policy), changed)
        self.assertTrue(all(not payload_source_exists(p.parent / '.cache-ready') for p in current))
        with mock.patch.object(self.m.subprocess, 'run') as run:
            self.m.font_cache(self.home, current, self.home / '.cache', self.m.policy_id(self.policy), False)
            run.assert_called_once()
            self.assertNotIn('shell', run.call_args.kwargs)
            self.assertEqual(run.call_args.args[0][0], '/usr/bin/fc-cache')

    def test_modified_user_generation_is_not_overwritten(self):
        source = self.generation(); current, _ = self.m.publish(self.home, source, self.policy)
        font = current[0] / 'FiraCode/font.ttf'; font.write_bytes(b'user-data')
        with self.assertRaises(ValueError): self.m.publish(self.home, source, self.policy)
        self.assertEqual(payload_read_bytes(font), b'user-data')

    def test_unmanaged_config_is_not_replaced(self):
        config = self.home / '.config/fontconfig/conf.d/60-labwc-terminal-fonts.conf'
        config.parent.mkdir(parents=True); config.write_bytes(b'admin-config')
        currents, changed = self.m.publish(self.home, self.generation(), self.policy)
        self.assertTrue(changed)
        self.assertTrue(all(p.is_dir() for p in currents))
        self.assertEqual(payload_read_bytes(config), b'admin-config')

    def test_symlink_home_component_refused(self):
        other = self.root / 'elsewhere'; other.mkdir()
        (self.home / '.local').symlink_to(other)
        with self.assertRaises(ValueError): self.m.publish(self.home, self.generation(), self.policy)
        self.assertEqual(list(other.iterdir()), [])

    def test_unmanaged_current_refused(self):
        base = self.home / '.local/share/icons/terminal-fonts'; base.mkdir(parents=True)
        (base / 'current').symlink_to('/usr/share/fonts')
        with self.assertRaises(ValueError): self.m.publish(self.home, self.generation(), self.policy)
        self.assertEqual(os.readlink(base / 'current'), '/usr/share/fonts')

    def test_atomic_pointer_failure_is_recoverable(self):
        source = self.generation()
        real_replace = os.replace
        def fail_pointer(src, dst):
            if Path(dst).name == 'current': raise OSError('simulated interruption')
            return real_replace(src, dst)
        with mock.patch.object(self.m.os, 'replace', side_effect=fail_pointer):
            with self.assertRaises(OSError): self.m.publish(self.home, source, self.policy)
        current, changed = self.m.publish(self.home, source, self.policy)
        self.assertTrue(all(p.is_dir() for p in current)); self.assertTrue(changed)
        self.assertFalse(any(list(p.parent.glob('.current-*')) for p in current))

    @unittest.skipUnless(os.geteuid() == 0, 'requires root ownership fixture')
    def test_root_created_xdg_parents_repaired_without_recursive_chown(self):
        nobody = pwd.getpwnam('nobody')
        account = types.SimpleNamespace(pw_uid=nobody.pw_uid, pw_gid=nobody.pw_gid, pw_dir=str(self.home))
        os.chown(self.home, account.pw_uid, account.pw_gid)
        share = self.home / '.local/share'; share.mkdir(parents=True)
        unrelated = share / 'unrelated'; unrelated.write_bytes(b'unchanged')
        self.m.prepare_user_parents(account)
        self.assertEqual(payload_source_stat(self.home / '.local').st_uid, account.pw_uid)
        self.assertEqual(payload_source_stat(share).st_uid, account.pw_uid)
        self.assertEqual(payload_source_stat(unrelated).st_uid, 0)
        self.m.prepare_user_parents(account)

    @unittest.skipUnless(os.geteuid() == 0, 'requires root ownership fixture')
    def test_xdg_parent_symlink_never_chowns_its_target(self):
        nobody = pwd.getpwnam('nobody')
        account = types.SimpleNamespace(pw_uid=nobody.pw_uid, pw_gid=nobody.pw_gid, pw_dir=str(self.home))
        os.chown(self.home, account.pw_uid, account.pw_gid)
        other = self.root / 'outside'; other.mkdir()
        (self.home / '.local').symlink_to(other)
        with self.assertRaises(OSError): self.m.prepare_user_parents(account)
        self.assertEqual(payload_source_stat(other).st_uid, 0)
        self.assertEqual(list(other.iterdir()), [])

    @unittest.skipUnless(os.geteuid() == 0 and shutil.which('fc-cache') and shutil.which('fc-list'), 'requires root privilege-drop fixture and real fontconfig')
    def test_real_nonroot_publication_and_fontconfig_discovery(self):
        candidates = sorted(Path('/usr/share/fonts').rglob('*.ttf'))
        if not candidates: self.skipTest('no system font available for a temporary fixture')
        # This file is used only in TemporaryDirectory, never in the source tree.
        data = payload_read_bytes(candidates[0])
        for item in self.policy:
            self.archives[item['name']] = self.archive(item['name'] + '.tar.xz', [('fixture.ttf', data, tarfile.REGTYPE)])
            item['sha256'] = self.m.digest(self.archives[item['name']])
        source = self.generation()
        nobody = pwd.getpwnam('nobody')
        account = types.SimpleNamespace(pw_uid=nobody.pw_uid, pw_gid=nobody.pw_gid, pw_dir=str(self.home))
        os.chown(self.home, account.pw_uid, account.pw_gid)
        config = self.home / '.config/fontconfig/conf.d'
        config.mkdir(parents=True)
        for path in (FORKY / 'hooks/target/etc/skel-desktop/.config/fontconfig/conf.d').iterdir():
            payload_copyfile(path, config / path.name)
            (config / path.name).chmod(0o600)
        for path in self.home.rglob('*'):
            os.chown(path, account.pw_uid, account.pw_gid)
        self.m.install_user(account, source, self.policy)
        current = self.home / '.local/share/icons/terminal-fonts/current'
        self.assertEqual(current.lstat().st_uid, account.pw_uid)
        for path in self.home.rglob('*'):
            self.assertEqual(path.lstat().st_uid, account.pw_uid)
        result = subprocess.run(payload_installed_argv(['/usr/bin/fc-list', '-f', '%{file}\n']),
            env={'HOME': str(self.home), 'XDG_DATA_HOME': str(self.home / '.local/share'),
                 'XDG_CONFIG_HOME': str(self.home / '.config'), 'XDG_CACHE_HOME': str(self.home / '.cache'),
                 'LC_ALL': 'C.UTF-8', 'PATH': '/usr/bin:/bin'},
            user=account.pw_uid, group=account.pw_gid, extra_groups=[], cwd='/',
            capture_output=True, text=True, check=True)
        self.assertIn(str(self.home / '.local/share/icons/terminal-fonts'), result.stdout)
        self.assertIn(str(self.home / '.local/share/fonts/microsoft-fonts'), result.stdout)

    def test_all_profiles_and_role_flow_have_complete_pins(self):
        profiles = sorted((FORKY / 'hosts/profiles').glob('*.env'))
        self.assertEqual(len(profiles), 10)
        keys = ('FIRACODE', 'SYMBOLS', 'PROFONT', 'APTOS', 'MICROSOFT')
        for profile in profiles:
            text = payload_read_text(profile)
            for key in keys:
                self.assertEqual(text.count('LABWC_FONT_' + key + '_URL='), 1)
                self.assertEqual(text.count('LABWC_FONT_' + key + '_SHA256='), 1)
        self.assertIn('desktop_install_fonts', payload_read_text(FORKY / 'scripts/desktop/labwc.sh'))
        self.assertIn('fonts.sh', payload_read_text(FORKY / 'scripts/late/desktop.sh'))
        self.assertIn('fonts-install.py', payload_read_text(FORKY / 'scripts/desktop/fonts.sh'))
        self.assertIn('fonts.d/labwc-terminal-fonts', payload_read_text(FORKY / 'scripts/late/security.sh'))

    def test_closed_names_basename_and_hash_requirements(self):
        self.assertEqual(set(self.m.NAMES), {'FiraCode', 'NerdFontsSymbolsOnly', 'ProFont', 'MicrosoftAptosFonts', 'MicrosoftLocalFonts'})
        rows = [[p['name'], p['url'], p['sha256']] for p in self.policy]
        for name in ('microsoft-fonts', 'unknown', '../MicrosoftLocalFonts'):
            bad = [row[:] for row in rows]; bad[-1][0] = name
            with self.subTest(name=name), self.assertRaises(ValueError): self.m.validate_policy(bad)
            with self.assertRaises(ValueError): self.m.publication_group(name)
        for column, value in ((1, rows[0][1].replace(rows[0][0], 'wrong')), (2, ''), (2, 'x'*64)):
            bad = [row[:] for row in rows]; bad[0][column] = value
            with self.assertRaises(ValueError): self.m.validate_policy(bad)
        self.assertEqual(self.m.GROUPS['terminal'], ('FiraCode', 'NerdFontsSymbolsOnly', 'ProFont'))
        self.assertEqual(self.m.GROUPS['microsoft'], ('MicrosoftAptosFonts', 'MicrosoftLocalFonts'))

    def test_static_fontconfig_is_only_configuration_source(self):
        import xml.etree.ElementTree as ET
        source = payload_read_text(SOURCE)
        components = payload_read_text(FORKY / 'scripts/desktop/components.sh')
        for name, directory in (('60-labwc-terminal-fonts.conf', 'icons/terminal-fonts/current'),
                                ('61-microsoft-fonts.conf', 'fonts/microsoft-fonts/current')):
            path = FORKY / 'hooks/target/etc/skel-desktop/.config/fontconfig/conf.d' / name
            node = ET.parse(path).getroot().find('dir')
            self.assertEqual(node.attrib, {'prefix': 'xdg'})
            self.assertEqual(node.text, directory)
            self.assertIn(name, components)
            self.assertNotIn(name, source)
        self.assertNotIn('<fontconfig>', source)
        self.assertNotIn('FONT_CONFIG', source)
        self.assertIn('    .config/fontconfig ', components)

    def test_second_tree_failure_leaves_neither_current_published(self):
        base = self.home / '.local/share/fonts/microsoft-fonts'
        base.mkdir(parents=True); (base / 'current').symlink_to('/unmanaged')
        with self.assertRaises(ValueError): self.m.publish(self.home, self.generation(), self.policy)
        self.assertFalse(os.path.lexists(self.home / '.local/share/icons/terminal-fonts/current'))
        self.assertEqual(os.readlink(base / 'current'), '/unmanaged')

    def test_second_swap_failure_rolls_back_both_generations(self):
        self.check_swap_rollback(False)

    def test_post_second_swap_failure_rolls_back_both_generations(self):
        self.check_swap_rollback(True)

    def check_swap_rollback(self, after_swap):
        source = self.generation()
        currents, _ = self.m.publish(self.home, source, self.policy)
        old = [os.readlink(p) for p in currents]
        rows = [[p['name'], p['url'].replace('/test/', '/next/'), p['sha256']] for p in self.policy]
        policy = self.m.validate_policy(rows); source = self.m.prepare_generation(self.cache, policy)
        replace = self.m.replace_current
        failed = False
        def interrupted(path, value):
            nonlocal failed
            if path == currents[1] and not failed:
                failed = True
                if after_swap: replace(path, value)
                raise OSError('second swap failure')
            replace(path, value)
        with mock.patch.object(self.m, 'replace_current', side_effect=interrupted), self.assertRaises(OSError):
            self.m.publish(self.home, source, policy)
        self.assertEqual([os.readlink(p) for p in currents], old)

    def test_forged_user_manifest_cannot_replace_verified_cache_content(self):
        source = self.generation(); currents, _ = self.m.publish(self.home, source, self.policy)
        font = currents[0] / 'FiraCode/font.ttf'; font.write_bytes(b'forged')
        subset = [p for p in self.policy if p['name'] in self.m.GROUPS['terminal']]
        self.m.seal(currents[0].resolve(), subset)
        with self.assertRaises(ValueError): self.m.publish(self.home, source, self.policy)

    def verification_fixture(self):
        if os.geteuid() != 0:
            self.skipTest('desktop ownership verification fixture requires root')
        account = pwd.getpwnam('nobody')
        fake = types.SimpleNamespace(pw_uid=account.pw_uid, pw_gid=account.pw_gid,
                                     pw_dir=str(self.home))
        source = self.generation()
        skel = self.root / 'skel'; skel.mkdir(mode=0o755)
        config_source = FORKY / 'hooks/target/etc/skel-desktop/.config/fontconfig/conf.d'
        for home in (skel, self.home):
            currents, _ = self.m.publish(home, source, self.policy)
            with mock.patch.object(self.m.subprocess, 'run'):
                self.m.font_cache(home, currents, home / '.cache', self.m.policy_id(self.policy), True)
            destination = home / '.config/fontconfig/conf.d'
            destination.mkdir(parents=True, mode=0o700)
            for config in config_source.glob('*.conf'):
                payload_copyfile(config, destination / config.name)
                (destination / config.name).chmod(0o644 if home == skel else 0o600)
        for path in (self.home, *self.home.rglob('*')):
            os.chown(path, account.pw_uid, account.pw_gid, follow_symlinks=False)
        source = payload_read_text(FORKY / 'scripts/desktop/verify.sh').split('desktop_verify_font_publications() {', 1)[1]
        code = source.split("/usr/bin/python3 -I -c '\n", 1)[1].split("\n' \"${ACCOUNT_HOME", 1)[0]
        rows = {row['name']: row for row in self.policy}
        argv = ['desktop-font-verifier', str(self.home), 'fixture-user', str(skel), str(self.cache)]
        for name in self.m.NAMES:
            argv.extend((rows[name]['url'], rows[name]['sha256']))
        def verify():
            import sys
            with mock.patch.object(pwd, 'getpwnam', return_value=fake), mock.patch.object(sys, 'argv', argv):
                exec(compile(code, 'desktop/verify.sh:font-publications', 'exec'), {})
        return verify

    def test_desktop_verifier_checks_both_publications(self):
        verify = self.verification_fixture()
        verify()
        # Existing skeleton deployment tightens an existing user tree on rerun.
        for path in self.home.rglob('*'):
            if not path.is_symlink(): path.chmod(0o700 if path.is_dir() else 0o600)
        verify()

    def test_desktop_verifier_rejects_tampered_font(self):
        verify = self.verification_fixture()
        (self.home / '.local/share/fonts/microsoft-fonts/current/MicrosoftLocalFonts/font.ttf').write_bytes(b'tampered')
        with self.assertRaises(ValueError): verify()

    def test_desktop_verifier_rejects_wrong_or_broken_current(self):
        verify = self.verification_fixture()
        current = self.home / '.local/share/fonts/microsoft-fonts/current'
        current.unlink(); current.symlink_to('../../icons/terminal-fonts/current')
        account = pwd.getpwnam('nobody')
        os.chown(current, account.pw_uid, account.pw_gid, follow_symlinks=False)
        with self.assertRaises(ValueError): verify()

    def test_desktop_verifier_rejects_wrong_fontconfig_and_unsafe_modes(self):
        verify = self.verification_fixture()
        config = self.home / '.config/fontconfig/conf.d/61-microsoft-fonts.conf'
        original = payload_read_bytes(config)
        config.write_bytes(original.replace(b'fonts/microsoft-fonts/current', b'icons/terminal-fonts/current'))
        with self.assertRaises(ValueError): verify()
        config.write_bytes(original); config.chmod(0o666)
        with self.assertRaises(ValueError): verify()

    def test_requested_debian_packages_present(self):
        packages = payload_read_text(FORKY / 'classes/class-select/role/desktop.cfg').split()
        for name in 'wtype fonts-liberation2 fonts-crosextra-carlito fonts-crosextra-caladea fonts-noto fonts-noto-cjk fonts-dejavu fonts-dejavu-extra fonts-noto-ui-core fonts-noto-ui-extra fonts-texgyre'.split():
            self.assertIn(name, packages)


if __name__ == '__main__': unittest.main()
