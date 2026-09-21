# Repeating the recorded checks

From the extracted repository root, with the documented dependencies installed:

```sh
python -B tools/build.py --check
python -B tools/build_browser_config.py --check
python -B tools/check_preseeds.py
python -B tools/check_shells.py
python -B validation/atomic-output-zram-20260921-r3/run-test-modules.py 0 200
python -B validation/atomic-output-zram-20260921-r3/run-test-modules.py -1 0
```

The first test command handles parallel-safe modules; the second runs the three
shared/slow-fixture modules serially. The runner deliberately reuses complete
prior passing module logs. For an independent rerun, move the existing `test_*.log`
and `tools-test_*.log` files out of this validation directory before running it.
It does not run the installer or activate power/storage operations. Follow the
review for missing dependency and physical-runtime limits. The archived failed
initial runs and R2 counterexamples are historical evidence, not final failures.
