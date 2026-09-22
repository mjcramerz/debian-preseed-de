"""A mount-namespace fixture, never the host user bus or production service."""
from pathlib import Path
import errno, json, socket, subprocess, tempfile
R=Path(__file__).resolve().parents[2]
O=R/'validation/followup-20260922'
child=r'''
import errno, pathlib, socket, sys
runtime=pathlib.Path(sys.argv[1]); kind=sys.argv[2]
sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
if kind=='hidden':
    try: sock.connect(str(runtime/'bus'))
    except FileNotFoundError: print('hidden runtime: IPC inaccessible (expected prior-policy failure)')
    else: raise AssertionError('hidden runtime unexpectedly reachable')
else:
    assert (runtime/'readable').read_text()=='fixture'
    try: (runtime/'must-not-create').write_text('forbidden')
    except OSError as exc: assert exc.errno==errno.EROFS,exc
    else: raise AssertionError('read-only runtime allowed file creation')
    sock.connect(str(runtime/'bus'));sock.sendall(b'probe')
    print('read-only runtime: IPC usable; regular file creation denied')
sock.close()
'''
results=[]
with tempfile.TemporaryDirectory(prefix='runtime-ipc-probe-') as tmp:
    root=Path(tmp);runtime=root/'runtime';runtime.mkdir(mode=0o700)
    (runtime/'readable').write_text('fixture')
    script=root/'client.py';script.write_text(child)
    server=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);server.settimeout(3)
    server.bind(str(runtime/'bus'));server.listen(1)
    for mode in ('hidden','readonly'):
        setup='mount --make-rprivate /; '
        if mode=='hidden':
            setup+='mount -t tmpfs -o mode=000,nosuid,nodev,noexec tmpfs "$1"; '
        else:
            setup+='mount --bind "$1" "$1"; mount -o remount,bind,ro "$1"; '
        setup+='exec /usr/bin/python3 "$2" "$1" "$3"'
        command=['/usr/bin/unshare','--user','--map-root-user','--mount','--fork','/bin/sh','-eu','-c',setup,'fixture',str(runtime),str(script),mode]
        proc=subprocess.run(command,capture_output=True,text=True,timeout=10)
        row=dict(mode=mode,returncode=proc.returncode,stdout=proc.stdout,stderr=proc.stderr)
        if mode=='readonly' and proc.returncode==0:
            conn,_=server.accept()
            with conn: row['received']=conn.recv(16).decode()
            assert row['received']=='probe'
        results.append(row)
    server.close()
report=dict(methodology='Separate disposable user/mount namespaces model inaccessible versus read-only runtime mounts. Uses a temporary UNIX socket, not the system/user bus. Does not start a systemd service.',
            success=all(x['returncode']==0 for x in results),checks=results)
(O/'runtime-ipc-probe.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
