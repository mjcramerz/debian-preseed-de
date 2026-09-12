#!/usr/bin/python3
"""Offline tests for generated overrides, panel supervision and Whisper stops."""
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
            STATE_DIR=self.state, MANIFEST=self.state/'overrides.json', PENDING=self.state/'pending.json')
        self.patches.start()
        self.trust = mock.patch.object(self.hook, 'trusted_directory'); self.trust.start()
        self.owner = mock.patch.object(self.hook, 'package_for', return_value='test-package'); self.owner.start()
        self.electron = mock.patch.object(self.hook, 'is_electron', return_value=False); self.electron.start()
        self.defaults = {'electron':'/usr/local/bin/labwc-electron-app intel','wayland':'/usr/local/bin/labwc-wayland-app intel'}
        self.text = '[Desktop Entry]\nType=Application\nName=Test\nExec=/usr/bin/example "a b" %U\nDBusActivatable=true\n\n[Desktop Action New]\nExec=/usr/bin/example --new %f\n'
        self.source = self.vendor / 'example.desktop'; self.source.write_text(self.text)
    def tearDown(self):
        self.electron.stop(); self.owner.stop(); self.trust.stop(); self.patches.stop(); self.temp.cleanup()
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
