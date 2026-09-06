# Validation: CUDA-legacy and Podman/Incus second pass

Completed: 2026-09-06T17:32:59.331997+00:00. The current five-stage pipeline returned zero.
This is offline/loopback source validation, not a booted unattended installation.

| Check | Result |
| --- | --- |
| Browser currentness | PASS |
| Payload and preseed pins | PASS; 1,219 payload files |
| Debconf preseed checks | 58 files; PASS |
| Full suite | **401 tests; PASS; 0 skipped**; 56.400 seconds |
| CUDA-focused suite | 28 tests: 16 lifecycle/hook, 12 real APT; included above |
| Podman/Incus-focused suite | 81 tests; included above |
| Seven rendered systemd units | `systemd-analyze verify` with isolated dependency fixtures; PASS |
| Hardware profiles | All 13 unchanged from this pass's input archive |

See [the second-pass report](CUDA-LEGACY-SECOND-PASS-2026-09-06.md) for the exact
source policy, tested cases, the startup/client corrections and security tradeoff.
CUDA metadata authenticity and freshness are intentionally not enforced for the
explicitly selected legacy source. HTTPS and available package checksums remain;
other repositories' signature validation remains intact.

## Evidence and classification

`validation/summary.json`, `tests.log` and sibling stage logs are the current run.
Runtime product hashes in the summary match the regenerated files. Additional
logs in `validation/second-pass/` are not extra distinct tests. Its earlier
policy-transition failure is retained and labeled, not presented as success.
`validation/podman-incus-initial/` and the other previous-release folders are
historical evidence, not current validation.

| Audit classification | Count |
| --- | ---: |
| Syntax/parser pass | 404 |
| Lexical systemd structure pass | 113 |
| Inventory only | 475 |
| Blocked by missing dependencies | 154 |
| Template needs rendering | 2 |

The last three categories are not executed runtime successes. The independent
seven-unit check uses executable/dependency fixtures and does not activate services.
AppArmor files are unchanged this pass; historical compilation logs are retained,
but no new kernel policy load or enforcement test was performed.

## Reproduce

```sh
python3 -B tools/build.py
python3 -B tools/validate.py
python3 -B -m unittest discover -v -s d-i/forky/tests -p test_cuda_legacy_apt.py
python3 -B -m unittest discover -v -s d-i/forky/tests -p test_podman_incus_redesign.py
python3 -B validation/podman-incus/verify-rendered-units.py
```

Use a disposable Linux environment. Perl syntax checks can execute BEGIN blocks.
The host used Debian 13, APT 3.0.3 and sqv 1.3.0. Tests use local/loopback fixtures
and disposable keys; the inert APT fixture package is downloaded, not installed.
No host sources, trust policy or package database are modified. Full fixture
coverage needs the tools named in each test's prerequisite guards. This run had
zero skips. `CUDA_TEST_APT_ROOT` can select a separately extracted APT/libapt tree;
that alternate-version run was not performed here.

## Remaining installed-system acceptance

No real d-i boot, live upstream package dependency solve, CUDA package installation,
DKMS build/module loading, Secure Boot, GPU workload, partitioning, desktop launch,
container runtime execution, Incus activation, AppArmor enforcement or reboot
recovery was tested. Current Forky package behavior needs acceptance on the actual
installer image. Browser and site coverage remains static/fixture coverage, not
successful live websites. These boundaries apply regardless of a green unit suite.
