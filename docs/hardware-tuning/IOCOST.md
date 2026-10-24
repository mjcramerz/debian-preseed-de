# IOCost profile data and acceptance

`IOCOST_CALIBRATE_ENABLE` enables installation of the profile's native IOCost
metadata. Installation does not run a storage benchmark. The selected solution
is `IOCOST_TARGET_SOLUTION`, which must occur in `IOCOST_SOLUTIONS`. Every listed
solution has its own six model coefficients and six QoS fields. The existing
renderer in `scripts/late/iocost.sh` validates these fields before publication;
reserved empty groups are not advertised.

Model fields are `RBPS`, `RSEQIOPS`, `RRANDIOPS`, `WBPS`, `WSEQIOPS`, `WRANDIOPS`.
QoS fields are `RPCT`, `RLAT`, `WPCT`, `WLAT`, `MIN`, `MAX`. Rates are bytes/s or
4 KiB operations/s, latencies are microseconds, and percentiles/rates are percent.
Do not infer QoS latency targets or controller min/max from isolated peak rates.

## October 24 Flex baseline

The supplied `todo/reports-storage-flex/iocost.json` is an **untuned baseline**
and explicitly reports `status=needs_review`, `applied=false`. Its drive identity
is `KXG6AZNV512G TOSHIBA`, firmware `5108AGLA`. Its candidate coefficients are:

| Field | Candidate value |
| --- | ---: |
| RBPS | 2350302939 |
| RSEQIOPS | 144524 |
| RRANDIOPS | 139156 |
| WBPS | 656015893 |
| WSEQIOPS | 96787 |
| WRANDIOPS | 87763 |

These are recorded candidates, **not newly accepted deployment values**. All 27
fio trials completed, but the sequential-read trials are approximately
3.240, 2.350 and 2.155 GB/s. The report rejects the complete model's repeatability
gate because RBPS variation exceeds 10%. Other individual successful trials do
not establish acceptance of the complete device model.

The companion hwdb candidate contains `rpct=0 wpct=0` and describes this as an
explicit internal-saturation policy. It supplies no measured read/write QoS
latency targets or controller min/max. QD1 and mixed-load observations alone are
not an accepted contention/QoS calibration. No accepted replacement QoS export
is present in the supplied directory.

Accordingly the October 24 baseline does not replace the existing profile
solutions derived from the September 23 export. Flex single/duo retain their
existing selected `naive` solution and full model/QoS fields. P15s remains opted
out of that Flex drive policy. This preserves the existing data; it is not a
new assertion of its native performance or stability on this revision.

To incorporate replacement values, supply a complete repeatable six-coefficient
model and accepted QoS experiment for the identified drive/firmware, with raw
trial evidence, saturation/queue-depth and thermal/health observations, plus
the chosen percentile, latency and controller min/max policy. Add the solution
and all twelve fields to every profile together, selecting it only on the
intended hardware. Do not mark a rejected report accepted, mix coefficients
across unrelated runs, or fabricate latency values to fill the schema.

No calibration, cgroup write, hwdb reload or device benchmark ran on the
development host. Storage acceptance remains an explicit open gate in
the [October 24 review](../validation/failures-hardware-20261024.md).
