"""Diagnostic only: observe the existing fatal-record test beyond its 8s cutoff.
The repository assertion/timeout are NOT edited and this is NOT a suite pass.
"""
import sys, time, json, unittest
from pathlib import Path
root=Path(sys.argv[1]); output=Path(sys.argv[2])
sys.path.insert(0,str(root/'d-i/forky/tests'))
import test_repository_transport as test
observations=[]
original=test.wait_file
def observe(path,timeout=8):
    start=time.monotonic()
    result=original(path,30)
    observations.append({'standard_timeout_seconds':timeout,'diagnostic_timeout_seconds':30,
                         'observed_seconds':round(time.monotonic()-start,3),'record_found':result,
                         'record':path.read_text() if path.exists() else None})
    return result
test.wait_file=observe
suite=unittest.TestSuite([test.RealBootstrapTests('test_opposite_role_fails_before_preflight_marker')])
result=unittest.TextTestRunner(verbosity=2).run(suite)
output.write_text(json.dumps({'diagnostic_only':True,'repository_test_unmodified':True,
    'basis':str(root),'observations':observations,'diagnostic_assertions_succeeded':result.wasSuccessful()},indent=2)+'\n')
