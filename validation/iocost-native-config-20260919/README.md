# IOCost native config migration release qualification

The previous release rejected Debian udev's ordinary, inactive
`/etc/udev/iocost.conf`. `reproduction.json` records the exact failure before
this change. Both native regression roots now include the shipped conffile.

Only the production IOCost staging helper changed. Defaults are saved before
link publication, restored on rollback/disable, and never confused with active
administrator policy. Native schema checks, secure target paths, locking,
transactional publication and target-only hwdb rebuilding remain in force.

## Completed checks

`make build`, `make check`, `make audit` and the hardware-tuning checker passed.
All 152 focused tests passed, including 34 IOCost tests. The rebuilt 1,375-file
payload was checked against every source and manifest entry.

`make test` and the test stage of `make validate` each completed 1,685 tests,
with the same six failures, two errors and 31 skips observed in the unchanged
1,674-test input. No new failure identifiers were detected. These exceptions
were not suppressed; `report.json` and the complete logs record them.

The stock-file integration verifies both enabled profiles, the native selected
solution, nine queried hwdb properties, repeat staging, and exact-byte native
config restoration. An additional integration run used all 34 available native
vendor hwdb source files: both enabled profiles and the disabled restoration
passed strict compilation, preserving every vendor source. The parser-only
query intentionally uses a nonexistent
device and fails only after reporting the selected solution; no apply occurs.

This is not a physical target boot or storage calibration result. The KXG6
values remain provisional. Historical qualification reports were retained.
