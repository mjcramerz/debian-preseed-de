from pathlib import Path
import concurrent.futures,json,os,re,subprocess,sys,time
root=Path(__file__).resolve().parents[2]
out=root/'validation/atomic-output-zram-20260921-r3';out.mkdir(exist_ok=True)
modules=sorted(list((root/'d-i/forky/tests').glob('test_*.py'))+list((root/'tools/tests').glob('test_*.py')))
serial=[p for p in modules if 'debconf_protocol' in p.name or 'bootstrap_portability' in p.name or 'test_log_followup_20260915' in p.name]
parallel=[p for p in modules if p not in serial]
start,end=int(sys.argv[1]),int(sys.argv[2]);selected=parallel[start:end] if start>=0 else serial

def run(path):
    label=('tools-' if '/tools/' in str(path) else '')+path.stem
    command=[sys.executable,'-B','-m','unittest','discover','-v','-s',str(path.parent),'-p',path.name]
    begin=time.monotonic();timedout=False
    existing=out/(label+'.log')
    if existing.is_file() and re.search(r'\n(?:OK(?: \(skipped=\d+\))?|NO TESTS RAN)\n?\Z',existing.read_text()):
        text=existing.read_text();code=5 if 'NO TESTS RAN' in text else 0
        counts=re.findall(r'Ran (\d+) tests? in ([\d.]+)s',text)
        skips=re.findall(r"\.\.\. skipped ['\"](.*?)['\"]\n",text)
        row={'name':label,'source':str(path.relative_to(root)),'returncode':code,'seconds':float(counts[-1][1]) if counts else 0,'tests':int(counts[-1][0]) if counts else 0,'skipped':len(skips),'failed':0,'timed_out':False,'skip_reasons':skips,'log':str(existing.relative_to(root)),'reused_completed_run':True}
        (out/(label+'.json')).write_text(json.dumps(row,indent=2)+'\n')
        return row
    try:
        result=subprocess.run(command,cwd=root,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'},capture_output=True,text=True,timeout=170)
        text=result.stdout+result.stderr;code=result.returncode
    except subprocess.TimeoutExpired as ex:
        text=(ex.stdout or b'')+(ex.stderr or b'')
        if isinstance(text,bytes):text=text.decode(errors='replace')
        code=124;timedout=True
    (out/(label+'.log')).write_text(text)
    counts=re.findall(r'Ran (\d+) tests? in',text)
    skip=re.findall(r"\.\.\. skipped ['\"](.*?)['\"]\n",text)
    failures=re.findall(r'FAILED \(([^)]+)\)',text)
    unsuccessful=sum(int(n) for n in re.findall(r'(?:failures|errors)=(\d+)', failures[-1] if failures else ''))
    row={'name':label,'source':str(path.relative_to(root)),'returncode':code,'seconds':round(time.monotonic()-begin,3),'tests':int(counts[-1]) if counts else 0,'skipped':len(skip),'failed':unsuccessful,'timed_out':timedout,'skip_reasons':skip,'log':str((out/(label+'.log')).relative_to(root))}
    (out/(label+'.json')).write_text(json.dumps(row,indent=2)+'\n')
    print(label, 'rc='+str(code), 'tests='+str(row['tests']), 'skips='+str(len(skip)),flush=True)
    return row
with concurrent.futures.ThreadPoolExecutor(max_workers=4 if start>=0 else 1) as pool:
    results=list(pool.map(run,selected))
(out/f'batch-{start}-{end}.json').write_text(json.dumps(results,indent=2)+'\n')
print('BATCH',len(results),'failures',[r['name'] for r in results if r['returncode']])
