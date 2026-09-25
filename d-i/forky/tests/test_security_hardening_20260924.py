"""Adversarial checks for the scoped security repair; no real boot/key setup.

Integration probes explicitly skip unavailable tools/namespaces. TPM and FSS
fixtures exercise production state logic, not a real TPM or journal generation.
"""
from __future__ import annotations
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock
from payload_fixture import installed_script

ROOT = Path(__file__).resolve().parents[3]
SEED = ROOT / 'd-i/forky'
LIBEXEC = SEED / 'hooks/target/usr/local/libexec'


def module(path):
    name = 'security_fixture_' + path.name.replace('-', '_').replace('.', '_')
    m = types.ModuleType(name)
    m.__file__ = str(path)
    sys.modules[name] = m
    exec(compile(path.read_bytes(), str(path), 'exec'), m.__dict__)
    return m


def shell_function(path, name):
    text = path.read_text()
    start = text.index(name + '() {')
    return text[start:text.index('\n}\n', start) + 3]


class StorageAndInitramfs(unittest.TestCase):
    def shell(self, code):
        return subprocess.run(['/bin/sh', '-c', code], capture_output=True, text=True)

    def test_every_profile_emits_private_spool_only_when_enabled(self):
        profiles = sorted((SEED/'hosts/profiles').glob('*.env'))
        self.assertEqual(len(profiles), 10)
        for profile in profiles:
            for enabled in ('true', 'false'):
                with self.subTest(profile=profile.name, enabled=enabled):
                    result = self.shell(f'''
. '{profile}'
. '{SEED}/hosts/installer/runtime.env'
. '{SEED}/hosts/installer/layout.env'
. '{SEED}/scripts/late/volatile-storage.sh'
installer_fatal() {{ echo "$*" >&2; exit 91; }}
TMPFS_VAR_SPOOL_RSYSLOG={enabled}
validate_tmpfs_policy_env
fstab_entry() {{ printf '%s %s %s %s %s %s\\n' "$@"; }}
write_rsyslog_spool_fstab
''')
                    self.assertEqual(result.returncode, 0, result.stderr)
                    if enabled == 'false':
                        self.assertEqual(result.stdout, '')
                    else:
                        size = re.search(r'^SIZE_TMPFS_VAR_SPOOL_RSYSLOG_MIB="(\d+)"$',
                                         profile.read_text(), re.M).group(1)
                        self.assertEqual(result.stdout,
                                         'tmpfs /var/spool/rsyslog tmpfs rw,nodev,nosuid,noexec,'
                                         f'mode=0700,huge=within_size,size={size}M,'
                                         'x-systemd.requires-mounts-for=/var/spool 0 0\n')
        for family in ('btrfs', 'f2fs'):
            self.assertIn('write_rsyslog_spool_fstab', (SEED/f'scripts/late/{family}-family.sh').read_text())

    def test_spool_bad_sizes_are_rejected_before_emission(self):
        for size in ('0', '01', '-1', '65537', '9999999999999', '256,exec', 'true', ''):
            result = self.shell(f'''
. '{SEED}/hosts/profiles/btrfs-de.env'
. '{SEED}/hosts/installer/runtime.env'
. '{SEED}/scripts/late/volatile-storage.sh'
installer_fatal() {{ exit 91; }}
SIZE_TMPFS_VAR_SPOOL_RSYSLOG_MIB='{size}'
validate_tmpfs_policy_env
''')
            self.assertNotEqual(result.returncode, 0, size)

    def test_partman_fstab_uses_selected_spool_policy_for_both_families(self):
        source = (SEED/'hooks/installer/partman/finish.d/99-storage-layout.sh').read_text()
        def definitions(name):
            blocks = []
            offset = 0
            while f'{name}() {{' in source[offset:]:
                start = source.index(f'{name}() {{', offset)
                offset = source.index('\n}\n', start) + 3
                blocks.append(source[start:offset])
            self.assertEqual(len(blocks), 2)
            return blocks

        emitters = definitions('emit_fstab_entries')
        filters = definitions('emit_fstab_entries_without_tmpfs')
        writers = definitions('write_fstab_file')

        for profile in sorted((SEED/'hosts/profiles').glob('*.env')):
            family = profile.name.split('-', 1)[0]
            emitter = emitters[0 if family == 'btrfs' else 1]
            for enabled in ('true', 'false'):
                with self.subTest(profile=profile.name, enabled=enabled):
                    with tempfile.TemporaryDirectory() as directory:
                        target_fstab = Path(directory)/'fstab'
                        partman_cache = Path(directory)/'partman-fstab'
                        result = self.shell(f'''
. '{profile}'
. '{SEED}/hosts/installer/runtime.env'
. '{SEED}/hosts/installer/layout.env'
. '{SEED}/hosts/installer/{family}.env'
set -e
TMPFS_VAR_SPOOL_RSYSLOG={enabled}
layout_bool_is_true() {{ case "$1" in true) return 0;; *) return 1;; esac; }}
layout_syncthing_home_enabled() {{ return 1; }}
device_source() {{ printf '/dev/test\\n'; }}
fstab_entry() {{ printf '%s %s %s %s %s %s\\n' "$@"; }}
prep_dir() {{ mkdir -p "$1"; }}
{emitter}
{filters[0 if family == 'btrfs' else 1]}
{writers[0 if family == 'btrfs' else 1]}
write_fstab_file '{target_fstab}' 1 1
write_fstab_file '{partman_cache}' 0 0
''')
                        self.assertEqual(result.returncode, 0, result.stderr)
                        fstab_text = target_fstab.read_text()
                        cache_text = partman_cache.read_text()
                    rows = [line.split() for line in fstab_text.splitlines()
                            if line and not line.startswith('#')]
                    spool = [row for row in rows if len(row) >= 3 and row[1] == '/var/spool/rsyslog']
                    self.assertEqual(len(spool), int(enabled == 'true'))
                    if spool:
                        self.assertEqual(spool[0][0:3], ['tmpfs', '/var/spool/rsyslog', 'tmpfs'])
                        self.assertIn('mode=0700', spool[0][3])
                        self.assertIn('x-systemd.requires-mounts-for=/var/spool', spool[0][3])
                    backing = '/var/spool' if family == 'btrfs' else '/'
                    self.assertEqual(len([row for row in rows if len(row) >= 3
                                          and row[1] == backing and row[2] == family]), 1)
                    self.assertNotIn('/var/spool/rsyslog', cache_text)
                    self.assertIn(f'/dev/test {backing} {family} ', cache_text)

    def test_partman_validates_spool_policy_before_writing_fstab(self):
        source = SEED/'hooks/installer/partman/finish.d/99-storage-layout.sh'
        functions = '\n'.join(shell_function(source, name) for name in
                              ('layout_bool_is_true', 'layout_bool_is_false',
                               'require_layout_bool', 'validate_tmpfs_policy_config'))
        profile = SEED/'hosts/profiles/btrfs-de.env'
        for override, accepted in (('', True),
                                   ('TMPFS_VAR_SPOOL_RSYSLOG=false', True),
                                   ('TMPFS_VAR_SPOOL_RSYSLOG=invalid', False),
                                   ('SIZE_TMPFS_VAR_SPOOL_RSYSLOG_MIB=01', False),
                                   ('DIR_VAR_SPOOL_RSYSLOG=/unmanaged', False)):
            with self.subTest(override=override):
                result = self.shell(f'''
. '{profile}'
. '{SEED}/hosts/installer/runtime.env'
. '{SEED}/hosts/installer/layout.env'
{override}
fatal() {{ printf '%s\\n' "$*" >&2; exit 91; }}
{functions}
validate_tmpfs_policy_config
''')
                self.assertEqual(result.returncode == 0, accepted, result.stderr)

    def test_finish_normalizer_accepts_only_the_selected_spool_mount(self):
        source = SEED/'hooks/installer/finish-install.d/99-normalize-finish'
        functions = '\n'.join(shell_function(source, name) for name in
                              ('managed_tmpfs_mount_mode', 'normalize_target_fstab_tmpfs_dirs'))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'etc').mkdir()
            options = ('rw,nodev,nosuid,noexec,mode=0700,huge=within_size,'
                       'size=256M,x-systemd.requires-mounts-for=/var/spool')
            spool = f'tmpfs /var/spool/rsyslog tmpfs {options} 0 0\n'
            cases = ((True, spool, True), (False, '', True),
                     (True, '', False), (False, spool, False),
                     (True, spool + spool, False),
                     (True, spool.replace('mode=0700', 'mode=0755'), False),
                     (True, 'tmpfs /unmanaged tmpfs defaults 0 0\n', False))
            for enabled, extra, accepted in cases:
                with self.subTest(enabled=enabled, extra=extra, accepted=accepted):
                    (root/'etc/fstab').write_text('tmpfs /tmp tmpfs defaults 0 0\n' + extra)
                    result = self.shell(f'''
. '{SEED}/hosts/profiles/btrfs-de.env'
. '{SEED}/hosts/installer/runtime.env'
. '{SEED}/hosts/installer/layout.env'
set -eu
TARGET='{root}'
TMPFS_VAR_SPOOL_RSYSLOG={'true' if enabled else 'false'}
log() {{ printf '%s\\n' "$*" >&2; }}
bool_is_true() {{ [ "$1" = true ]; }}
require_absolute_path() {{ case "$1" in /*) :;; *) exit 90;; esac; }}
target_path_for() {{ printf '%s%s\\n' "$TARGET" "$1"; }}
ensure_empty_dir_mode() {{ printf '%s %s\\n' "$2" "$3"; }}
{functions}
normalize_target_fstab_tmpfs_dirs
''')
                    self.assertEqual(result.returncode == 0, accepted, result.stderr)
                    if accepted and enabled:
                        self.assertIn('target fstab tmpfs mountpoint /var/spool/rsyslog 0700',
                                      result.stdout)
                    if accepted and not enabled:
                        self.assertNotIn('/var/spool/rsyslog 0700', result.stdout)

    def test_actual_initramfs_function_rejects_current_and_obsolete_secret(self):
        function = shell_function(SEED/'scripts/late/crypto.sh', 'crypto_verify_initramfs')
        safe = ('scripts/local-top/00-tpm2-cryptroot\nscripts/local-top/cryptroot\n'
                'usr/lib/libcryptsetup-token-systemd-tpm2.so\netc/tpm2-cryptroot.conf\n')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'boot').mkdir()
            (root/'boot/initrd.img-test').touch()
            listing = root/'listing'
            paths = ('', 'var/lib/tpm2-enrollment/install-passphrase',
                     './var/lib/tpm2-enrollment/install-passphrase',
                     '/var/lib/tpm2-enrollment/install-passphrase',
                     'usr/local/lib/crypto/install-passphrase',
                     'var/lib/tpm2-enrollment/config.env', 'etc/cryptsetup-keys.d/crypthome.key')
            for member in paths:
                listing.write_text(safe + member + '\n')
                result = self.shell(function + f'''
target_root='{root}'
tmp_env_dir='{root}'
install_passphrase_target=/var/lib/tpm2-enrollment/install-passphrase
run_in_target() {{ cat '{listing}'; }}
crypto_fatal() {{ echo "$*" >&2; exit 93; }}
crypto_verify_initramfs
''')
                self.assertEqual(result.returncode == 0, not bool(member), (member, result.stderr))


@unittest.skipUnless(os.geteuid() == 0, 'real root/nonroot metadata fixtures')
class TailscaleMetadata(unittest.TestCase):
    def test_safe_package_modes_and_unsafe_metadata(self):
        text = (SEED/'scripts/late/tailscale.sh').read_text()
        start = text.index('for config_file in "$FILE_TAILSCALED_DEFAULT"')
        block = text[start:text.index('unset config_file config_parent', start)]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'etc/default').mkdir(parents=True, mode=0o755)
            a, b = root/'etc/default/tailscaled', root/'etc/default/syncthing'
            for mode in (0o400, 0o440, 0o444, 0o600, 0o640, 0o644, 0o700, 0o750, 0o755, 0o660, 0o666, 0o777):
                a.write_text('not executed\n'); a.chmod(mode)
                code = f'''. '{installed_script(SEED / 'scripts/common/lib.sh')}'
target_root='{root}'
FILE_TAILSCALED_DEFAULT=/etc/default/tailscaled
FILE_MANAGED_SYNCTHING_DEFAULT=/etc/default/syncthing
tailscale_fatal() {{ echo "$*" >&2; exit 94; }}
''' + block
                result = subprocess.run(['/bin/sh','-c', code], capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, not bool(mode & 0o022), (oct(mode), result.stderr))
            a.chmod(0o644)
            for attack in ('symlink', 'hardlink', 'nonroot'):
                a.unlink(missing_ok=True)
                b.unlink(missing_ok=True)
                b.write_text('fixture'); b.chmod(0o644)
                if attack == 'symlink': a.symlink_to(b)
                elif attack == 'hardlink': os.link(b, a)
                else: a.write_text('fixture'); os.chown(a, pwd.getpwnam('nobody').pw_uid, 0)
                result = subprocess.run(['/bin/sh','-c', code], capture_output=True)
                self.assertNotEqual(result.returncode, 0, attack)


class SudoAndFirewall(unittest.TestCase):
    def test_readonly_sudo_excludes_mutating_arguments(self):
        text = (SEED/'hooks/target/etc/sudoers.d/account.tmpl').read_text()
        regexes = re.findall(r'/usr/bin/(?:systemctl|journalctl) (\^[^\n]+\$)', text)
        self.assertEqual(len(regexes), 2)
        accepted = ('--no-pager status ssh.service', '--no-pager -u ssh.service -n 200')
        rejected = ('--no-pager status ssh --force', '--no-pager status --root=/tmp',
                    '--no-pager -u ssh --vacuum-size=1 -n 200', '--no-pager -u ssh --rotate -n 200',
                    '--no-pager status ssh.service\nreboot', '--no-pager status ssh.service --system')
        for value in accepted: self.assertTrue(any(re.fullmatch(r, value) for r in regexes), value)
        for value in rejected: self.assertFalse(any(re.fullmatch(r, value) for r in regexes), value)
        self.assertIn('/usr/bin/dmesg "",', text)
        self.assertNotRegex(text, r'/usr/bin/dmesg\s*,')
        if shutil.which('visudo'):
            with tempfile.NamedTemporaryFile(mode='w') as stream:
                stream.write(text.replace('__INSTALLER_ACCOUNT_USERNAME__', 'nobody')); stream.flush()
                result = subprocess.run(['visudo','-cf',stream.name],capture_output=True)
                self.assertEqual(result.returncode,0,result.stderr)

    def test_nft_only_owns_fixed_tables(self):
        m = module(SEED/'hooks/target/usr/local/sbin/nft-policy-generate.py')
        paths = {k: Path('/etc/nftables.d')/(k+'.nft') for k in ('defines','base','filter','nat','local')}
        text = m.render_nftables_conf({}, paths)
        self.assertNotIn('flush ruleset', text)
        self.assertEqual(re.findall(r'^destroy table (.*)$',text,re.M), ['inet labwc_filter','ip labwc_nat'])
        for p in ({'generator':{'nftables_conf':{'flush_ruleset': True}}},
                  {'nftables':{'filter_table':'crowdsec'}}, {'nftables':{'nat_table':'tailscale'}}):
            with self.assertRaises(m.PolicyError): m.render_nftables_conf(p, paths)
        self.assertIn('include "/etc/nftables.local.d/*.nft"', m.render_local({}))
        self.assertNotIn('flush ruleset', (SEED/'hooks/target/etc/systemd/system/nftables.service.d/override.conf').read_text())

    @unittest.skipUnless(shutil.which('nft') and shutil.which('unshare'), 'nft/unshare are unavailable')
    def test_nft_foreign_table_survives_real_transaction(self):
        code = '''nft add table inet foreign_fixture &&
nft add chain inet foreign_fixture keep &&
nft -f - <<'EOF'
destroy table inet labwc_filter
destroy table ip labwc_nat
table inet labwc_filter { chain input { } }
EOF
nft list chain inet foreign_fixture keep
'''
        probe = subprocess.run(['unshare','-n','true'],capture_output=True)
        if probe.returncode: self.skipTest('network namespace creation is not permitted')
        result = subprocess.run(['unshare','-n','/bin/sh','-ec',code],capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)


class OpenVPN(unittest.TestCase):
    def setUp(self): self.m = module(LIBEXEC/'network-openvpn-import')

    def test_self_contained_profile(self):
        self.m.validate_profile(b'client\nremote vpn.example 1194 udp\nauth-user-pass\n<ca>\nfixture\n</ca>\n')

    def test_external_references_and_grammar_differentials_rejected(self):
        for value in (b'config /etc/shadow', b'ca /etc/shadow', b'auth-user-pass /etc/shadow',
                      b'up /bin/sh', b'plugin /tmp/m.so', b'--client', b'client\\\nup /tmp/a',
                      b'<ca>\n</ca>junk\nca /etc/shadow\n</ca>', b'client\x00', b'client\vup /bin/sh',
                      b'<key>\nx\n', b'http-proxy host 443 /etc/shadow', b'<ca>\nx\n</ca>\n<ca>\ny\n</ca>'):
            with self.subTest(value=value), self.assertRaises((ValueError, UnicodeError)):
                self.m.validate_profile(value)

    @unittest.skipUnless(os.geteuid() == 0, 'unprivileged subprocess credential-drop fixture')
    def test_reader_drops_privilege_and_rejects_links(self):
        uid = pwd.getpwnam('nobody').pw_uid
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory); parent.chmod(0o755)
            source = parent/'test.ovpn'; source.write_bytes(b'client\n'); os.chown(source,uid,0); source.chmod(0o600)
            argv = ['/usr/bin/python3','-I',str(LIBEXEC/'network-openvpn-import'),'--read',str(uid),str(source)]
            result = subprocess.run(argv,capture_output=True)
            self.assertEqual((result.returncode,result.stdout),(0,b'client\n'),result.stderr)
            source.unlink(); source.symlink_to('/etc/shadow')
            self.assertNotEqual(subprocess.run(argv,capture_output=True).returncode,0)
            source.unlink(); source.write_bytes(b'client\n'); source.chmod(0o600)
            self.assertNotEqual(subprocess.run(argv,capture_output=True).returncode,0)

    @unittest.skipUnless(os.geteuid() == 0, 'root-private snapshot fixture')
    def test_parser_receives_snapshot_not_reopened_caller_path(self):
        captured = []
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory)/'input.ovpn'; original.write_bytes(b'client\n')
            def run(argv, **kwargs):
                if '--read' in argv:
                    data = original.read_bytes(); original.write_bytes(b'ca /etc/shadow\n')
                    return types.SimpleNamespace(returncode=0,stdout=data)
                snapshot = Path(argv[-1]); captured.append(snapshot)
                self.assertNotEqual(snapshot,original)
                self.assertEqual(snapshot.read_bytes(),b'client\n')
                self.assertEqual(stat.S_IMODE(snapshot.stat().st_mode),0o600)
                self.assertEqual(stat.S_IMODE(snapshot.parent.stat().st_mode),0o700)
                self.assertEqual(kwargs['env']['HOME'],'/root')
                return types.SimpleNamespace(returncode=0)
            old = os.umask(0o077)
            try:
                with mock.patch.object(self.m.subprocess,'run',side_effect=run):
                    self.assertEqual(self.m.main(['65534',str(original)]),0)
            finally: os.umask(old)
            self.assertTrue(captured)
            self.assertFalse(captured[0].exists())


class TutaExtraction(unittest.TestCase):
    def setUp(self): self.m = module(LIBEXEC/'tuta-extract')

    def image(self):
        header = bytearray(64); header[:6]=b'\x7fELF\x02\x01';header[8:11]=b'AI\x02'
        struct.pack_into('<H',header,18,62);struct.pack_into('<Q',header,40,64);struct.pack_into('<HH',header,58,64,1)
        section=bytes(64);sq=bytearray(96);sq[:4]=b'hsqs';struct.pack_into('<I',sq,4,1)
        struct.pack_into('<HH',sq,28,4,0);struct.pack_into('<Q',sq,40,96)
        return bytes(header)+section+sq

    def test_offset_reads_metadata_without_execution(self):
        with tempfile.TemporaryFile() as stream:
            stream.write(self.image()); stream.seek(0)
            self.assertEqual(self.m.squashfs_offset(stream),128)
        # A padded runtime is still a Type-2 AppImage; do not execute it to
        # discover the payload offset or mistake a magic string for a superblock.
        padded = self.image()[:128] + b'hsqs' + bytes(124) + self.image()[128:]
        with tempfile.TemporaryFile() as stream:
            stream.write(padded); stream.seek(0)
            self.assertEqual(self.m.squashfs_offset(stream),256)
        stripped = bytearray(64)
        stripped[:6]=b'\x7fELF\x02\x01'; stripped[8:11]=b'AI\x02'
        struct.pack_into('<H',stripped,18,62)
        struct.pack_into('<Q',stripped,32,64)
        struct.pack_into('<HH',stripped,54,56,1)
        program = bytearray(56)
        struct.pack_into('<Q',program,8,64)
        struct.pack_into('<Q',program,32,56)
        with tempfile.TemporaryFile() as stream:
            stream.write(stripped + program + self.image()[128:]); stream.seek(0)
            self.assertEqual(self.m.squashfs_offset(stream),120)
        with mock.patch.object(self.m, 'MAX_RUNTIME_TRAILER', 64):
            with tempfile.TemporaryFile() as stream:
                stream.write(padded); stream.seek(0)
                with self.assertRaises(ValueError): self.m.squashfs_offset(stream)
        for bad in (b'#!/bin/sh\n', self.image()[:100], self.image().replace(b'hsqs',b'bad!')):
            with tempfile.TemporaryFile() as stream:
                stream.write(bad); stream.seek(0)
                with self.assertRaises(ValueError): self.m.squashfs_offset(stream)

    def test_sandbox_is_dedicated_no_network_no_host_home_and_no_appimage_exec(self):
        argv=self.m.sandbox_command(Path('/private/image'),Path('/private/output'),128,123,124)
        for value in ('--unshare-pid','--unshare-net','--unshare-ipc','--no-new-privs','--bounding-set=-all','--reuid=123','--regid=124','/usr/bin/unsquashfs'):
            self.assertIn(value,argv)
        # bwrap changes directory before setpriv changes uid. The private
        # /output mount must only be entered by the parser after that switch.
        self.assertEqual(argv[argv.index('--chdir') + 1], '/')
        self.assertEqual(argv[argv.index('--bind') + 1:argv.index('--bind') + 3],
                         ['/private/output', '/output'])
        self.assertEqual(argv[argv.index('-dest') + 1], '/output/tree')
        self.assertNotIn('--appimage-extract',argv);self.assertNotIn('/root',argv);self.assertNotIn('/home',argv)
        self.assertIn('tuta-extract', (SEED/'hooks/target/usr/lib/sysusers.d/tuta-extract.conf').read_text())

    def test_failure_reports_the_rejected_condition(self):
        result=subprocess.run([sys.executable,'-I',str(LIBEXEC/'tuta-extract')],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('ValueError: usage: tuta-extract ARTIFACT NEW_DESTINATION SHA256',result.stderr)

    def test_parser_reports_child_failure_without_blocking_on_output(self):
        with tempfile.TemporaryDirectory() as directory:
            command = [
                sys.executable, '-I', '-c',
                'import os,sys; os.write(1,b"x"*131072); '
                'os.write(2,b"bwrap: failed to open /proc\\n"); sys.exit(42)',
            ]
            failure = r'isolated packaged extractor exited 42: .*bwrap: failed to open /proc'
            with self.assertRaisesRegex(ValueError, failure):
                self.m.run_parser(command, Path(directory))

    def test_extraction_requires_procfs_and_the_installer_target_executor(self):
        with mock.patch.object(self.m.Path,'read_text',side_effect=FileNotFoundError):
            with self.assertRaisesRegex(ValueError,'procfs is required'):
                self.m.extractor_identity()
        source = (SEED/'scripts/late/software.sh.tmpl').read_text()
        begin = source.index("# d-i's target executor mounts /proc")
        tuta = source[begin:source.index('tuta_icon_source=', begin)]
        self.assertIn('INSTALLER_TARGET_DIR="$target_root" target_exec /bin/sh -eu -c',tuta)
        self.assertNotIn('chroot "$target_root" /bin/sh -eu -c',tuta)

    @unittest.skipUnless(os.geteuid()==0,'root publication metadata fixture')
    def test_tree_modes_and_escape_special_hardlink_rejection(self):
        for attack in ('none','internal-apprun-link','escape','fifo','hardlink','escape-apprun'):
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory)/'extracted';root.mkdir()
                app=root/'AppRun';app.write_bytes(b'fixture');app.chmod(0o6755)
                if attack=='escape':(root/'bad').symlink_to('/etc/shadow')
                if attack=='fifo':os.mkfifo(root/'bad')
                if attack=='hardlink':os.link(app,root/'bad')
                if attack=='internal-apprun-link':
                    (root/'bin').mkdir()
                    app.rename(root/'bin/tuta')
                    app.symlink_to('bin/tuta')
                if attack=='escape-apprun':
                    app.unlink();app.symlink_to('/etc/shadow')
                if attack in ('none','internal-apprun-link'):
                    self.m.normalize_tree(root)
                    self.assertEqual(stat.S_IMODE(app.stat().st_mode),0o755)
                    if attack=='internal-apprun-link':
                        published=Path(directory)/'published'
                        shutil.copytree(root,published,symlinks=True)
                        self.assertTrue((published/'AppRun').is_file())
                        self.assertTrue(os.access(published/'AppRun',os.X_OK))
                else:
                    with self.assertRaises(ValueError):self.m.normalize_tree(root)

    @unittest.skipUnless(os.geteuid()==0,'root publication fixture')
    def test_hash_mismatch_never_starts_parser_or_publishes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);image=root/'input';image.write_bytes(self.image());destination=root/'new'
            with mock.patch.object(self.m.subprocess,'Popen') as parser:
                with self.assertRaises(ValueError):self.m.extract(image,destination,'0'*64,65534,65534)
                parser.assert_not_called()
            self.assertFalse(destination.exists())
            self.assertFalse(list(root.glob('.tuta-extract-*')))

    def test_inner_sandbox_exceptions_are_removed(self):
        text=(SEED/'hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/profiles.py.tmpl').read_text()
        self.assertNotIn('MOZ_DISABLE_RDD_SANDBOX',text)
        self.assertIn('"inner_sandbox_args": ("--enable-sandbox",)',text)
        self.assertNotIn('"inner_sandbox_args": ("--no-sandbox",)',text)

    def test_privileged_helper_apparmor_transitions_are_explicit_and_scoped(self):
        text=(SEED/'hooks/target/etc/apparmor.d/desktop-wrappers.tmpl').read_text()
        def profile(name):
            begin=text.index('profile '+name+' ')
            return text[begin:text.index('\n}\n',begin)+3]
        root=profile('labwc-network-control-action-root')
        update=profile('apt-repo-local-software-update')
        reader=profile('network-openvpn-import')
        extract=profile('tuta-extract')
        self.assertIn('/usr/local/libexec/network-openvpn-import rPx -> network-openvpn-import,',root)
        self.assertIn('/usr/local/libexec/tuta-extract rPx -> tuta-extract,',update)
        self.assertNotIn('tutanota-desktop-linux.AppImage',update)
        self.assertIn('capability setuid,',reader)
        self.assertIn('capability setgid,',reader)
        self.assertIn('owner /**.ovpn r,',reader)
        self.assertIn('/run/network-openvpn-*/*.ovpn rw,',reader)
        self.assertIn('/usr/bin/bwrap rCx -> unpack,',extract)
        self.assertIn('  profile unpack flags=(attach_disconnected, mediate_deleted) {',extract)
        self.assertIn('    / r,\n    /usr/bin/{bwrap,setpriv,unsquashfs} rix,',extract)
        self.assertIn('/output/{,**} rwkl,',extract)
        self.assertNotRegex(extract,r'AppImage.*[puPU]?[ix],')
        self.assertNotIn('flags=(unconfined',extract)



class TPMPolicy(unittest.TestCase):
    def setUp(self): self.m=module(LIBEXEC/'tpm2-policy-check')

    def token(self):
        return {'tokens':{'0':{'type':'systemd-tpm2','tpm2-pin':True,'tpm2-pcr-bank':'sha256',
                               'tpm2-pcrs':[7,8,9,14],'keyslots':['1']}},'keyslots':{'1':{'type':'luks2'}}}

    def test_strict_final_token_policy(self):
        self.assertEqual(self.m.validate_token(self.token()),'0')
        for key,value in (('tpm2-pin',False),('tpm2-pcr-bank','sha1'),('tpm2-pcrs',[7]),('tpm2-pcrlock',True),('keyslots',['9'])):
            document=self.token();document['tokens']['0'][key]=value
            with self.assertRaises(ValueError):self.m.validate_token(document)
        document=self.token();document['tokens']['2']=copy.deepcopy(document['tokens']['0'])
        with self.assertRaises(ValueError):self.m.validate_token(document)

    def test_verification_is_token_only_nonmutating_and_detects_metadata_change(self):
        m=self.m;document=self.token()
        with mock.patch.object(m,'metadata',return_value=document),mock.patch.object(m,'command') as command:
            m.verify_pin('/dev/fixture',b'123456')
            argv=command.call_args.args[0]
            for value in ('--token-only','--test-passphrase','--token-id'):self.assertIn(value,argv)
            self.assertNotIn('--key-file',argv);self.assertNotIn('systemd-cryptenroll',argv[0])
        with mock.patch.object(m,'metadata',side_effect=[document,{}]),mock.patch.object(m,'command'):
            with self.assertRaises(ValueError):m.verify_pin('/dev/fixture',b'123456')

    def eventlog(self):
        spec=bytearray(33);spec[:16]=b'Spec ID Event03\x00';struct.pack_into('<I',spec,24,1);struct.pack_into('<HH',spec,28,11,32)
        data=struct.pack('<II',0,3)+bytes(20)+struct.pack('<I',len(spec))+spec
        for index,kind,event in ((7,13,b'secureboot'),(8,13,b'kernel_cmdline: root=fixture'),(9,6,b'/initrd.img'),(14,13,b'mok')):
            data+=struct.pack('<IIIH',index,kind,1,11)+hashlib.sha256(event).digest()+struct.pack('<I',len(event))+event
        return data

    def test_eventlog_replay_requires_actual_measured_events(self):
        values,initrd,cmdline=self.m.replay_eventlog(self.eventlog())
        self.assertTrue(initrd and cmdline);self.assertEqual(set(values),{7,8,9,14})
        self.assertTrue(all(v!=bytes(32) for v in values.values()))
        for raw in (b'',self.eventlog()[:-1],self.eventlog()+b'bad'):
            with self.assertRaises(ValueError):self.m.replay_eventlog(raw)

    @unittest.skipUnless(os.geteuid()==0,'private durable state fixture')
    def test_completion_requires_another_boot_and_unchanged_proof(self):
        with tempfile.TemporaryDirectory(dir='/root') as directory:
            self.m.STATE=Path(directory)
            (self.m.STATE/'tpm2-enroll.pending').write_bytes(b'pending');(self.m.STATE/'tpm2-enroll.pending').chmod(0o600)
            with mock.patch.object(self.m,'verify_boot_evidence',return_value={'7':'a'}),mock.patch.object(self.m,'verify_initramfs'),mock.patch.object(self.m,'fingerprints',return_value={'root':'digest'}),mock.patch.object(self.m,'boot_id',return_value='first') as boot:
                self.m.record_state({},'enrolled')
                with self.assertRaises(ValueError):self.m.record_state({},'complete')
                self.assertTrue((self.m.STATE/'tpm2-enroll.pending').exists())
                boot.return_value='second';self.m.record_state({},'complete')
                self.assertFalse((self.m.STATE/'tpm2-enroll.pending').exists())
                record=json.loads((self.m.STATE/'enrollment.json').read_text())
                self.assertEqual((record['enrolled_boot_id'],record['verified_boot_id']),('first','second'))


@unittest.skipUnless(os.geteuid()==0,'root-private sealing fixture; journalctl is mocked')
class JournalSealing(unittest.TestCase):
    def setUp(self):
        self.m=module(LIBEXEC/'journal-sealing')
        self.temp=tempfile.TemporaryDirectory(dir='/root');self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);self.m.STATE=root/'state';self.m.RUNTIME=root/'run'
        self.m.STATE.mkdir(mode=0o700);self.m.RUNTIME.mkdir(mode=0o700)
        self.m.KEY=self.m.RUNTIME/'verification-key';self.m.RECORD=self.m.STATE/'status.json'
        self.fss=root/'fss';self.key=b'aaaaaa-bbbbbb-cccccc-dddddd-eeeeee-ff/1234-abcd\n'

    def fake_setup(self,argv,**kwargs):
        self.assertIn('--setup-keys',argv);self.assertNotIn('--force',argv)
        kwargs['stdout'].write(self.key);self.fss.write_bytes(b'fixture-fss');self.fss.chmod(0o600)
        return types.SimpleNamespace(returncode=0)

    def test_explicit_key_setup_and_rotation_not_repeated(self):
        with mock.patch.object(self.m.subprocess,'run',side_effect=self.fake_setup) as setup,mock.patch.object(self.m,'command') as command:
            record=self.m.setup('machine',self.fss)
            self.assertFalse(record['exported']);self.assertTrue(record['rotated'])
            self.assertEqual(record['verification_sha256'],hashlib.sha256(self.key).hexdigest())
            self.m.setup('machine',self.fss)
            self.assertEqual(setup.call_count,1);self.assertEqual(command.call_count,1)
            self.assertNotIn(self.key.strip(),self.m.RECORD.read_bytes())

    def test_lost_seed_never_replaces_existing_fss_generation(self):
        with mock.patch.object(self.m.subprocess,'run',side_effect=self.fake_setup),mock.patch.object(self.m,'command'):
            self.m.setup('machine',self.fss)
        self.m.KEY.unlink()
        with mock.patch.object(self.m.subprocess,'run') as setup:
            with self.assertRaises(OSError):self.m.setup('machine',self.fss)
            setup.assert_not_called()

    def test_foreign_preexisting_state_requires_recovery(self):
        self.fss.write_bytes(b'existing');self.fss.chmod(0o600)
        with mock.patch.object(self.m.subprocess,'run') as setup:
            with self.assertRaises(OSError):self.m.setup('machine',self.fss)
            setup.assert_not_called()


if __name__=='__main__':unittest.main()
