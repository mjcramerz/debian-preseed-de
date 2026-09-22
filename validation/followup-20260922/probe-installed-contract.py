"""Execute only the firstboot greeter-check block against disposable staged files."""
import json, shutil, subprocess, tempfile, types
from pathlib import Path
R=Path(__file__).resolve().parents[2]
T=R/'d-i/forky/hooks/target';O=R/'validation/followup-20260922'
source=(R/'d-i/forky/scripts/firstboot/04-validation.sh').read_text()
start=source.index('  # Validate the complete greeter handoff, not just the presence of a menu.')
end=source.index('\n  if grep -q',start)
block=source[start:end]
assets=['usr/local/sbin/greetd-power-action','usr/local/libexec/greetd-power-action-root',
        'usr/local/libexec/labwc-admin-action-root','usr/local/libexec/labwc-admin-action-worker',
        'etc/systemd/system/labwc-admin-action@.service']
results=[]
with tempfile.TemporaryDirectory(prefix='greeter-installed-contract-') as tmp:
    root=Path(tmp)
    for rel in assets:
        path=root/rel;path.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(T/rel,path)
    # Replace file operands only, leaving the exact contents being checked intact.
    for rel in assets:
        block=block.replace(' /'+rel+' 2>/dev/null',' '+str(root/rel)+' 2>/dev/null')
    script='failures=0\nrecord() { printf "%s\\n" "$*"; }\nlog_line() { :; }\n'+block+'\nexit "$failures"\n'
    for scenario in ('intact','wrong-sandbox','wrong-force-handoff'):
        for rel in assets: shutil.copy2(T/rel,root/rel)
        if scenario=='wrong-sandbox':
            p=root/assets[-1];p.write_text(p.read_text().replace('ProtectHome=read-only','ProtectHome=yes'))
        if scenario=='wrong-force-handoff':
            p=root/'usr/local/libexec/labwc-admin-action-worker';p.write_text(p.read_text().replace('"--force", "--no-ask-password"','"--no-ask-password"'))
        proc=subprocess.run(['/bin/sh','-eu','-c',script],capture_output=True,text=True,timeout=5)
        expect=0 if scenario=='intact' else 1
        assert proc.returncode==expect,(scenario,proc.returncode,proc.stdout,proc.stderr)
        results.append(dict(scenario=scenario,returncode=proc.returncode,expected_returncode=expect,stdout=proc.stdout,stderr=proc.stderr))
# Replay the actual account/class topology from the uploaded journal.
w=types.ModuleType('worker_fixture')
path=T/'usr/local/libexec/labwc-admin-action-worker';exec(compile(path.read_text(),str(path),'exec'),w.__dict__)
count=0
def transport(argv,**kwargs):
    global count
    count+=1
    if 'list-sessions' in argv:
        return '1 989 _greetd seat0 2541 greeter tty1 no -\n2 989 _greetd - 2550 manager-early - no -\n'
    assert argv[:2]==['/usr/bin/loginctl','show-session']
    is_greeter=argv[2]=='1'
    props=dict(User='989',Name='_greetd',Class='greeter' if is_greeter else 'manager-early',
               Active='yes' if is_greeter else 'no',Remote='no',Service='greetd-greeter' if is_greeter else 'systemd-user',
               Leader='2541' if is_greeter else '2550')
    return ''.join(k+'='+v+'\n' for k,v in props.items())
w.run=transport
worker=w.Worker(989,'_greetd','poweroff',greeter=True)
worker.protect_other_sessions();worker.protect_other_sessions()
assert worker.greeter_identity==('1','2541')
report=dict(success=True,firstboot_cases=results,
            journal_topology_fixture=dict(user='_greetd',uid=989,greeter_class='greeter',other_class='manager-early',identity=worker.greeter_identity,transport_calls=count),
            limitations='File-operands redirected only in the test. No real firstboot, logind, polkit, systemd unit or power action executed. The account/class values reproduce supplied journal evidence, not a fresh target observation.')
(O/'installed-contract-probe.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'success':True,'firstboot_cases':len(results),'journal_topology':True}))
