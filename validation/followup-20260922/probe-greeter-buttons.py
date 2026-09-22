"""Run actual greeter methods with fake widgets and child transport; no GUI or power action."""
import ast
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

R = Path(__file__).resolve().parents[2]
T = R/'d-i/forky/hooks/target'
source = (T/'usr/local/bin/labwc-greeter-power').read_text()
tree = ast.parse(source)
cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'GreeterPower')
results = []
for action in ('reboot', 'poweroff'):
    for outcome in ('failed', 'cancelled', 'spawn-failed'):
        glib = SimpleNamespace(SOURCE_REMOVE=False, SOURCE_CONTINUE=True,
            timeout_add=mock.Mock(), timeout_add_seconds=mock.Mock())
        process = mock.Mock(DEVNULL=subprocess.DEVNULL)
        namespace = dict(GLib=glib, subprocess=process,
            ACTION_HELPER='/usr/local/sbin/greetd-power-action')
        exec(compile(ast.Module(body=[cls], type_ignores=[]), '<greeter-methods>', 'exec'), namespace)
        ui = namespace['GreeterPower'].__new__(namespace['GreeterPower'])
        ui.pending_action = ui.action_process = None
        ui.buttons = {a:(mock.Mock(), label) for a,label in (('reboot','Reboot'),('poweroff','Shutdown'))}
        button = ui.buttons[action][0]
        ui.request_action(button, action)
        process.Popen.assert_not_called()
        assert ui.pending_action == action
        if outcome == 'spawn-failed':
            process.Popen.side_effect = OSError('fixture failure')
        ui.request_action(button, action)
        process.Popen.assert_called_once_with(['/usr/local/sbin/greetd-power-action',action],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=None,
            close_fds=True, start_new_session=True)
        if outcome != 'spawn-failed':
            child = ui.action_process
            child.poll.return_value = None
            assert ui.check_action() is True
            for other in ('reboot','poweroff'):
                ui.request_action(ui.buttons[other][0], other)
            assert process.Popen.call_count == 1
            child.poll.return_value = 1 if outcome == 'failed' else 0
            assert ui.check_action() is False
        assert ui.pending_action is None and ui.action_process is None
        for b,label in ui.buttons.values():
            b.set_sensitive.assert_called_with(True)
            b.set_label.assert_called_with(label)
        results.append(dict(action=action,outcome=outcome,passed=True))
packages = (R/'d-i/forky/classes/class-select/role/desktop.cfg').read_text().split()
required = ('gtkgreet','greetd','pkexec','polkitd','python3-gi','gir1.2-gtk-3.0','gir1.2-gtklayershell-0.1')
assert all(p in packages for p in required)
report = dict(success=True,cases=results,selected_runtime_packages=list(required),
    limitations='Actual Python class methods; fake GTK widgets and Popen transport. No real gtkgreet, Python GI, Wayland compositor or power action was executed. Package selection is static, not current repository availability verification.')
(Path(__file__).parent/'greeter-button-probe.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'success':True,'button_cases':len(results),'required_packages':len(required)}))
