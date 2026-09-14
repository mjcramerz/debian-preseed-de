# GPG recipient fix evidence

The authoritative full-suite result is `full-validation/result.json`; it is
explicitly not green. All seven failures/errors reproduce on the previous
archive (see `baseline-comparison.json`). The new regression module passes.

The pre-fix reproduction uses disposable keys, not customer data. Run it with
`python3 -B reproduce-gpg-conflict.py /path/to/previous/debian-preseed-de`.
It intentionally exercises the old API and is not a live-system repair tool.

The supplied raw installer logs and private inputs are not included here.
`input-provenance.json` records their hashes for traceability. Review and
validation reports are under `docs/`.
