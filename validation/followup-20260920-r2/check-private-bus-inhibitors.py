#!/usr/bin/env python3
"""Exercise busctl JSON on an owned private bus; never call logind/PID 1."""
import ctypes as C
import ctypes.util
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import time
from unittest import mock

lib = C.CDLL(ctypes.util.find_library('systemd'))
P = C.c_void_p
CALLBACK = C.CFUNCTYPE(C.c_int, P, P, P)

def bind(name, args, result=C.c_int):
    fn=getattr(lib,name);fn.argtypes=args;fn.restype=result
    return fn

new=bind('sd_bus_new',[C.POINTER(P)])
set_address=bind('sd_bus_set_address',[P,C.c_char_p])
client=bind('sd_bus_set_bus_client',[P,C.c_int])
start=bind('sd_bus_start',[P])
request=bind('sd_bus_request_name',[P,C.c_char_p,C.c_uint64])
add_object=bind('sd_bus_add_object',[P,C.POINTER(P),C.c_char_p,CALLBACK,P])
is_call=bind('sd_bus_message_is_method_call',[P,C.c_char_p,C.c_char_p])
new_reply=bind('sd_bus_message_new_method_return',[P,C.POINTER(P)])
open_container=bind('sd_bus_message_open_container',[P,C.c_char,C.c_char_p])
close_container=bind('sd_bus_message_close_container',[P])
append=bind('sd_bus_message_append_basic',[P,C.c_char,P])
send=bind('sd_bus_send',[P,P,C.POINTER(C.c_uint64)])
process=bind('sd_bus_process',[P,C.POINTER(P)])
message_unref=bind('sd_bus_message_unref',[P],P)
slot_unref=bind('sd_bus_slot_unref',[P],P)
bus_close=bind('sd_bus_flush_close_unref',[P],P)

def checked(value):
    if value<0:raise OSError(-value,'sd-bus operation failed')
    return value

name=b'org.example.PowerValidation'
path=b'/org/example/PowerValidation'
records=[]
callback_errors=[]
bus=P();slot=P()

@CALLBACK
def handle(message,userdata,error):
    if is_call(message,name,b'ListInhibitors')<=0:return 0
    reply=P()
    try:
        checked(new_reply(message,C.byref(reply)))
        checked(open_container(reply,b'a',b'(ssssuu)'))
        for record in records:
            checked(open_container(reply,b'r',b'ssssuu'))
            for value in record[:4]:checked(append(reply,b's',C.c_char_p(value.encode())))
            for value in record[4:]:
                number=C.c_uint32(value);checked(append(reply,b'u',C.byref(number)))
            checked(close_container(reply))
        checked(close_container(reply));checked(send(bus,reply,None))
        return 1
    except BaseException as exc:
        callback_errors.append(repr(exc));return -5
    finally:
        if reply:message_unref(reply)

root=Path(sys.argv[1]).resolve()
worker_path=root/'d-i/forky/hooks/target/usr/local/libexec/labwc-admin-action-worker'
loader=importlib.machinery.SourceFileLoader('private_bus_worker_fixture',str(worker_path))
spec=importlib.util.spec_from_loader(loader.name,loader)
worker=importlib.util.module_from_spec(spec);loader.exec_module(worker)
outputs=[]
with tempfile.TemporaryDirectory(prefix='private-inhibitor-bus-') as temporary:
    address='unix:path='+str(Path(temporary)/'bus')
    daemon=subprocess.Popen(['/usr/bin/dbus-daemon','--session','--nofork','--nopidfile','--print-address=1','--address='+address],
                            stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    query=None
    try:
        if not select.select([daemon.stdout],[],[],5)[0]:raise RuntimeError('private bus startup timeout')
        actual=daemon.stdout.readline().strip()
        if not actual.startswith(address):raise RuntimeError('unexpected private bus address')
        checked(new(C.byref(bus)));checked(set_address(bus,actual.encode()))
        checked(client(bus,1));checked(start(bus));checked(request(bus,name,0))
        checked(add_object(bus,C.byref(slot),path,handle,None))
        for mode in ('empty','delay','block','block-weak'):
            records=[] if mode=='empty' else [['shutdown','fixture','private test',mode,1000,1234]]
            query=subprocess.Popen(['/usr/bin/busctl','--address='+actual,'--json=short','--timeout=3s',
                    'call',name.decode(),path.decode(),name.decode(),'ListInhibitors'],
                    stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            deadline=time.monotonic()+5
            while query.poll() is None:
                if time.monotonic()>deadline:raise RuntimeError('fixture call deadline')
                while checked(process(bus,None))>0:pass
                time.sleep(.005)
            stdout,stderr=query.communicate(timeout=1)
            if query.returncode:raise RuntimeError(stderr)
            parsed=json.loads(stdout)
            assert parsed=={'type':'a(ssssuu)','data':[records]},parsed
            with mock.patch.object(worker,'run',return_value=stdout):
                if mode in ('block','block-weak'):
                    try:worker.check_shutdown_inhibitors()
                    except worker.Error:decision='blocked'
                    else:raise AssertionError('blocking inhibitor was ignored')
                else:
                    worker.check_shutdown_inhibitors();decision='allowed'
            outputs.append({'mode':mode,'reply':parsed,'decision':decision})
        assert not callback_errors,callback_errors
    finally:
        if query is not None and query.poll() is None:
            query.kill();query.communicate(timeout=2)
        if slot:slot_unref(slot)
        if bus:bus_close(bus)
        daemon.terminate()
        try:daemon.communicate(timeout=2)
        except subprocess.TimeoutExpired:daemon.kill();daemon.communicate(timeout=2)
print(json.dumps({'private_bus_cases':len(outputs),'results':outputs,'busctl_version':subprocess.check_output(['/usr/bin/busctl','--version'],text=True).splitlines()[0]},indent=2))
