from pathlib import Path
import sys,time,unittest
root=Path(sys.argv[1]);sys.path.insert(0,str(root/'d-i/forky/tests'))
import test_repository_transport as test
from process_fixture import wait_file

def observe(path,timeout=8):
    started=time.monotonic()
    ok=wait_file(path,timeout=30)
    print(f'DIAGNOSTIC ONLY: file={path.name}; original deadline={timeout}s; diagnostic deadline=30s; elapsed={time.monotonic()-started:.3f}s; observed={ok}',flush=True)
    if not ok:
        print('Runtime files:',[(str(p.relative_to(path.parents[1])),p.stat().st_size) for p in path.parents[1].rglob('*') if p.is_file()][-20:])
    return ok

test.wait_file=observe
suite=unittest.defaultTestLoader.loadTestsFromName('RealBootstrapTests.test_opposite_role_fails_before_preflight_marker',test)
result=unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(not result.wasSuccessful())
