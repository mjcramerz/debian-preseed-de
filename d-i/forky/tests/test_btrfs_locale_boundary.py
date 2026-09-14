"""Btrfs --features and installer/target locale regressions.

No real disk, mounted target, private initrd or service is used. Bridge fixtures
capture both environments; the optional real Btrfs test writes only temporary
regular-file images. The root-only chroot test copies existing binaries, never
compiles them, and never mounts anything.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import unittest

SEED = Path(__file__).resolve().parents[1]
TARGET = SEED / 'scripts/common/target.sh'
LAYOUT = SEED / 'hosts/installer/layout-btrfs.env'
CATEGORIES = (
    'LC_CTYPE', 'LC_NUMERIC', 'LC_TIME', 'LC_COLLATE', 'LC_MONETARY',
    'LC_MESSAGES', 'LC_PAPER', 'LC_NAME', 'LC_ADDRESS', 'LC_TELEPHONE',
    'LC_MEASUREMENT', 'LC_IDENTIFICATION',
)
EXTRA_LOCALE = ('LANGUAGE', 'LOCPATH', 'NLSPATH', 'GCONV_PATH', 'IT_LANG_OVERRIDE')
POISON = {key: 'installer_only_invalid.UTF-8' for key in ('LANG', 'LC_ALL', *CATEGORIES)}
POISON.update(LANGUAGE='zz_DI:zz', LOCPATH='/d-i/locale', NLSPATH='/d-i/catalog/%N',
              GCONV_PATH='/d-i/gconv', IT_LANG_OVERRIDE='installer_only_invalid.UTF-8')
DEBCONF = (
    'DEBCONF_DB_REPLACE', 'DEBCONF_REDIR', 'DEBCONF_FRONTEND',
    'DEBCONF_NONINTERACTIVE_SEEN', 'DEBCONF_SYSTEMRC', 'DEBCONF_PIPE',
    'DEBCONF_USE_CDEBCONF', 'DEBCONF_DEBUG', 'DEBCONF_NOWARNINGS',
    'DEBCONF_TERSE', 'DEBIAN_FRONTEND',
)
SHELLS = [[path] for path in ('/bin/dash', '/bin/bash') if Path(path).exists()]
if shutil.which('busybox'):
    SHELLS.append([shutil.which('busybox'), 'ash'])


def poison_script() -> str:
    # Suppress only warnings from deliberately poisoning the FIXTURE shell.
    # Output from target_exec and its children is never suppressed here.
    return '{\n' + '\n'.join('export '+k+'='+shlex.quote(v) for k, v in POISON.items()) + '\n} 2>/dev/null\n'


def env_parse(data: bytes) -> dict[str, str]:
    return dict(item.decode().split('=', 1) for item in data.split(b'\0') if b'=' in item)


def executable(path: Path, text: str) -> None:
    path.write_text(text)
    path.chmod(0o755)


class LocaleBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='btrfs-locale-')
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name)
        self.bin = self.work/'bin'
        self.bin.mkdir()
        self.fake_root = self.work/'target with spaces'
        self.fake_root.mkdir()

    def bridge(self, kind: str, *, inject=False, fail=0):
        # The fake in-target models Debconf passthrough and the documented
        # IT_LANG_OVERRIDE behavior, not the real mounting/diversion machinery.
        body = '#!/bin/sh\n/usr/bin/env -0 > '+shlex.quote(str(self.work/(kind+'.env'))) + '\n'
        body += 'printf "%s\\n" "$1" > '+shlex.quote(str(self.work/(kind+'.arg'))) + '\n'
        if fail:
            body += f'exit {fail}\n'
        elif kind == 'in-target':
            body += '[ "$1" = --pass-stdout ] || exit 91\nshift\n'
            body += 'LANG=${IT_LANG_OVERRIDE:-installer_debconf_invalid.UTF-8}\nexport LANG\n'
            body += 'DEBIAN_FRONTEND=passthrough\nDEBCONF_READFD=0\nDEBCONF_WRITEFD=3\n'
            body += 'export DEBIAN_FRONTEND DEBCONF_READFD DEBCONF_WRITEFD\n'
            if inject:
                body += poison_script()
            body += 'exec "$@"\n'
        else:
            body += 'shift\nexec "$@"\n'
        executable(self.bin/kind, body)

    def run_code(self, shell, code: str, *, root='/target', stdin=None):
        script = '. '+shlex.quote(str(TARGET))+'\n'
        script += 'installer_fatal() { printf "%s\\n" "$*" >&2; exit 79; }\n'
        script += 'INSTALLER_TARGET_DIR='+shlex.quote(root)+'\n'
        script += poison_script()
        script += '\n'.join('export '+key+'=installer_debconf' for key in DEBCONF)+'\n'
        script += 'export http_proxy=http://fixture.invalid:3142 KEEP_FIXTURE=yes\n'
        script += code
        return subprocess.run([*shell, '-c', script], input=stdin, capture_output=True,
                              env={'PATH':str(self.bin), 'HOME':'/root', 'LANG':'C', 'LC_ALL':'C'},
                              timeout=10)

    def assert_clean_child(self, data):
        self.assertEqual(data['LANG'], 'C.UTF-8')
        self.assertEqual(data['LC_ALL'], 'C.UTF-8')
        for key in (*CATEGORIES, *EXTRA_LOCALE):
            self.assertNotIn(key, data, key)
        self.assertEqual(data['HOME'], '/root')
        self.assertEqual(data['XDG_CONFIG_HOME'], '/root/.config')

    def test_in_target_bridge_has_c_and_no_installer_locale_categories(self):
        self.bridge('in-target')
        for shell in SHELLS:
            with self.subTest(shell=shell):
                p=self.run_code(shell, 'target_exec /usr/bin/env -0')
                self.assertEqual(p.returncode, 0, p.stderr)
                bridge=env_parse((self.work/'in-target.env').read_bytes())
                self.assertEqual(bridge['LANG'], 'C')
                self.assertEqual(bridge['LC_ALL'], 'C')
                self.assertEqual(bridge['IT_LANG_OVERRIDE'], 'C')
                for key in (*CATEGORIES, *EXTRA_LOCALE[:-1], *DEBCONF):
                    self.assertNotIn(key, bridge, key)
                self.assert_clean_child(env_parse(p.stdout))
                self.assertEqual(p.stderr, b'')

    def test_target_rejects_bridge_reintroduced_categories_and_paths(self):
        self.bridge('in-target', inject=True)
        for shell in SHELLS:
            with self.subTest(shell=shell):
                p=self.run_code(shell, 'target_exec /usr/bin/env -0')
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assert_clean_child(env_parse(p.stdout))
                self.assertEqual(p.stderr, b'')

    def test_in_target_keeps_passthrough_proxy_and_unrelated_environment(self):
        self.bridge('in-target')
        for shell in SHELLS:
            with self.subTest(shell=shell):
                p=self.run_code(shell, 'target_exec /usr/bin/env -0')
                self.assertEqual(p.returncode, 0, p.stderr)
                child=env_parse(p.stdout)
                self.assertEqual(child['DEBIAN_FRONTEND'], 'passthrough')
                self.assertEqual(child['DEBCONF_READFD'], '0')
                self.assertEqual(child['DEBCONF_WRITEFD'], '3')
                self.assertEqual(child['http_proxy'], 'http://fixture.invalid:3142')
                self.assertEqual(child['KEEP_FIXTURE'], 'yes')

    def test_chroot_bridge_is_normalized_before_clean_target_env(self):
        self.bridge('chroot')
        for shell in SHELLS:
            with self.subTest(shell=shell):
                p=self.run_code(shell, 'target_exec /usr/bin/env -0', root=str(self.fake_root))
                self.assertEqual(p.returncode, 0, p.stderr)
                bridge=env_parse((self.work/'chroot.env').read_bytes())
                self.assertEqual(bridge['LANG'], 'C')
                self.assertEqual(bridge['LC_ALL'], 'C')
                for key in (*CATEGORIES, *EXTRA_LOCALE):
                    self.assertNotIn(key, bridge, key)
                child=env_parse(p.stdout)
                self.assert_clean_child(child)
                self.assertNotIn('KEEP_FIXTURE', child)
                self.assertNotIn('http_proxy', child)
                self.assertNotIn('DEBCONF_FRONTEND', child)
                self.assertEqual((self.work/'chroot.arg').read_text().strip(), str(self.fake_root))

    def test_custom_root_uses_chroot_even_when_in_target_exists(self):
        self.bridge('in-target', fail=90)
        self.bridge('chroot')
        p=self.run_code(SHELLS[0], 'target_exec /usr/bin/env -0', root=str(self.fake_root))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse((self.work/'in-target.env').exists())
        self.assert_clean_child(env_parse(p.stdout))

    def test_normalization_never_changes_callers_locale_or_debconf(self):
        for kind in ('in-target', 'chroot'):
            self.bridge(kind)
            for shell in SHELLS:
                with self.subTest(kind=kind, shell=shell):
                    p=self.run_code(shell, 'target_exec /usr/bin/true\n/usr/bin/env -0',
                                    root='/target' if kind=='in-target' else str(self.fake_root))
                    self.assertEqual(p.returncode, 0, p.stderr)
                    parent=env_parse(p.stdout)
                    for key,value in POISON.items():
                        self.assertEqual(parent[key], value, key)
                    for key in DEBCONF:
                        self.assertEqual(parent[key], 'installer_debconf', key)

    def test_failed_bridge_status_preserved_no_chroot_fallback(self):
        self.bridge('in-target', fail=37)
        self.bridge('chroot')
        for shell in SHELLS:
            with self.subTest(shell=shell):
                p=self.run_code(shell, 'target_exec /usr/bin/true')
                self.assertEqual(p.returncode, 37)
                self.assertFalse((self.work/'chroot.env').exists())

    def test_failed_target_status_preserved_both_branches(self):
        for kind in ('in-target', 'chroot'):
            self.bridge(kind)
            for shell in SHELLS:
                with self.subTest(kind=kind,shell=shell):
                    p=self.run_code(shell, "target_exec /bin/sh -c 'exit 23'",
                                    root='/target' if kind=='in-target' else str(self.fake_root))
                    self.assertEqual(p.returncode, 23, p.stderr)

    def test_explicit_command_locale_overrides_still_work(self):
        for kind in ('in-target', 'chroot'):
            self.bridge(kind)
            for shell in SHELLS:
                with self.subTest(kind=kind,shell=shell):
                    p=self.run_code(shell, 'target_exec /usr/bin/env -u LC_ALL LANG=C LC_MESSAGES=C /usr/bin/env -0',
                                    root='/target' if kind=='in-target' else str(self.fake_root))
                    self.assertEqual(p.returncode, 0, p.stderr)
                    child=env_parse(p.stdout)
                    self.assertEqual(child['LANG'], 'C')
                    self.assertEqual(child['LC_MESSAGES'], 'C')
                    self.assertNotIn('LC_ALL', child)
                    for key in (*CATEGORIES, *EXTRA_LOCALE):
                        if key!='LC_MESSAGES':
                            self.assertNotIn(key, child, key)

    def test_child_can_unset_lc_all_without_reactivating_bad_categories(self):
        self.bridge('in-target', inject=True)
        for shell in SHELLS:
            with self.subTest(shell=shell):
                p=self.run_code(shell, 'target_exec /usr/bin/env -u LC_ALL /usr/bin/locale charmap')
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertEqual(p.stdout, b'UTF-8\n')
                self.assertEqual(p.stderr, b'')

    def test_stdin_fd3_and_literal_arguments_preserved(self):
        self.bridge('in-target')
        for shell in SHELLS:
            with self.subTest(shell=shell):
                fd=self.work/'fd3'
                command="target_exec /bin/sh -c 'IFS= read -r value; printf \"%s\\n\" \"$value\"; printf \"%s\\n\" \"$1\" >&3' sh 'literal ; $x * spaced'"
                p=self.run_code(shell, 'exec 3>'+shlex.quote(str(fd))+'\n'+command,
                                stdin=b'fixture data with spaces\n')
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertEqual(p.stdout,b'fixture data with spaces\n')
                self.assertEqual(fd.read_text(),'literal ; $x * spaced\n')

    def test_nondefault_root_without_chroot_fails_closed(self):
        self.bridge('in-target')
        p=self.run_code(SHELLS[0], 'target_exec /usr/bin/true', root=str(self.fake_root))
        self.assertEqual(p.returncode, 79)
        self.assertIn(b'non-default installer target root', p.stderr)
        self.assertFalse((self.work/'in-target.env').exists())


class BtrfsFeatureTests(unittest.TestCase):
    @staticmethod
    def options():
        p=subprocess.run(['/bin/sh','-c', '. "$1"; printf "%s\\0" "$MKFS_BTRFS_ROOT_OPTS" "$MKFS_BTRFS_HOME_OPTS" "$MKFS_BTRFS_OPT_OPTS"',
                          'sh',str(LAYOUT)], capture_output=True,timeout=10,
                         env={'PATH':'/usr/bin:/bin','LANG':'C','LC_ALL':'C'})
        if p.returncode:
            raise AssertionError(p.stderr)
        return [shlex.split(x.decode()) for x in p.stdout.split(b'\0') if x]

    def test_three_tiers_keep_exact_filesystem_policy_with_merged_features(self):
        for label, argv in zip(('ROOT','HOME','OPT'), self.options(), strict=True):
            self.assertEqual(argv, ['-f','-L',label,'--checksum','xxhash','--data','single',
                                    '--metadata','dup','--nodesize','16384','--features',
                                    'extref,skinny-metadata,no-holes,free-space-tree'])

    def test_no_deprecated_mkfs_options_remain_in_active_configuration(self):
        for directory in ('hosts','scripts','hooks/installer'):
            for path in (SEED/directory).rglob('*'):
                if path.is_file():
                    text=path.read_text()
                    self.assertNotIn('--runtime-features',text,str(path))
                    self.assertNotRegex(text,r'mkfs\.btrfs[^\n]*\s-R(?:\s|$)',str(path))

    def test_shared_policy_retains_mount_and_boot_space_cache(self):
        text=LAYOUT.read_text()
        for variable in ('MNT_BTRFS_BASE','GRUB_ROOT_FLAGS'):
            line=next(x for x in text.splitlines() if x.startswith(variable+'='))
            self.assertIn('space_cache=v2',line)
        hook=(SEED/'hooks/installer/partman/finish.d/99-storage-layout.sh').read_text()
        for tier in ('ROOT','HOME','OPT'):
            self.assertIn(f'ensure_btrfs_filesystem "$DEV_PART_{tier}" "$MKFS_BTRFS_{tier}_OPTS" "$FS_LABEL_{tier}"',hook)

    def test_btrfs_and_vm_host_compositions_receive_the_new_policy(self):
        overrides=set()
        for config in (SEED/'classes/configs').glob('*.cfg'):
            for stanza in re.split(r'\n\s*\n',config.read_text()):
                fields=dict(line.split(': ',1) for line in stanza.splitlines()
                            if ': ' in line and not line.startswith('#'))
                if fields.get('Type')=='class' and fields.get('Group')=='profile':
                    overrides.add(fields['Name'])
        profiles=[p for p in (SEED/'hosts/profiles').glob('*.env') if p.name.startswith(('btrfs-','vm-'))]
        self.assertTrue(profiles)
        with tempfile.TemporaryDirectory(prefix='btrfs-composition-') as name:
            work=Path(name)
            commands=['. "$INSTALLER_SOURCE_ROOT/scripts/common/lib.sh"',
                      'installer_ensure_repo_env "$INSTALLER_SOURCE_ROOT"', 'installer_classes_cache_ensure']
            for profile in profiles:
                logical=('override-' if profile.stem in overrides else '')+profile.stem
                out=work/profile.name
                commands.append('installer_fetch_host_env "$INSTALLER_SOURCE_ROOT" '+shlex.quote(logical)+' '+shlex.quote(str(out)))
            env={**os.environ,'LANG':'C','LC_ALL':'C','INSTALLER_RUNTIME_DIR':str(work),
                 'INSTALLER_CMDLINE':'','INSTALLER_SOURCE_ROOT':str(SEED),
                 'INSTALLER_SOURCE_LIBRARY':str(SEED/'scripts/common/source.sh')}
            p=subprocess.run(['/bin/sh','-eu','-c','\n'.join(commands)],env=env,capture_output=True,timeout=45)
            self.assertEqual(p.returncode,0,p.stderr)
            for profile in profiles:
                text=(work/profile.name).read_text()
                self.assertNotIn('--runtime-features',text,profile.name)
                for tier in ('ROOT','HOME','OPT'):
                    line=next(x for x in text.splitlines() if x.startswith('MKFS_BTRFS_'+tier+'_OPTS='))
                    self.assertIn('--features extref,skinny-metadata,no-holes,free-space-tree',line)

    def test_regenerated_payload_contains_both_canonical_sources(self):
        with tarfile.open(SEED/'payload.tar.gz') as archive:
            for path in (TARGET,LAYOUT):
                member=archive.extractfile(str(path.relative_to(SEED)))
                self.assertIsNotNone(member)
                self.assertEqual(member.read(),path.read_bytes(),str(path))

    @unittest.skipUnless(shutil.which('mkfs.btrfs') and shutil.which('btrfs'),
                         'real btrfs-progs executables unavailable; no mock claimed as format validation')
    def test_real_mkfs_uses_only_temporary_regular_images(self):
        with tempfile.TemporaryDirectory(prefix='btrfs-image-regression-') as name:
            for label,argv in zip(('ROOT','HOME','OPT'),self.options(),strict=True):
                with self.subTest(tier=label):
                    image=Path(name)/(label+'.img')
                    with image.open('xb') as stream:
                        stream.truncate(256*1024*1024)
                    self.assertTrue(image.is_file())
                    p=subprocess.run(['mkfs.btrfs',*argv,str(image)],capture_output=True,timeout=30,
                                     env={**os.environ,'LANG':'C','LC_ALL':'C'})
                    self.assertEqual(p.returncode,0,p.stderr)
                    self.assertNotIn(b'runtime features are deprecated',p.stderr+p.stdout)
                    q=subprocess.run(['btrfs','inspect-internal','dump-super',str(image)],
                                     capture_output=True,timeout=10)
                    self.assertEqual(q.returncode,0,q.stderr)
                    for feature in (b'FREE_SPACE_TREE',b'FREE_SPACE_TREE_VALID',b'EXTENDED_IREF',b'SKINNY_METADATA',b'NO_HOLES'):
                        self.assertIn(feature,q.stdout)
                    self.assertRegex(q.stdout,rb'nodesize\s+16384')
                    self.assertIn(b'xxhash64',p.stdout)


@unittest.skipUnless(os.geteuid()==0 and shutil.which('chroot') and shutil.which('ldd'),
                     'root and existing chroot/ldd tools required for minimal target fixture')
class RealChrootLocaleTests(unittest.TestCase):
    def test_target_utf8_without_installer_locale_paths_or_generated_user_locale(self):
        with tempfile.TemporaryDirectory(prefix='target-locale-root-') as name:
            root=Path(name)
            for binary in ('/usr/bin/env','/bin/dash','/usr/bin/locale'):
                dest=root/binary.lstrip('/')
                dest.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(binary,dest)
                p=subprocess.run(['ldd',binary],capture_output=True,text=True,timeout=10)
                self.assertEqual(p.returncode,0,p.stderr)
                for library in re.findall(r'(/[^\s()]+)',p.stdout):
                    source=Path(library)
                    if source.is_file():
                        dest=root/library.lstrip('/')
                        dest.parent.mkdir(parents=True,exist_ok=True)
                        shutil.copy2(source,dest)
            (root/'bin/sh').symlink_to('dash')
            # C.UTF-8 data belongs to Debian's base libc, not locale-gen or the
            # installer LOCPATH. Copy only this standard base data when present.
            base_locale=Path('/usr/lib/locale/C.utf8')
            if base_locale.is_dir():
                shutil.copytree(base_locale,root/'usr/lib/locale/C.utf8')
            script='. '+shlex.quote(str(TARGET))+'\n'+poison_script()
            script+='INSTALLER_TARGET_DIR='+shlex.quote(str(root))+'\n'
            script+='target_exec /usr/bin/env -u LC_ALL /bin/sh -c '+shlex.quote(
                'test -z "${LC_CTYPE+x}${LC_MESSAGES+x}${LANGUAGE+x}${LOCPATH+x}${GCONV_PATH+x}" || exit 90; '
                '/usr/bin/locale charmap')
            p=subprocess.run(['/bin/dash','-c',script],capture_output=True,timeout=15,
                             env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C','LC_ALL':'C'})
            self.assertEqual(p.returncode,0,p.stderr)
            self.assertEqual(p.stdout,b'UTF-8\n')
            self.assertEqual(p.stderr,b'')
            self.assertFalse((root/'etc/locale.gen').exists())


if __name__=='__main__':
    unittest.main()
