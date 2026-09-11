# Validation evidence for this patch

Read ../../FIXES-2026-09-11.md and summary.json first. This is not an
all-tests-pass or target-installation certificate. Failed, skipped, excluded,
and unexercised checks are retained, not suppressed. The older validation files
outside this directory arrived in the supplied ZIP and are not this run.

The broad run was followed by one final ChatGPT AppArmor handoff fix and a new
regression; final-affected.log and new-regressions.log are after that fix.
Shell, preseed, build and AppArmor parse logs are also after the final fix.

The AppArmor parse checks use repository policy plus installed host abstractions
in an isolated include directory and do not load policy into the kernel. Audit
coverage is a finite source-mapping regression, not a live denial replay.

Archive packaging excludes only .git, __pycache__ and .pytest_cache. It normalizes
public source archive modes; target-private modes remain explicit in the installer.
