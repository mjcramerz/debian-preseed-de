import hashlib, json, os, sys, time, unittest
from pathlib import Path
root=Path(sys.argv[1]).resolve()
index=int(sys.argv[2])
output=Path(sys.argv[3]).resolve()
os.chdir(root)
sys.path.insert(0,str(root/'d-i/forky/tests'))
loader=unittest.TestLoader()
all_suite=loader.discover(str(root/'d-i/forky/tests'),pattern='test_*.py')
def flatten(suite):
    for item in suite:
        if isinstance(item,unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item
all_tests=list(flatten(all_suite))
groups={}
for test in all_tests:
    groups.setdefault(test.id().split('.')[0],[]).append(test)
partitions=[[] for _ in range(4)]
loads=[0]*4
for module,tests in sorted(groups.items(),key=lambda pair:(-len(pair[1]),pair[0])):
    dest=min(range(4),key=lambda n:(loads[n],n))
    partitions[dest].append(module)
    loads[dest]+=len(tests)
selected=[t for t in all_tests if t.id().split('.')[0] in partitions[index]]
started=time.monotonic()
result=unittest.TextTestRunner(verbosity=1).run(unittest.TestSuite(selected))
report={'partition':index,'partition_count':4,'discovered_tests':len(all_tests),
        'assigned_counts':loads,'modules':sorted(partitions[index]),
        'test_ids':[test.id() for test in selected],
        'tests_run':result.testsRun,'seconds':time.monotonic()-started,
        'failures':[t.id() for t,_ in result.failures],
        'errors':[t.id() for t,_ in result.errors],
        'skipped':[(t.id(),reason) for t,reason in result.skipped],
        'expected_failures':[t.id() for t,_ in result.expectedFailures],
        'unexpected_successes':[t.id() for t in result.unexpectedSuccesses]}
output.write_text(json.dumps(report,indent=2)+'\n')
sys.exit(not result.wasSuccessful())
