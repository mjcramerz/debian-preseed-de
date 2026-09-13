"""Scoped process/renderer fixtures, without compositor, root writes or builds.

The process harness uses real broker/IPC/policy code but substitutes only the
State constructor (Moo unavailable on some builders), config/runtime location
and the driver executable. This does NOT test real Moo, PyWayland or AppArmor.
"""
from __future__ import annotations
import ast
import json
import re
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET
import test_workspace_broker as source

ROOT, FORKY, TARGET, PERL = source.ROOT, source.FORKY, source.TARGET, source.PERL
wire = source.wire
FIXTURES = FORKY / 'tests/fixtures/workspace-broker'


def wait_for(predicate, timeout=4):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate(): return
        time.sleep(.02)
    raise AssertionError('fixture deadline')


def receive(sock):
    sock.settimeout(3)
    header = b''
    while len(header) < 4:
        data = sock.recv(4-len(header))
        if not data: raise EOFError('fixture socket closed')
        header += data
    length = int.from_bytes(header, 'big')
    if not 0 < length <= 262144: raise AssertionError('frame bound')
    data = b''
    while len(data) < length:
        part = sock.recv(length-len(data))
        if not part: raise EOFError('fixture short frame')
        data += part
    return wire.decode(data)


class RenderIntegrationTests(unittest.TestCase):
    def test_real_template_renderers_all_workspace_counts(self):
        for workspaces, style, slots in ((1,'thumbnail',4),(3,'thumbnail',24),(4,'classic',24),(5,'classic',64),(12,'thumbnail',64)):
            with self.subTest(workspaces=workspaces,style=style), tempfile.TemporaryDirectory() as tmp:
                result = subprocess.run(['/bin/sh',str(FIXTURES/'render.sh'),str(ROOT),tmp,str(workspaces),style,str(slots)],capture_output=True,text=True,timeout=15)
                self.assertEqual(result.returncode,0,result.stderr)
                cfg = Path(tmp)/'etc/skel-desktop/.config'
                rc = ET.parse(cfg/'labwc/rc.xml').getroot()
                switch = rc.findall('windowSwitcher')
                self.assertEqual(len(switch),1)
                self.assertEqual(switch[0].get('order'),'focus')
                self.assertEqual(switch[0].find('osd').get('style'),style)
                self.assertEqual(switch[0].find('osd').get('output'),'focused')
                self.assertEqual(len(rc.findall('desktops/names/name')),workspaces)
                for key in ('A-Tab','A-S-Tab'):
                    action = rc.find(f'keyboard/keybind[@key="{key}"]/action')
                    self.assertEqual(action.get('workspace'),'current')
                    self.assertEqual(action.get('output'),'all')
                bars = json.loads((cfg/'waybar/config').read_text())
                self.assertEqual(len(bars),2)
                for bar in bars:
                    self.assertIn('ext/workspaces',bar)
                    self.assertIn('group/apps',bar)
                    self.assertNotIn('wlr/taskbar',bar)
                    self.assertEqual(len(bar['group/workspace-taskbar']['modules']),slots+1)
                for relative in ('waybar/config','waybar/style.css','labwc/rc.xml'):
                    self.assertNotIn('__INSTALLER_', (cfg/relative).read_text())
    def test_private_asset_inventory_is_staged_and_verified(self):
        library = TARGET / 'usr/local/lib/labwc-workspace-broker'
        assets = {p.relative_to(TARGET).as_posix() for p in library.rglob('*') if p.is_file()}
        self.assertEqual(len(assets), 15)
        components = (FORKY / 'scripts/desktop/components.sh').read_text()
        stage = components.split('desktop_stage_workspace_broker_assets() {', 1)[1].split('desktop_stage_labwc_user_session_assets()', 1)[0]
        verify = (FORKY / 'scripts/desktop/verify.sh').read_text().split('desktop_verify_workspace_broker() {', 1)[1]
        for asset in sorted(assets):
            self.assertIn(asset, stage)
            self.assertIn('/' + asset, verify)
        for entry in ('usr/local/libexec/labwc-workspace-broker', 'usr/local/libexec/labwc-workspace-wayland-adapter', 'usr/local/bin/labwc-workspace-broker-client'):
            self.assertTrue((TARGET / entry).stat().st_mode & 0o111)
            self.assertIn(entry, stage)
            self.assertIn('/' + entry, verify)

    def test_installed_target_configuration_verifier_on_rendered_fixture(self):
        # Execute the exact configuration verifier with only its filesystem
        # root relocated. Package-version checks are covered separately by
        # the real target; no fake package availability is reported here.
        verify = (FORKY / 'scripts/desktop/verify.sh').read_text()
        marker = 'import json\nfrom pathlib import Path\nimport subprocess\nimport xml.etree.ElementTree as ET\n'
        code = marker + verify.split(marker, 1)[1].split("\n'", 1)[0]
        ast.parse(code)
        with tempfile.TemporaryDirectory() as tmp:
            rendered = subprocess.run(['/bin/sh', str(FIXTURES / 'render.sh'), str(ROOT), tmp, '12', 'classic', '64'], capture_output=True, text=True, timeout=15)
            self.assertEqual(rendered.returncode, 0, rendered.stderr)
            start = code.index('for package, minimum in ')
            end = code.index('root = Path(', start)
            code = code[:start] + code[end:]
            code = code.replace('Path("/etc/skel-desktop/.config")', 'Path(' + repr(str(Path(tmp) / 'etc/skel-desktop/.config')) + ')')
            result = subprocess.run([sys.executable, '-I', '-B', '-c', code], capture_output=True, text=True, timeout=3)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('native=current grouped=true', result.stdout)

    def test_new_policy_enums_reject_injection(self):
        # Extract this exact contiguous production validator section; unrelated
        # desktop hardware/account resolution is not mocked into acceptance.
        text=(FORKY/'scripts/desktop/detect.sh').read_text()
        start=text.index('  case "${LABWC_WINDOW_SWITCHER_STYLE:-thumbnail}"')
        end=text.index('  desktop_validate_uint_range LABWC_QBITTORRENT_PORT',start)
        checks=text[start:end]
        for key, value in (('STYLE','broken'),('ORDER','focus" />'),('PREVIEW','true'),('OUTLINES','yes; id'),('UNSHADE','YES'),('OSD_OUTPUT','HDMI-A-1'),('CYCLE_OUTPUT','other')):
            env=dict(os.environ,**{'LABWC_WINDOW_SWITCHER_'+key:value})
            code='. "$1"; installer_fatal() { exit 17; }; '+checks
            result=subprocess.run(['/bin/sh','-c',code,'test',str(FORKY/'scripts/desktop/detect.sh')],env=env,capture_output=True,timeout=3)
            self.assertEqual(result.returncode,17,key)


class BrokerProcessTests(unittest.TestCase):
    def fixture(self, root):
        package=root/'lib/Labwc/WorkspaceBroker'; package.mkdir(parents=True)
        production=PERL/'Labwc/WorkspaceBroker'
        text=(production/'Broker.pm').read_text().replace('/usr/local/libexec/labwc-workspace-wayland-adapter',str(root/'adapter.py'))
        (package/'Broker.pm').write_text(text)
        # Only constructor/accessor facade is replaced. All methods call the
        # same production reducer, as the actual Moo class does.
        state=(production/'State.pm').read_text()
        begin=state.index('use Moo;'); end=state.index('# Explicit entry points')
        state=state[:begin]+'''use Labwc::WorkspaceBroker::Policy ();
sub new { my ($class, %arg)=@_; bless {config=>$arg{config}, model=>Labwc::WorkspaceBroker::Policy::new_model($arg{config}{group_slots})}, $class; }
sub config { $_[0]{config} }
sub _model { $_[0]{model} }
'''+state[end:]
        (package/'State.pm').write_text(state)
        (root/'run.pl').write_text('''use strict; use warnings;
use Labwc::WorkspaceBroker::Broker;
no warnings 'redefine';
*Labwc::WorkspaceBroker::Broker::runtime_dir = sub { q{'''+str(root)+'''} };
*Labwc::WorkspaceBroker::Config::load = sub { +{group_slots=>4,picker_lines=>12,picker_width=>64,tooltip_windows=>8} };
$ENV{WAYLAND_DISPLAY}='wayland-test'; delete $ENV{NOTIFY_SOCKET};
exit Labwc::WorkspaceBroker::Broker::run();
''')
        (root/'adapter.py').write_text('''import json,os,socket,struct,time,select
from pathlib import Path
root=Path('''+repr(str(root))+''')
(root/'driver-pid').write_text(str(os.getpid()))
time.sleep(.15)
s=socket.socket(socket.AF_UNIX); s.connect(str(root/'adapter.sock')); seq=0
instance='a'*32
def send(kind,**fields):
 global seq
 seq+=1; data=json.dumps(dict(v=1,instance=instance,seq=seq,kind=kind,**fields)).encode()
 s.sendall(struct.pack('!I',len(data))+data)
send('hello',pid=os.getpid(),capabilities=['ext-workspace-v1','foreign-toplevel-v1','wl-output-name','sync-fence'])
send('outputs',outputs=[dict(id=1,name='eDP-1')])
send('workspaces',workspaces=[dict(id=2,name='1',stable_id='ws1',state=1)],groups=[dict(id=3,outputs=[1],workspaces=[2])])
send('new',id=4)
send('task',id=4,revision=1,title='fixture',app_id='foot',state=4,observed_state=1,outputs=[1])
send('barrier'); send('ready')
buffer=b''; last=time.monotonic()
while not (root/'crash').exists():
 if select.select([s],[],[],.05)[0]:
  data=s.recv(65536)
  if not data: break
  buffer+=data
  while len(buffer)>=4 and len(buffer)>=4+int.from_bytes(buffer[:4],'big'):
   size=int.from_bytes(buffer[:4],'big'); msg=json.loads(buffer[4:4+size]); buffer=buffer[4+size:]
   with (root/'commands').open('a') as f: f.write(json.dumps(msg)+'\\n')
   send('ack',command_id=msg['command_id'],status='marshalled')
 if time.monotonic()-last>1:
  send('heartbeat'); last=time.monotonic()
s.close()
''')
        process=subprocess.Popen(['perl','-T','-I'+str(root/'lib'),'-I'+str(PERL),str(root/'run.pl')],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        return process
    def connect(self, path):
        s=socket.socket(socket.AF_UNIX); s.settimeout(3); s.connect(str(path)); self.addCleanup(s.close); return s
    def test_supervised_child_ready_authentication_actions_and_shutdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); p=self.fixture(root)
            try:
                wait_for(lambda:(root/'adapter.sock').exists() or p.poll() is not None)
                spoof=self.connect(root/'adapter.sock'); spoof.sendall(wire.encode(dict(v=1)))
                try: self.assertEqual(spoof.recv(10),b'')
                except ConnectionResetError: pass
                wait_for(lambda:(root/'control.sock').exists() or p.poll() is not None)
                if p.poll() is not None: self.fail(p.communicate()[1])
                self.assertEqual((root/'control.sock').stat().st_mode & 0o777,0o600)
                watcher=self.connect(root/'control.sock'); watcher.sendall(wire.encode(dict(v=1,kind='watch',slot=1,output='eDP-1')))
                view=receive(watcher)
                self.assertEqual(view['kind'],'frame'); self.assertIsNotNone(view['view'])
                self.assertNotIn('<span',view['frame']['text'])
                bad=self.connect(root/'control.sock'); bad.sendall(b'\0\0\0\0'); self.assertEqual(bad.recv(1),b'')
                time.sleep(.25)
                action=self.connect(root/'control.sock'); action.sendall(wire.encode(dict(v=1,kind='action',slot=1,view=view['view'],mode='primary')))
                self.assertEqual(receive(action)['kind'],'done')
                wait_for(lambda:(root/'commands').exists())
                command=json.loads((root/'commands').read_text().splitlines()[0])
                self.assertEqual((command['op'],command['id']),('set_minimized',4))
                diag=self.connect(root/'control.sock'); diag.sendall(wire.encode(dict(v=1,kind='diagnose')))
                self.assertEqual(receive(diag)['ready'],1)
                child=int((root/'driver-pid').read_text())
                p.terminate(); out,err=p.communicate(timeout=5)
                self.assertEqual(p.returncode,0,err)
                self.assertFalse((root/'control.sock').exists())
                with self.assertRaises(ProcessLookupError): os.kill(child,0)
            finally:
                if p.poll() is None: p.kill(); p.communicate(timeout=5)
    def test_child_failure_tears_down_entire_broker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); p=self.fixture(root)
            try:
                wait_for(lambda:(root/'control.sock').exists() or p.poll() is not None)
                if p.poll() is not None: self.fail(p.communicate()[1])
                (root/'crash').touch()
                out,err=p.communicate(timeout=5)
                self.assertNotEqual(p.returncode,0)
                self.assertFalse((root/'control.sock').exists())
                self.assertRegex(err,'driver exited|channel EOF')
            finally:
                if p.poll() is None: p.kill(); p.communicate(timeout=5)


class PickerProcessTests(unittest.TestCase):
    def run_picker(self, behavior, remaining=2):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); package=root/'lib/Labwc/WorkspaceBroker'; package.mkdir(parents=True)
            text=(PERL/'Labwc/WorkspaceBroker/Picker.pm').read_text().replace('/usr/local/bin/labwc-fuzzel',str(root/'fuzzel'))
            (package/'Picker.pm').write_text(text)
            fake=root/'fuzzel'
            fake.write_text('#!/usr/bin/python3\nimport sys,time,os,signal\nsys.stdin.read()\n'+behavior+'\n')
            fake.chmod(0o755)
            code='$ENV{PATH}=q{/usr/bin:/bin}; delete @ENV{qw(IFS CDPATH ENV BASH_ENV)}; use Labwc::WorkspaceBroker::Picker; use JSON::PP; my $p={rows=>[{label=>q{$(not-a-command)},index=>4},{label=>q{second},index=>7}],count=>2,offset=>0,lines=>12,width=>64,mode=>q{primary}}; print JSON::PP->new->encode(Labwc::WorkspaceBroker::Picker::choose($p,'+str(remaining)+'));'
            result=subprocess.run(['perl','-T','-I'+str(root/'lib'),'-I'+str(PERL),'-e',code],capture_output=True,text=True,timeout=6)
            self.assertEqual(result.returncode,0,result.stderr)
            return json.loads(result.stdout)
    def test_index_cancel_malformed_and_timeout(self):
        self.assertEqual(self.run_picker('print(1)'),{'index':7})
        self.assertIsNone(self.run_picker('sys.exit(1)'))
        self.assertIsNone(self.run_picker('print("second")'))
        self.assertIsNone(self.run_picker('print(999)'))
        self.assertIsNone(self.run_picker('print(0,flush=True); time.sleep(30)',.1))
    def test_crashed_wrapper_cannot_leave_live_descendant(self):
        # The wrapper exits with a valid-looking result while its child holds
        # stdout. A timeout must kill that process group, not return a choice.
        behavior='''pid=os.fork()
if pid==0:
 signal.signal(signal.SIGTERM,signal.SIG_IGN)
 time.sleep(30)
else:
 print(0,flush=True)
 sys.exit(0)'''
        self.assertIsNone(self.run_picker(behavior,.1))


if __name__=='__main__': unittest.main()
