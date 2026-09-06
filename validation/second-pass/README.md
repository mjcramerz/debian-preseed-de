# Second-pass evidence

`../summary.json`, `../tests.log`, and the other parent logs are the current full
pipeline. Focused logs here are additional checks, not additional distinct tests
to add to the full-suite count. `systemd-units.log` is rendered-unit verification
with isolated dependency fixtures, not service activation.

`pipeline/` and `pipeline-driver.log` record the first policy-transition run: one
obsolete strict-Sequoia assertion failed. That assertion was rewritten as an
ordinary-repository strong-signature and wrong-fingerprint control test; it was
not silently skipped. `baseline-tests.log` is an interrupted initial run, not
passing evidence. Current successful results supersede these diagnostic runs.
