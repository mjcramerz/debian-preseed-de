# Build status — 2026-09-29 follow-up

The source tree includes the narrow Discord sandbox and CrowdSec status fixes,
plus the Zoom/Discord clipboard AppArmor rule. The storage follow-up found a
correctable PCIe receiver error, but no evidence that the existing exact-device
link-idle rule failed or that counters continue to increase. The read-only
`nvme-pcie-status` helper and its source policy are unchanged.

**This source archive intentionally omits** `d-i/forky/preseed.cfg`,
`d-i/forky/payload.manifest`, and `d-i/forky/payload.tar.gz`. The prior snapshot
does not contain the new AppArmor policy. This workspace lacks BusyBox, so
`make build` and `make check` stop at the project's mandatory ash syntax gate.
No substitute shell or hand-edited generated artifact is a passing build.
**Do not serve this archive as an unattended installer.**

The focused AppArmor tests, ten Discord/clipboard tests, and fifteen runnable
NVMe policy/status tests pass; the udev parser test is skipped because
`udevadm` is unavailable. `make audit` passes with 599 pass, 218
structure-pass, 159 blocked-dependency, 602 inventory-only, and 11
template-needs-render checks. The broad suites are not a passing release
signal in this workspace. Neither enforce-mode application behavior nor PCIe
hardware response has been tested on the Forky/systemd 261.2 target.

On a trusted release host with BusyBox, run `make build`, `make check`,
`make test`, `make audit`, and `make validate`. Resolve every release-gate
failure and deploy the checked repository atomically. See
`docs/installed-2026-09-29.md` for target-side acceptance and the read-only
NVMe evidence needed to decide whether hardware/firmware work remains.
