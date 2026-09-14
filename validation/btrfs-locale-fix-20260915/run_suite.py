from pathlib import Path
import argparse,importlib.util,json,os,sys,time,unittest
p=argparse.ArgumentParser()
p.add_argument('repository',type=Path)
p.add_argument('output',type=Path)
p.add_argument('--pattern',default='test_*.py')
p.add_argument('--ids-json',type=Path)
p.add_argument('--new-tests-on-baseline',type=Path)
a=p.parse_args()
a.repository=a.repository.resolve()
a.output=a.output.resolve()
if a.new_tests_on_baseline: a.new_tests_on_baseline=a.new_tests_on_baseline.resolve()
if a.ids_json: a.ids_json=a.ids_json.resolve()
os.chdir(a.repository)
sys.path.insert(0,str(a.repository/'d-i/forky/tests'))
os.environ['PYTHONDONTWRITEBYTECODE']='1'
sys.dont_write_bytecode=True
if a.new_tests_on_baseline:
    spec=importlib.util.spec_from_file_location('test_btrfs_locale_boundary',a.new_tests_on_baseline)
    m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
    m.SEED=a.repository/'d-i/forky';m.TARGET=m.SEED/'scripts/common/target.sh';m.LAYOUT=m.SEED/'hosts/installer/layout-btrfs.env'
    suite=unittest.defaultTestLoader.loadTestsFromModule(m)
elif a.ids_json:
    ids=[i[1] for i in json.loads(a.ids_json.read_text())['failing_identifiers']]
    suite=unittest.defaultTestLoader.loadTestsFromNames(ids)
else:
    suite=unittest.defaultTestLoader.discover(str(a.repository/'d-i/forky/tests'),pattern=a.pattern)
a.output.parent.mkdir(parents=True,exist_ok=True)
start=time.monotonic()
with a.output.with_suffix('.log').open('w') as log:
    result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
summary={'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),
         'successful':result.wasSuccessful(),'seconds':round(time.monotonic()-start,3),
         'failing_identifiers':[['FAIL',x.id()] for x,_ in result.failures]+[['ERROR',x.id()] for x,_ in result.errors],
         'skipped_tests':[[x.id(),why] for x,why in result.skipped]}
a.output.with_suffix('.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps({k:v for k,v in summary.items() if k not in ('failing_identifiers','skipped_tests')},indent=2),flush=True)
sys.exit(not result.wasSuccessful())
