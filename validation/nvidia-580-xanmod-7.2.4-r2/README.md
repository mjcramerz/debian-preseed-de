# Revision-2 evidence

See ../../docs/NVIDIA580-XANMOD724-R2.md for scope, results and limitations.

Completed test suites: nvidia-tests.log (43), cuda-tests.log (40),
wrapper-security-tests.log (3). test-interfaces.log (19) and test-recovery.log (9)
are earlier focused runs of subsets of the same tests, not additional cases.
The two *.interrupted.log files are incomplete broader batches, not passed
suites. Their partial results are not added to the completed-suite totals.

kernel-api-probe.py / .c / .json / .log are a minimal compile/link probe against
Debian 6.12.96 headers, NOT full NVIDIA or XanMod 7.2.4. No module was loaded.
The C file is generated from reduced source-derived fixtures by the production
patch functions. Its copyright attribution is in UPSTREAM-LICENSE.txt.

No evidence here certifies a full unattended boot, Secure Boot enrollment or CUDA
GPU runtime. Existing evidence in the sibling directory without '-r2' belongs
to the incomplete first delivery and must not be counted as current testing.
