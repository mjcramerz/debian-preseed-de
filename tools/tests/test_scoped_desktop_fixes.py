#!/usr/bin/python3
"""Offline tests for generated overrides, panel supervision and Whisper stops."""

# Refuse host execution before importing runtime helpers or creating fixtures.
from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[2] / 'tools'))
# Copied checker/GUI fixtures still use the verified private checkout gate.
_isolation_sys.path.insert(0, '/workspace/repository/tools')
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / 'd-i/forky/hooks/target'

def load(name):
    loader = importlib.machinery.SourceFileLoader(name.replace('-', '_'), str(TARGET / 'usr/local/libexec' / name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module

class DesktopOverrideTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.vendor = self.root / 'vendor'; self.vendor.mkdir()
        self.local = self.root / 'local'; self.local.mkdir()
        self.state = self.root / 'state'; self.state.mkdir()
        self.hook = load('labwc-wrap-desktop-files')
        self.patches = mock.patch.multiple(self.hook, APPLICATION_DIRS=(self.vendor,), OUTPUT_DIR=self.local,
            STATE_DIR=self.state, MANIFEST=self.state/'overrides.json', PENDING=self.state/'pending.json',
            DATABASE_DIRTY=self.state/'database-dirty', SOURCE_STATE=self.state/'source-state.json')
        self.patches.start()
        self.trust = mock.patch.object(self.hook, 'trusted_directory'); self.trust.start()
        self.owner = mock.patch.object(self.hook, 'package_for', return_value='test-package'); self.owner.start()
        self.electron = mock.patch.object(self.hook, 'is_electron', return_value=False); self.electron.start()
        # Ownership tests isolate external tools; the menu integration suite
        # separately runs desktop-file-validate when installed.
        self.validator = mock.patch.object(self.hook, 'validate_desktop'); self.validator.start()
        self.defaults = {'electron':'/usr/local/bin/labwc-electron-app intel','wayland':'/usr/local/bin/labwc-wayland-app intel'}
        self.text = '[Desktop Entry]\nType=Application\nName=Test\nExec=/usr/bin/example "a b" %U\nDBusActivatable=true\n\n[Desktop Action New]\nExec=/usr/bin/example --new %f\n'
        self.source = self.vendor / 'example.desktop'; self.source.write_text(self.text)
    def tearDown(self):
        self.validator.stop(); self.electron.stop(); self.owner.stop(); self.trust.stop(); self.patches.stop(); self.temp.cleanup()
    def test_pristine_vendor_idempotent_generated_override(self):
        before = self.source.stat()
        self.assertTrue(self.hook.generate_overrides(self.defaults))
        after = self.source.stat()
        self.assertEqual((before.st_ino,before.st_mtime_ns,before.st_mode), (after.st_ino,after.st_mtime_ns,after.st_mode))
        self.assertEqual(self.source.read_text(), self.text)
        output = self.local / self.source.name
        self.assertIn('intel -- /usr/bin/example "a b" %U', output.read_text())
        self.assertIn('DBusActivatable=false', output.read_text())
        self.assertIn('intel -- /usr/bin/example --new %f', output.read_text())
        self.assertFalse(self.hook.generate_overrides(self.defaults))
    def test_administrator_override_and_edits_preserved(self):
        output = self.local / self.source.name; output.write_text('administrator file\n')
        self.hook.generate_overrides(self.defaults)
        self.assertEqual(output.read_text(), 'administrator file\n')
        output.unlink(); self.hook.generate_overrides(self.defaults)
        output.write_text('edited administrator file\n'); self.source.unlink()
        self.hook.generate_overrides(self.defaults)
        self.assertEqual(output.read_text(), 'edited administrator file\n')
    def test_stale_owned_override_removed(self):
        self.hook.generate_overrides(self.defaults); self.source.unlink()
        self.hook.generate_overrides(self.defaults)
        self.assertFalse((self.local / self.source.name).exists())
    def test_crash_after_output_before_manifest_is_recoverable(self):
        original = self.hook.write_atomic
        def interrupted(path, *args):
            if path == self.hook.MANIFEST:
                raise OSError('injected interruption')
            return original(path, *args)
        with mock.patch.object(self.hook, 'write_atomic', side_effect=interrupted):
            with self.assertRaises(OSError): self.hook.generate_overrides(self.defaults)
        self.assertTrue(self.hook.PENDING.exists())
        self.hook.generate_overrides(self.defaults)
        self.assertFalse(self.hook.PENDING.exists())
        self.assertIn(self.source.name,json.loads(self.hook.MANIFEST.read_text()))
        self.source.unlink(); self.hook.generate_overrides(self.defaults)
        self.assertFalse((self.local/self.source.name).exists())

class PanelTests(unittest.TestCase):
    def setUp(self): self.panel = load('labwc-panel-run')

    def command(self, child):
        code = "import runpy,sys; panel=runpy.run_path(sys.argv[1]); raise SystemExit(panel['supervise']([sys.executable,'-c',sys.argv[2]],set()))"
        return [sys.executable, '-B', '-c', code, str(TARGET / 'usr/local/libexec/labwc-panel-run'), child]

    def fixture_environment(self, home):
        return {'PATH': '/usr/bin:/bin', 'HOME': str(home), 'TMPDIR': str(home),
                'LC_ALL': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1'}

    def test_output_queue_retains_partial_and_blocked_writes(self):
        stream = mock.Mock()
        stream.fileno.return_value = 42
        with mock.patch.object(self.panel.os, 'get_blocking', return_value=True), \
             mock.patch.object(self.panel.os, 'set_blocking') as blocking, \
             mock.patch.object(self.panel.os, 'write', side_effect=[2, BlockingIOError(), 3]):
            output = self.panel.OutputBuffer(stream)
            output.write(b'abcde')
            output.drain()
            self.assertEqual(output.pending, b'cde')
            output.drain()
            self.assertEqual(output.pending, b'cde')
            output.drain()
            self.assertEqual(output.pending, b'')
            output.restore()
        self.assertEqual(blocking.call_args_list, [mock.call(42, False), mock.call(42, True)])

    def test_bulk_output_is_lossless_with_regular_file_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = b'normal message\n' * 50000 + b'partial tail'
            child = "import os; os.write(1,b'normal message\\n'*50000+b'partial tail'); raise SystemExit(17)"
            with (root / 'output').open('wb') as output:
                result = subprocess.run(self.command(child), stdout=output, stderr=subprocess.PIPE,
                                        env=self.fixture_environment(root), timeout=10)
            self.assertEqual(result.returncode, 17, result.stderr)
            self.assertEqual((root / 'output').read_bytes(), expected)

    def test_spawn_failure_restores_output_flags_in_reverse_order(self):
        outputs = [mock.Mock(), mock.Mock()]
        restored = []
        for index, output in enumerate(outputs):
            output.restore.side_effect = lambda index=index: restored.append(index)
        with mock.patch.object(self.panel, 'OutputBuffer', side_effect=outputs), \
             mock.patch.object(self.panel.subprocess, 'Popen', side_effect=FileNotFoundError()), \
             self.assertRaises(FileNotFoundError):
            self.panel.supervise(['/fixture/missing'], set(), signals=())
        self.assertEqual(restored, [1, 0])

    def test_full_output_pipe_cannot_block_termination_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ready = root / 'ready'
            child = ("import os,pathlib,signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
                     f"pathlib.Path({str(ready)!r}).touch(); os.write(1,b'x'*8388608); time.sleep(60)")
            process = subprocess.Popen(self.command(child), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       env=self.fixture_environment(root), start_new_session=True)
            try:
                deadline = time.monotonic() + 5
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue(ready.exists())
                time.sleep(.2)  # Leave stdout unread so both pipe and queue fill.
                started = time.monotonic()
                process.send_signal(signal.SIGTERM)
                process.wait(timeout=9)
                self.assertEqual(process.returncode, 247)  # Child -SIGKILL through SystemExit.
                self.assertLess(time.monotonic() - started, 8)
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=3)
                process.stdout.close()
                process.stderr.close()

    def test_only_exact_repeats_coalesced(self):
        output = io.BytesIO(); c=self.panel.Coalescer({b'Plugged'})
        for line in (b'Plugged\n',b'Plugged\n',b'Plugged\n',b'ERROR actual failure\n',b'Plugged device X\n'):
            c.line(output,line)
        c.flush(final=True)
        self.assertEqual(output.getvalue(), b'Plugged\nERROR actual failure\nPlugged device X\n[labwc-panel-run] repeated 2 times: Plugged\n')
    def test_supervisor_retains_error_and_exit_status(self):
        with tempfile.TemporaryDirectory() as directory:
            runner=Path(directory)/'runner.py'
            runner.write_text("import sys\nsys.path.insert(0,"+repr(str(Path(__file__).parent))+ ")\nfrom test_scoped_desktop_fixes import load\np=load('labwc-panel-run')\nsys.exit(p.supervise([sys.executable, '-c', \"import sys; print('Plugged'); print('Plugged'); print('fatal detail', file=sys.stderr); sys.exit(7)\"], {b'Plugged'}))\n")
            result=subprocess.run([sys.executable,'-B',str(runner)],capture_output=True,timeout=10)
            self.assertEqual(result.returncode,7,result.stderr)
            self.assertIn(b'Plugged\n',result.stdout); self.assertIn(b'repeated 1 times',result.stdout)
            self.assertIn(b'fatal detail',result.stderr)
    def test_reload_is_forwarded(self):
        with tempfile.TemporaryDirectory() as directory:
            directory=Path(directory); ready=directory/'ready'; runner=directory/'runner.py'
            child="import signal,time,pathlib,sys; signal.signal(signal.SIGUSR2,lambda *_: sys.exit(0)); pathlib.Path(sys.argv[1]).touch(); time.sleep(5)"
            runner.write_text("import sys\nsys.path.insert(0,"+repr(str(Path(__file__).parent))+")\nfrom test_scoped_desktop_fixes import load\nsys.exit(load('labwc-panel-run').supervise([sys.executable,'-c',"+repr(child)+","+repr(str(ready))+"], set()))\n")
            with subprocess.Popen([sys.executable,'-B',str(runner)],stdout=subprocess.PIPE,stderr=subprocess.PIPE) as process:
                end=time.monotonic()+5
                while not ready.exists() and time.monotonic()<end: time.sleep(.02)
                self.assertTrue(ready.exists()); process.send_signal(signal.SIGUSR2)
                out,err=process.communicate(timeout=5); self.assertEqual(process.returncode,0,err)

class WhisperSupervisorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(); cls.root=Path(cls.temp.name)
        source=(TARGET/'usr/local/lib/perl5/site_perl/whisper/WhisperMode/Audio.pm').read_text()
        # Exercise the production fork/wait/signal and WAV-validation methods
        # verbatim; full module integration additionally requires installed Moo.
        methods=source[source.index('sub _completed_wav {'):source.rindex('\n1;')]
        cls.runner=cls.root/'supervisor.pl'
        cls.runner.write_text('''use strict; use warnings;
package WhisperMode::Systemd;
sub _detail { return 'worker status ' . $_[0]; }
package WhisperMode::Audio;
use POSIX qw(_exit WNOHANG);
use Errno qw(EINTR);
use Fcntl qw(O_RDONLY O_NOFOLLOW O_NONBLOCK);
use Time::HiRes qw(sleep clock_gettime CLOCK_MONOTONIC);
sub _fatal { die $_[0] . "\\n"; }
'''+methods+'''\npackage main;
my ($destination, @command) = @ARGV;
my $audio=bless {}, 'WhisperMode::Audio';
$audio->_supervise_recording($destination, @command);
exit 0;
''')
        cls.worker=cls.root/'worker.py'
        cls.worker.write_text('''import pathlib, signal, sys, time, wave
path,mode=sys.argv[1:]
def finish(*_):
    if mode != 'invalid':
        with wave.open(path,'wb') as wav:
            wav.setparams((1,2,16000,0,'NONE','not compressed'))
            wav.writeframes(b'\\0\\0'*1600)
    else:
        pathlib.Path(path).write_bytes(b'invalid WAV')
    sys.exit(1)
signal.signal(signal.SIGINT,finish)
pathlib.Path(path+'.ready').touch()
if mode=='spontaneous': finish()
while True: time.sleep(.05)
''')
    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()
    def scenario(self, mode, stop=True):
        with tempfile.TemporaryDirectory(dir=self.root) as directory:
            wav=Path(directory)/'recording.wav'
            command=['/usr/bin/perl',str(self.runner),str(wav),sys.executable,str(self.worker),str(wav),mode]
            with subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE) as process:
                end=time.monotonic()+5
                while not Path(str(wav)+'.ready').exists() and time.monotonic()<end: time.sleep(.02)
                self.assertTrue(Path(str(wav)+'.ready').exists())
                if stop: process.send_signal(signal.SIGINT)
                out,err=process.communicate(timeout=20)
                return process.returncode,err
    def test_intentional_stop_status_one_with_complete_wav_is_success(self):
        status,err=self.scenario('complete');self.assertEqual(status,0,err)
    def test_spontaneous_status_one_remains_failure(self):
        status,_=self.scenario('spontaneous',stop=False);self.assertNotEqual(status,0)
    def test_intentional_stop_with_invalid_wav_remains_failure(self):
        status,_=self.scenario('invalid');self.assertNotEqual(status,0)
    def test_fifteen_second_limit_is_graceful(self):
        status,err=self.scenario('complete',stop=False);self.assertEqual(status,0,err)

if __name__=='__main__': unittest.main(verbosity=2)
