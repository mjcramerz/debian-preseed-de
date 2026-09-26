"""Offline compz regression tests; native codec tests skip absent executables.

No test claims live AppArmor mediation or a booted systemd user service.
Production namespace and lifecycle arguments are checked independently of the
real core Perl streaming pipeline and the available codec round trips.
"""
from __future__ import annotations

from contextlib import ExitStack
import gzip
import io
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from unittest import mock

FORKY = Path(__file__).resolve().parents[1]
TARGET = FORKY / 'hooks/target'
MODULES = TARGET / 'usr/local/lib/python3.14/dist-packages'
PERL = TARGET / 'usr/local/lib/perl5/site_perl/labwc-compz'
sys.path.insert(0, str(MODULES))
from labwc_compz import CompzError
from labwc_compz import cli, formats, isolation, safeio, volumes, worker


def plan(**changes):
    result = dict(action='extract', selected=['archive.tar'], codec='gzip', tier=0,
                  output='archive', encrypted=False, nested=False, max_bytes=64 * 1024**2,
                  max_files=10000, memory_mib=512, threads=1, hours=1, depth=8)
    result.update(changes)
    return result


def tar_bytes(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w', format=tarfile.PAX_FORMAT) as archive:
        for item, data in entries:
            if isinstance(item, str):
                item = tarfile.TarInfo(item)
                item.size = len(data)
            archive.addfile(item, io.BytesIO(data) if item.isreg() else None)
    return output.getvalue()


class Temporary(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='compz-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def files(self, *names, data=b'fixture'):
        for name in names:
            (self.root / name).write_bytes(data)
        return self.root / names[-1]


class SafeIOTests(Temporary):
    def extract(self, data, **limits):
        destination = self.root / 'output'
        destination.mkdir(exist_ok=True)
        safeio.extract_tar(io.BytesIO(data), destination,
                          safeio.Budget(limits.get('bytes', 16 * 1024**2), limits.get('files', 10000)))
        return destination

    def test_thousands_of_files_and_arbitrary_names_round_trip(self):
        source = self.root / 'source'
        source.mkdir()
        tree = source / 'tree'
        tree.mkdir()
        expected = {f'file-{i:05d}': str(i).encode() for i in range(2500)}
        expected.update({'line\nbreak': b'LF', 'tab\tname': b'tab', '-rf': b'not an option',
                         'snowman-\u2603': b'UTF8', 'raw-\udcff': b'undecodable',
                         'quote\'"$;`': b'not shell code'})
        for name, value in expected.items():
            (tree / name).write_bytes(value)
        stream = io.BytesIO()
        safeio.produce_tar(source, ['tree'], stream, safeio.Budget(16 * 1024**2, 10000))
        output = self.extract(stream.getvalue())
        self.assertEqual({p.name: p.read_bytes() for p in (output / 'tree').iterdir()}, expected)
        self.assertEqual(safeio.audit(output, 16 * 1024**2, 10000)[1], len(expected) + 1)

    def test_reject_unsafe_names(self):
        for name in ('../outside', '/absolute', 'a/../../escape', 'a//b', 'C:/drive',
                     'back\\slash', 'a/./b', 'a/' * 129 + 'deep', 'x' * 256, '\0'):
            with self.subTest(name=repr(name)), self.assertRaises(CompzError):
                safeio.relative(name)

    def test_traversal_tar_does_not_write_outside(self):
        with self.assertRaises(CompzError):
            self.extract(tar_bytes([('../escape', b'bad')]))
        self.assertFalse((self.root / 'escape').exists())

    def test_duplicate_paths_rejected(self):
        with self.assertRaises(CompzError):
            self.extract(tar_bytes([('same', b'first'), ('./same', b'second')]))
        self.assertEqual((self.root / 'output/same').read_bytes(), b'first')

    def test_links_devices_fifo_sparse_rejected(self):
        for member_type in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE,
                            tarfile.BLKTYPE, tarfile.FIFOTYPE, tarfile.GNUTYPE_SPARSE):
            member = tarfile.TarInfo('unsafe')
            member.type = member_type
            member.linkname = '/etc/passwd'
            with self.subTest(member_type=member_type), self.assertRaises(CompzError):
                self.extract(tar_bytes([(member, b'')]))

    def test_byte_budget(self):
        with self.assertRaises(CompzError):
            self.extract(tar_bytes([('data', b'12345')]), bytes=4)

    def test_file_budget(self):
        with self.assertRaises(CompzError):
            self.extract(tar_bytes([('one', b''), ('two', b'')]), files=1)

    def test_truncated_data(self):
        data = tar_bytes([('large', b'a' * 2048)])
        with self.assertRaises(CompzError):
            self.extract(data[:600])

    def test_modes_are_sanitized(self):
        member = tarfile.TarInfo('executable')
        member.size = 3
        member.mode = 0o6777
        member.uid = 65534
        member.gid = 65534
        output = self.extract(tar_bytes([(member, b'run')]))
        self.assertEqual(stat.S_IMODE((output / 'executable').stat().st_mode), 0o700)
        self.assertEqual((output / 'executable').stat().st_uid, os.geteuid())

    def test_producer_rejects_symlink_and_fifo(self):
        for leaf in ('link', 'fifo'):
            if leaf == 'link':
                (self.root / leaf).symlink_to('/etc/passwd')
            else:
                os.mkfifo(self.root / leaf)
            with self.subTest(leaf=leaf), self.assertRaises(CompzError):
                safeio.produce_tar(self.root, [leaf], io.BytesIO(), safeio.Budget(10000, 100))

    def test_existing_output_never_replaced(self):
        self.files('source', data=b'new')
        self.files('destination', data=b'old')
        with self.assertRaises(CompzError):
            safeio.publish(self.root / 'source', self.root / 'destination')
        self.assertEqual((self.root / 'destination').read_bytes(), b'old')
        self.assertEqual((self.root / 'source').read_bytes(), b'new')

    def test_atomic_publication(self):
        self.files('source', data=b'complete')
        safeio.publish(self.root / 'source', self.root / 'destination')
        self.assertFalse((self.root / 'source').exists())
        self.assertEqual((self.root / 'destination').read_bytes(), b'complete')

    def test_audit_rejects_symlink(self):
        (self.root / 'bad').symlink_to('/etc/passwd')
        with self.assertRaises(CompzError):
            safeio.audit(self.root, 1000, 100)

    def test_audit_rejects_hardlinks(self):
        self.files('one')
        os.link(self.root / 'one', self.root / 'two')
        with self.assertRaises(CompzError):
            safeio.audit(self.root, 1000, 100)

    def test_audit_removes_file_directory_and_root_xattrs(self):
        self.files('one')
        (self.root / 'dir').mkdir()
        for path in (self.root, self.root / 'dir', self.root / 'one'):
            try:
                os.setxattr(path, 'user.compz-test', b'drop')
            except OSError as exc:
                self.skipTest('test filesystem has no writable user xattrs: ' + str(exc))
        safeio.audit(self.root, 1000, 100, sanitize=True)
        for path in (self.root, self.root / 'dir', self.root / 'one'):
            self.assertEqual(os.listxattr(path), [])

    def test_terminal_escape_sanitization(self):
        result = safeio.display('a\x1b]8;;bad\a\n\u202e')
        self.assertTrue(result.isascii())
        self.assertNotIn('\x1b', result)
        self.assertNotIn('\n', result)


class VolumeTests(Temporary):
    def names(self, path):
        return [p.name for p in volumes.resolve(path).members]

    def test_modern_rar_from_any_volume(self):
        names = ['movie.part001.rar', 'movie.part002.rar', 'movie.part003.rar']
        self.files(*names)
        for name in names:
            self.assertEqual(self.names(self.root / name), names)
            self.assertEqual(volumes.resolve(self.root / name).name, 'movie')

    def test_classic_rar_from_any_volume(self):
        names = ['movie.rar', 'movie.r00', 'movie.r01', 'movie.r02']
        self.files(*names)
        for name in names:
            self.assertEqual(self.names(self.root / name), names)
            self.assertFalse(volumes.resolve(self.root / name).concatenate)

    def test_three_digit_rar_with_rar_head(self):
        names = ['movie.rar', 'movie.r001', 'movie.r002']
        self.files(*names)
        self.assertEqual(self.names(self.root / names[-1]), names)

    def test_standalone_three_digit_head(self):
        names = ['movie.r001', 'movie.r002', 'movie.r003']
        self.files(*names, data=b'Rar!\x1a\x07\x01\x00fixture')
        self.assertEqual(self.names(self.root / names[-1]), names)

    def test_numbered_head_requires_rar_signature(self):
        self.files('movie.r001', 'movie.r002')
        with self.assertRaises(CompzError):
            volumes.resolve(self.root / 'movie.r002')

    def test_missing_intermediate_volume(self):
        self.files('movie.part01.rar', 'movie.part03.rar')
        with self.assertRaises(CompzError):
            volumes.resolve(self.root / 'movie.part03.rar')

    def test_missing_first_volume(self):
        self.files('movie.r02', 'movie.r03')
        with self.assertRaises(CompzError):
            volumes.resolve(self.root / 'movie.r03')

    def test_mixed_width_rejected(self):
        self.files('movie.part01.rar', 'movie.part002.rar')
        with self.assertRaises(CompzError):
            volumes.resolve(self.root / 'movie.part01.rar')

    def test_unpadded_modern_rar_number_rollover(self):
        names = [f'movie.part{i}.rar' for i in range(1, 12)]
        self.files(*names)
        self.assertEqual(self.names(self.root / names[-1]), names)

    def test_padded_modern_rar_number_rollover(self):
        names = [f'movie.part{i:02d}.rar' for i in range(1, 102)]
        self.files(*names)
        self.assertEqual(self.names(self.root / names[-1]), names)

    def test_classic_rar_letter_rollover(self):
        names = ['movie.rar'] + [f'movie.r{i:02d}' for i in range(100)] + ['movie.s00', 'movie.s01']
        self.files(*names)
        for selected in ('movie.rar', 'movie.r99', 'movie.s01'):
            self.assertEqual(self.names(self.root / selected), names)
        self.assertTrue(volumes.recognizable('movie.s01'))

    def test_classic_letter_rollover_gap_refused(self):
        self.files('movie.rar', 'movie.r00', 'movie.s00')
        with self.assertRaises(CompzError):
            volumes.resolve(self.root / 'movie.s00')

    def test_classic_and_extended_numbering_not_mixed(self):
        self.files('movie.rar', 'movie.r000', 'movie.s00')
        with self.assertRaises(CompzError):
            volumes.resolve(self.root / 'movie.rar')

    def test_unrelated_case_collisions_do_not_break_resolution(self):
        self.files('note', 'NOTE', 'movie.rar')
        self.assertEqual(self.names(self.root / 'movie.rar'), ['movie.rar'])

    def test_related_case_collisions_are_ambiguous(self):
        self.files('movie.rar', 'MOVIE.RAR')
        with self.assertRaises(CompzError):
            volumes.resolve(self.root / 'movie.rar')

    def test_split_zip_needs_final_directory(self):
        self.files('movie.z01', 'movie.z02')
        with self.assertRaises(CompzError):
            volumes.resolve(self.root / 'movie.z02')
        self.files('movie.zip')
        self.assertEqual(self.names(self.root / 'movie.z02'), ['movie.z01', 'movie.z02', 'movie.zip'])

    def test_generic_split_concatenation(self):
        self.files('movie.tar.gz.001', 'movie.tar.gz.002')
        group = volumes.resolve(self.root / 'movie.tar.gz.002')
        self.assertTrue(group.concatenate)
        self.assertEqual(group.name, 'movie')

    def test_unknown_split_not_an_archive(self):
        self.assertFalse(volumes.recognizable('data.txt.001'))
        self.assertTrue(volumes.recognizable('data.tar.xz.001'))

    def test_volume_symlink_and_hardlink_rejected(self):
        self.files('movie.rar')
        (self.root / 'movie.r00').symlink_to(self.root / 'movie.rar')
        with self.assertRaises(CompzError):
            volumes.resolve(self.root / 'movie.rar')
        (self.root / 'movie.r00').unlink()
        os.link(self.root / 'movie.rar', self.root / 'movie.r00')
        with self.assertRaises(CompzError):
            volumes.resolve(self.root / 'movie.rar')

    def test_fifo_first_volume_is_nonblocking(self):
        os.mkfifo(self.root / 'movie.r001')
        self.files('movie.r002')
        with self.assertRaises(CompzError):
            volumes.resolve(self.root / 'movie.r002')

    def test_rar5_aliases_normalize_nonstandard_numbering(self):
        self.files('movie.rar', 'movie.r001', 'movie.r002', data=b'Rar!\x1a\x07\x01\x00fixture')
        group = volumes.resolve(self.root / 'movie.r002')
        source = volumes.rar_aliases(group, self.root / 'aliases')
        self.assertEqual(source.name, 'volume.part00001.rar')
        for index, member in enumerate(group.members, 1):
            self.assertEqual((source.parent / f'volume.part{index:05d}.rar').resolve(), member)

    def test_rar4_aliases_follow_header_flags(self):
        for flags, expected in ((1, 'volume.rar'), (0x11, 'volume.part00001.rar')):
            with self.subTest(flags=flags):
                header = b'Rar!\x1a\x07\x00\0\0\x73' + flags.to_bytes(2, 'little') + b'\r\0'
                self.files('movie.rar', 'movie.r001', data=header)
                source = volumes.rar_aliases(volumes.resolve(self.root / 'movie.rar'), self.root / str(flags))
                self.assertEqual(source.name, expected)
                if flags == 1:
                    self.assertTrue((source.parent / 'volume.r00').is_symlink())


class PipelineTests(Temporary):
    def setUp(self):
        super().setUp()
        self.driver = self.root / 'pipeline.pl'
        # Exercise the actual core module; do not fake a live AppArmor label.
        self.driver.write_text("use strict; use warnings; use lib " + repr(str(PERL)) + ";\n"
                               "use JSON::PP; use CompzArchives::Pipeline;\n"
                               "%ENV=(PATH=>'/usr/bin:/bin', LC_ALL=>'C.UTF-8');\n"
                               "local $/; my $p=decode_json(<STDIN>);\n"
                               "exit CompzArchives::Pipeline->new(%$p)->run();\n")

    def run_pipeline(self, commands, **kwargs):
        return subprocess.run(['/usr/bin/perl', '-T', str(self.driver)],
                              input=json.dumps({'commands': commands}).encode(),
                              capture_output=True, timeout=15, **kwargs)

    def test_three_stage_stream(self):
        size = 16 * 1024**2
        result = self.run_pipeline([
            ['/usr/bin/python3', '-I', '-c', f'import sys;sys.stdout.buffer.write(b"x"*{size})'],
            ['/usr/bin/gzip', '-c', '-1'], ['/usr/bin/gzip', '-dc']])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, b'x' * size)

    def test_metacharacters_are_literal_arguments(self):
        value = '"; touch /tmp/compz-must-not-run; $(false) `false`\n'
        result = self.run_pipeline([['/usr/bin/python3', '-I', '-c',
                                     'import sys;sys.stdout.write(sys.argv[1])', value]])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.decode(), value)

    def test_unmanaged_executable_rejected(self):
        result = self.run_pipeline([['/bin/sh', '-c', 'true']])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'unmanaged', result.stderr)

    def test_first_stage_failure_is_not_hidden(self):
        result = self.run_pipeline([['/usr/bin/python3', '-I', '-c', 'raise SystemExit(23)'],
                                    ['/usr/bin/gzip', '-c']])
        self.assertNotEqual(result.returncode, 0)

    def test_middle_failure_terminates_and_reaps_stubborn_producer(self):
        pidfile = self.root / 'child.pid'
        producer = ('import os,signal,time;from pathlib import Path;'
                    'signal.signal(signal.SIGTERM,signal.SIG_IGN);'
                    f'Path({str(pidfile)!r}).write_text(str(os.getpid()));time.sleep(60)')
        result = self.run_pipeline([['/usr/bin/python3', '-I', '-c', producer],
                                   ['/usr/bin/python3', '-I', '-c', 'import time;time.sleep(.2);raise SystemExit(4)'],
                                   ['/usr/bin/gzip', '-c']])
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(pidfile.exists())
        with self.assertRaises(ProcessLookupError):
            os.kill(int(pidfile.read_text()), 0)

    def test_sigterm_reaps_all_children(self):
        pidfile = self.root / 'child.pid'
        command = ['/usr/bin/python3', '-I', '-c',
                   'import os,time;from pathlib import Path;'
                   f'Path({str(pidfile)!r}).write_text(str(os.getpid()));time.sleep(60)']
        process = subprocess.Popen(['/usr/bin/perl', '-T', str(self.driver)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            process.stdin.write(json.dumps({'commands': [command]}).encode())
            process.stdin.close()
            process.stdin = None
            deadline = time.monotonic() + 5
            while not pidfile.exists() and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertTrue(pidfile.exists())
            process.terminate()
            process.communicate(timeout=5)
            self.assertEqual(process.returncode, 143)
            with self.assertRaises(ProcessLookupError):
                os.kill(int(pidfile.read_text()), 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()


class WorkerTests(PipelineTests):
    # Pipeline tests also run through this fixture class; no production labels
    # are overridden and no root-running decoder is represented as a sandbox.
    def setUp(self):
        super().setUp()
        self.work = self.root / 'work'
        self.work.mkdir()
        self.inputs = self.root / 'inputs'
        self.inputs.mkdir()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(worker, 'WORK', self.work))
        self.stack.enter_context(mock.patch.object(worker, 'PIPELINE', str(self.driver)))
        self.producer = self.root / 'producer.py'
        self.producer.write_text(
            'import sys;from pathlib import Path\n'
            f'sys.path.insert(0,{str(MODULES)!r})\n'
            'from labwc_compz.safeio import produce_tar,Budget\n'
            f'produce_tar(Path({str(self.inputs)!r}),["tree"],sys.stdout.buffer,Budget(64*1024**2,10000))\n')
        self.stack.enter_context(mock.patch.object(worker, 'WORKER', str(self.producer)))

    def test_plan_validation_rejects_extra_and_bad_limits(self):
        target = self.root / 'plan.json'
        for changes in ({'unknown': 1}, {'max_files': True}, {'selected': ['../escape']},
                        {'selected': ['one', 'one']}, {'output': '/absolute'}, {'threads': 0}):
            target.write_text(json.dumps(plan(**changes)))
            with self.subTest(changes=changes), self.assertRaises(CompzError):
                worker.read_plan(target)
        target.write_text(json.dumps(plan()))
        self.assertEqual(worker.read_plan(target), plan())

    def test_unavailable_rar_writer_is_not_offered_or_accepted(self):
        original = os.access
        with mock.patch.object(formats.os, 'access', side_effect=lambda path, mode: path != '/usr/bin/rar' and original(path, mode)):
            self.assertNotIn('rar', [codec.key for codec in formats.available_codecs()])
            self.assertNotIn('/usr/bin/rar', formats.missing())
            target = self.root / 'rar-plan.json'
            target.write_text(json.dumps(plan(action='compress', codec='rar')))
            with self.assertRaises(CompzError):
                worker.read_plan(target)
            with self.assertRaises(CompzError):
                formats.compression(formats.BY_KEY['rar'], 1, 1, 512, self.work / 'rar')

    def test_nested_gzip_reaches_final_payload(self):
        (self.inputs / 'outer.tar').write_bytes(tar_bytes([('inner.gz', gzip.compress(b'final contents'))]))
        target = self.work / 'output'
        worker.Extractor(plan(nested=True), b'').unpack(volumes.resolve(self.inputs / 'outer.tar'), target)
        self.assertEqual((target / 'inner/inner').read_bytes(), b'final contents')
        self.assertTrue((target / 'inner.gz').is_file())

    def test_split_gzip_from_second_volume(self):
        data = gzip.compress(b'joined final data')
        (self.inputs / 'data.gz.001').write_bytes(data[:12])
        (self.inputs / 'data.gz.002').write_bytes(data[12:])
        target = self.work / 'output'
        worker.Extractor(plan(), b'').unpack(volumes.resolve(self.inputs / 'data.gz.002'), target)
        self.assertEqual((target / 'data').read_bytes(), b'joined final data')

    def test_corrupt_gzip_fails(self):
        (self.inputs / 'bad.gz').write_bytes(b'not gzip')
        with self.assertRaises(CompzError):
            worker.Extractor(plan(), b'').unpack(volumes.resolve(self.inputs / 'bad.gz'), self.work / 'output')

    def test_tar_extension_is_not_trusted(self):
        (self.inputs / 'bad.tar.gz').write_bytes(gzip.compress(b'not tar'))
        with self.assertRaises(CompzError):
            worker.Extractor(plan(), b'').unpack(volumes.resolve(self.inputs / 'bad.tar.gz'), self.work / 'output')

    def test_nested_depth_bound(self):
        (self.inputs / 'outer.tar').write_bytes(tar_bytes([('inner.gz', gzip.compress(b'end'))]))
        with self.assertRaises(CompzError):
            worker.Extractor(plan(nested=True, depth=0), b'').unpack(
                volumes.resolve(self.inputs / 'outer.tar'), self.work / 'output')

    def test_nested_destination_never_merged(self):
        data = tar_bytes([('inner.gz', gzip.compress(b'end')), ('inner/already', b'keep')])
        (self.inputs / 'outer.tar').write_bytes(data)
        with self.assertRaises(CompzError):
            worker.Extractor(plan(nested=True), b'').unpack(
                volumes.resolve(self.inputs / 'outer.tar'), self.work / 'output')

    @unittest.skipUnless(shutil.which('gpg') and shutil.which('gpgconf'), 'GnuPG is not installed')
    def test_gpg_envelope_round_trip_and_wrong_password(self):
        source = self.work / 'original'
        source.write_bytes(b'confidential archive contents' * 500)
        cipher, decoded = self.work / 'encrypted.gpg', self.work / 'decoded'
        worker.gpg(source, cipher, b'fixture passphrase', True)
        self.assertNotIn(b'confidential archive', cipher.read_bytes())
        worker.gpg(cipher, decoded, b'fixture passphrase', False)
        self.assertEqual(decoded.read_bytes(), source.read_bytes())
        with self.assertRaises(CompzError):
            worker.gpg(cipher, self.work / 'wrong', b'wrong passphrase', False)

    def test_rar_contract_uses_private_volume_aliases(self):
        for name in ('movie.rar', 'movie.r001'):
            (self.inputs / name).write_bytes(b'Rar!\x1a\x07\x01\x00fixture')
        def codec(command, **kwargs):
            source = Path(command[-2])
            self.assertEqual(command[0], '/usr/bin/unrar-nonfree')
            self.assertEqual(source.name, 'volume.part00001.rar')
            self.assertTrue(source.is_symlink())
            self.assertTrue((source.parent / 'volume.part00002.rar').is_symlink())
            (Path(command[-1]) / 'result').write_bytes(b'fixture output')
        with mock.patch.object(worker, 'run', side_effect=codec):
            worker.Extractor(plan(), b'').unpack(volumes.resolve(self.inputs / 'movie.r001'), self.work / 'output')
        self.assertEqual((self.work / 'output/result').read_bytes(), b'fixture output')

    def test_native_password_is_not_in_argv(self):
        (self.inputs / 'archive.zip').write_bytes(b'fixture')
        with mock.patch.object(worker, 'run') as run:
            worker.Extractor(plan(), b'secret').unpack(volumes.resolve(self.inputs / 'archive.zip'), self.work / 'output')
        args, kwargs = run.call_args
        self.assertIn('-p', args[0])
        self.assertNotIn('secret', ' '.join(args[0]))
        self.assertEqual(kwargs['secret'], b'secret\n')

    def codec_round_trip(self, key):
        codec = formats.BY_KEY[key]
        required = [codec.binary]
        if key in ('zpaq', 'zpaqfranz'):
            required.append('/usr/bin/zpaqfranz')
        if key == 'rar':
            required.append('/usr/bin/unrar-nonfree')
        if any(not os.access(path, os.X_OK) for path in required):
            self.skipTest('native codec executable unavailable: ' + ', '.join(required))
        (self.inputs / 'tree').mkdir()
        expected = {'a': b'hello' * 4096, 'name\nwith\tcontrols': b'arbitrary filenames'}
        for name, data in expected.items():
            (self.inputs / 'tree' / name).write_bytes(data)
        archive = worker.compress(plan(action='compress', selected=['tree'], codec=key), b'')
        output = self.work / 'output'
        worker.Extractor(plan(), b'').unpack(volumes.resolve(archive), output)
        self.assertEqual({p.name: p.read_bytes() for p in (output / 'tree').iterdir()}, expected)


for _codec in formats.CODECS:
    def _test(self, key=_codec.key):
        self.codec_round_trip(key)
    setattr(WorkerTests, 'test_codec_round_trip_' + _codec.key, _test)


class IsolationTests(Temporary):
    def test_required_service_lifecycle_and_limits(self):
        command = isolation.service_command('compz-test.service', Path('/tmp/in$%'), Path('/tmp/work'),
                                            Path('/run/user/1000/plan'), plan())
        for option in ('--wait', '--pipe', '--collect', '--expand-environment=no',
                       '--property=ExitType=cgroup', '--property=KillMode=control-group',
                       '--property=NoNewPrivileges=yes', '--property=MemorySwapMax=0'):
            self.assertIn(option, command)
        self.assertNotIn('/bin/sh', command)
        self.assertFalse(any(item.startswith('--property=AppArmorProfile=') for item in command))
        self.assertEqual(command[command.index('--') + 1:command.index('--') + 9],
                         ['/usr/bin/aa-exec', '-p', 'compz-worker', '--',
                          '/usr/bin/python3', '-I', '-B', '/usr/local/libexec/compz-sandbox'])
        self.assertIn('/tmp/in$%', command)

    def test_sandbox_exports_only_selected_descriptors(self):
        command = isolation.bwrap_command([('chosen', 8)], 9, 10, plan())
        for option in ('--unshare-user', '--unshare-all', '--disable-userns', '--assert-userns-disabled',
                       '--die-with-parent', '--new-session', '--clearenv'):
            self.assertIn(option, command)
        self.assertIn('/input/chosen', command)
        self.assertNotIn('/home', command)
        self.assertNotIn('/run/user', command)
        self.assertNotIn('--share-net', command)
        self.assertEqual(command[command.index('--cap-drop') + 1], 'ALL')

    def test_root_frontend_refused(self):
        with mock.patch.object(os, 'geteuid', return_value=0), self.assertRaises(CompzError):
            isolation.user_environment()

    def test_collected_service_counts_as_stopped(self):
        with mock.patch.object(subprocess, 'run', side_effect=[
                subprocess.CompletedProcess([], 5),
                subprocess.CompletedProcess([], 4, 'LoadState=not-found\nActiveState=inactive\nControlGroup=\n')]):
            isolation.stop('compz-test.service', {})

    def test_running_or_unreachable_service_never_cleaned(self):
        for state in ('LoadState=loaded\nActiveState=active\nControlGroup=/bad\n', '',
                      'LoadState=loaded\nActiveState=inactive\n'):
            with self.subTest(state=state), mock.patch.object(subprocess, 'run', side_effect=[
                    subprocess.CompletedProcess([], 0), subprocess.CompletedProcess([], 0, state)]):
                with self.assertRaises(CompzError):
                    isolation.stop('compz-test.service', {})

    def test_occupancy_never_follows_directory_symlink(self):
        (self.root / 'escape').symlink_to('/usr')
        with mock.patch.object(shutil, 'disk_usage', return_value=shutil._ntuple_diskusage(10**9, 0, 10**9)):
            isolation.occupancy(self.root, 10, 5)

    def test_parent_disconnect_exits_worker(self):
        code = ('import sys,time;'
                f'sys.path.insert(0,{str(MODULES)!r});'
                'from labwc_compz.worker import watch_parent;'
                'watch_parent();print("ready",flush=True);time.sleep(30)')
        process = subprocess.Popen([sys.executable, '-I', '-B', '-c', code],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            self.assertEqual(process.stdout.readline(), b'ready\n')
            process.stdin.close()
            process.stdin = None
            process.communicate(timeout=3)
            self.assertEqual(process.returncode, 125)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    def test_completed_lifeline_stops_without_buffered_io_deadlock(self):
        code = ('import sys;'
                f'sys.path.insert(0,{str(MODULES)!r});'
                'from labwc_compz.worker import watch_parent;'
                'event,thread=watch_parent();event.set();thread.join();print("complete")')
        process = subprocess.Popen([sys.executable, '-I', '-B', '-c', code],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            process.wait(timeout=3)  # Keep its parent pipe open throughout.
            process.stdin.close()
            process.stdin = None
            output, errors = process.communicate()
            self.assertEqual(process.returncode, 0, errors)
            self.assertEqual(output, b'complete\n')
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    def test_maximum_profiles_are_real_codec_options(self):
        kanzi = formats.compression(formats.BY_KEY['kanzi'], 2, 8, 4096, Path('/work/test'))
        self.assertIn('--level=9', kanzi)
        self.assertIn('--jobs=1', kanzi)
        flz = formats.compression(formats.BY_KEY['flzma2'], 2, 8, 4096, Path('/work/test'))
        self.assertIn('-m0=FLZMA2', flz)
        with self.assertRaises(CompzError):
            formats.compression(formats.BY_KEY['bzip3'], 2, 8, 512, Path('/work/test'))

    def test_installation_and_apparmor_wiring(self):
        packages = (FORKY / 'classes/class-select/role/desktop.cfg').read_text().split()
        for package in ('zpaq', 'zpaqfranz', 'lrzip', 'gzip', 'kanzi', 'rzip', 'rar',
                        'unrar', '7zip-rar', 'zip', 'zstd', 'xz-utils', 'bzip3'):
            self.assertIn(package, packages)
        self.assertIn('microsoft-edge-stable|rar)', (FORKY / 'scripts/preseed/answers.sh').read_text())
        self.assertIn('desktop_stage_compz', (FORKY / 'scripts/desktop/components/target-assets.sh').read_text())
        self.assertIn('components/compz.sh', (FORKY / 'scripts/desktop/components.sh').read_text())
        self.assertIn('compz', (FORKY / 'scripts/late/security.sh').read_text())
        profile = (TARGET / 'etc/apparmor.d/compz').read_text()
        self.assertIn('profile compz-worker ', profile)
        self.assertIn('unrar-nonfree', profile)
        self.assertNotIn('network inet', profile)
        for name in ('compz-worker', 'compz-sandbox', 'compz-pipeline'):
            self.assertTrue((TARGET / 'usr/local/libexec' / name).is_file())


if __name__ == '__main__':
    unittest.main()
