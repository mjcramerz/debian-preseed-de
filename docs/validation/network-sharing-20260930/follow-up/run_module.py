import json, os, sys, time, unittest
from pathlib import Path
root = Path(sys.argv[1]).resolve()
module = sys.argv[2]
output = Path(sys.argv[3]).resolve()
os.chdir(root)
sys.path.insert(0, str(root/'d-i/forky/tests'))
suite = unittest.defaultTestLoader.discover(str(root/'d-i/forky/tests'), pattern='test_*.py')
def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite): yield from flatten(item)
        else: yield item
selected = [t for t in flatten(suite) if t.id().split('.')[0] == module]
assert selected
start = time.monotonic()
result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(selected))
report = {'module': module, 'test_ids': [t.id() for t in selected], 'tests_run': result.testsRun,
          'seconds': time.monotonic()-start, 'failures': [t.id() for t,_ in result.failures],
          'errors': [t.id() for t,_ in result.errors],
          'skipped': [(t.id(), why) for t,why in result.skipped],
          'expected_failures': [t.id() for t,_ in result.expectedFailures],
          'unexpected_successes': [t.id() for t in result.unexpectedSuccesses]}
output.write_text(json.dumps(report,indent=2)+'\n')
sys.exit(not result.wasSuccessful())
