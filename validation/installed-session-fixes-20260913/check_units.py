from pathlib import Path
import os,subprocess,tempfile,json
r=Path(__file__).resolve().parents[2]
t=r/'d-i/forky/hooks/target'
out=r/'validation/installed-session-fixes-20260913'
records=[]
with tempfile.TemporaryDirectory() as directory:
    d=Path(directory); d.chmod(0o700)
    for scope, prefix, units in [
        ('system','etc/systemd/system',['managed-nvidia-char-links.service','managed-nvidia-char-links.path']),
        ('user','etc/skel-desktop/.config/systemd/user',['labwc-session-state@.service','labwc-session-restore.service'])]:
        paths=[]
        for unit in units:
            source=(t/prefix/unit).read_text()
            source=source.replace('/usr/local/libexec/labwc-session-state','/usr/bin/true').replace('/usr/local/libexec/managed-nvidia-char-links','/usr/bin/true')
            (d/unit).write_text(source); paths.append(str(d/unit))
        (d/'labwc-session.target').write_text('[Unit]\nDescription=Offline dependency fixture\n')
        command=['systemd-analyze'] + (['--user'] if scope=='user' else []) + ['verify',*paths]
        env=dict(os.environ,XDG_RUNTIME_DIR=str(d),SYSTEMD_UNIT_PATH=str(d)+':')
        result=subprocess.run(command,capture_output=True,text=True,env=env,timeout=15)
        records.append({'scope':scope,'units':units,'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr})
(out/'systemd-unit-check.json').write_text(json.dumps({'scope':'Offline parser/dependency check; target executable paths substituted with /usr/bin/true, labwc-session.target is a dependency fixture; no services started.','results':records},indent=2)+'\n')
for item in records: print(item)
