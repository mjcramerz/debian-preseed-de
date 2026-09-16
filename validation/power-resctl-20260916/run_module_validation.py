#!/usr/bin/env python3
"""Non-destructive existing unittest suites, isolated and bounded by module."""
import argparse, concurrent.futures, json, os, pathlib, re, subprocess, sys, time
p=argparse.ArgumentParser();p.add_argument('--root',type=pathlib.Path,required=True);p.add_argument('--output',type=pathlib.Path,required=True);p.add_argument('--modules',nargs='*');p.add_argument('--workers',type=int,default=4);p.add_argument('--timeout',type=int,default=240)
a=p.parse_args();a.root=a.root.resolve();a.output=a.output.resolve();a.output.mkdir(parents=True,exist_ok=True)
files=sorted((a.root/'d-i/forky/tests').glob('test_*.py'))
if a.modules: files=[f for f in files if f.stem in a.modules]
def run(f):
 start=time.monotonic();log=a.output/(f.stem+'.log')
 command=[sys.executable,'-B','-m','unittest','discover','-v','-s','d-i/forky/tests','-p',f.name]
 with log.open('w') as stream:
  proc=subprocess.Popen(command,cwd=a.root,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True,env=dict(os.environ,PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'))
  try: rc=proc.wait(timeout=a.timeout)
  except subprocess.TimeoutExpired:
   import signal
   os.killpg(proc.pid,signal.SIGKILL);proc.wait();rc=124
 text=log.read_text();m=re.search(r'Ran (\d+) tests? in',text);skip=re.search(r'(?m)^(?:OK|FAILED) \([^\n]*?skipped=(\d+)',text)
 failures=re.findall(r'(?m)^(?:FAIL|ERROR): (.+)$',text)
 item=dict(module=f.stem,returncode=rc,seconds=round(time.monotonic()-start,2),tests=int(m[1]) if m else None,skipped=int(skip[1]) if skip else 0,failures=failures,log=log.name)
 item['no_tests'] = rc == 5 and item['tests'] == 0 and 'NO TESTS RAN' in text
 print(json.dumps(item),flush=True);return item
with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
 records=list(pool.map(run,files))
result=dict(success=all(r['returncode']==0 or r['no_tests'] for r in records),modules=len(records),tests=sum(r['tests'] or 0 for r in records),skipped=sum(r['skipped'] for r in records),timed_out=[r['module'] for r in records if r['returncode']==124],results=records)
(a.output/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
sys.exit(0 if result['success'] else 1)
