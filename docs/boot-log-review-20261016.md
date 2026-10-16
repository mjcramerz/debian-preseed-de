# Boot log review: 16 October 2026

## Scope and evidence

Reviewed the 93 supplied regular files under `todo/` as data: 3,964,399
bytes and 24,938 newline records, including 23 empty files. Empty scanner
logs do not establish that a scanner ran successfully. No development host
service, security policy, device, network or package state was changed.

The copied target reports Debian Forky/sid, systemd 262 and kernel
`7.2.11-x64v3-xanmod1`. The hardware records identify the Flex 5-14ITL05
family, with BIOS `FXCN49WW` dated 2024-09-05. These are observations from
the supplied files, not a live inspection of the development host.

## Stubby ordering cycle: source fix implemented

`todo/installer-state/logs/firstboot/data/dmesg-warnings.txt`, lines 10-11,
records this cycle and deletion of Stubby's start job:

```text
stubby
  after network-online
  after NetworkManager-wait-online
  after NetworkManager
  after NetworkManager-dispatcher
  after basic
  after paths
  after apt-repo-local-inbox.path
  after sysinit
  after stubby
```

The drop-in supplied `Before=sysinit.target` and tried to remove Debian's
network dependencies with empty `Wants=` and `After=` assignments. systemd
dependency lists cannot be cleared in a drop-in. Removing vendor dependencies
requires a complete base unit override, as documented in
[systemd.unit](https://github.com/systemd/systemd/blob/main/man/systemd.unit.xml).

The new `/etc/systemd/system/stubby.service` omits Debian's
`Wants=network-online.target` and `After=network-online.target`. It retains
Debian's notify readiness, DynamicUser, runtime directory, working directory,
command and restart contract. The reference unit was read as data from the
[Debian getdns 1.7.3-5 source archive](https://deb.debian.org/debian/pool/main/g/getdns/getdns_1.7.3-5.debian.tar.xz).
The supplied logs do not establish the installed Stubby package version.

The existing drop-in retains the early listener ordering, AppArmor attachment,
capability removal and sandbox. The installer stages both files. Resolved's
ordering after Stubby and the application DNS frontend's dependency on Stubby
remain intact. A full override must be reviewed against future Debian Stubby
unit changes when updating that package contract.

The firstboot validator now checks the loaded fragment path and effective
`After`/`Before` properties, and requires the service to be active. Checking
only failed units missed the deleted start job in these logs: the supplied
failed-unit snapshot is empty, and another dependency later starts Stubby.

`test_stubby_boot_order.py` adds a native private unit graph that reproduces
the vendor dependency cycle, including the ineffective blank resets, and
checks the replacement graph. Separate command fixtures exercise firstboot's
acceptance and rejection paths. These checks are guarded for the disposable
test image and **have not been executed in this session**.

## Reported kernel messages

| Message | Evidence and interpretation | Disposition |
| --- | --- | --- |
| `x86/split lock detection: #AC: crashing the kernel ... warning on user-space split_locks` | `todo/managed/system/kernel.log:2`. Linux emits this with `pr_info` while reporting the selected split-lock policy. The supplied logs contain no actual `split_lock trap`, kernel panic or Oops. | Informational initialization message. No split-lock policy change. |
| `DPC: error containment capabilities: ...` on the two PCIe root ports | `todo/managed/system/kernel.log:590-596` reports AER enabled, DPC enabled and supported DPC capabilities. Linux emits the capability line with `pci_info` during DPC setup. No DPC containment event or AER error is present in the supplied kernel log. | Informational capability announcement. No PCIe containment or error reporting change. |
| `ucsi_acpi ... unknown error 88`, followed by `UCSI_GET_PDOS failed (-5)` | `todo/managed/system/usb/usb.log:51-59` and the warning snapshot show two failed requests during early USB-C initialization, around 0.864 and 0.927 seconds. | Actual USB-C Power Delivery capability query failure; the user reports no functional failure. |

Primary Linux sources for these classifications:

- [Split-lock policy report](https://github.com/torvalds/linux/blob/master/arch/x86/kernel/cpu/bus_lock.c).
- [PCIe DPC initialization and event handling](https://github.com/torvalds/linux/blob/master/drivers/pci/pcie/dpc.c).
- [UCSI command and error handling](https://github.com/torvalds/linux/blob/master/drivers/usb/typec/ucsi/ucsi.c)
  and [error bit definitions](https://github.com/torvalds/linux/blob/master/drivers/usb/typec/ucsi/ucsi.h).

### UCSI: capability query failure with no reported functional failure

The kernel prints the controller's error value in **decimal** (`%u`).
88 is `0x58`: the upstream UCSI definitions identify the set bits as
incompatible partner (bit 3), CC communication error (bit 4), and contract
negotiation failure (bit 6). The error decoder switches on individual values;
the combined value takes its unknown-error path and returns `-EIO` (`-5`).
This explains the two messages without proving whether the underlying fault
is in the partner, cable, controller firmware, stale controller state, or
the running kernel. The exact downstream XanMod source was not available in
the supplied evidence; the matching upstream code establishes message
semantics, not a proven downstream fix.

The copied BIOS version matches the version currently published for this
model on [Lenovo's support page](https://support.lenovo.com/nz/en/downloads/DS546876).
That page supplies no confirmed fix for this UCSI failure. The upstream
`ucsi_acpi` quirk table inspected during this review has no matching Flex
entry or supported configuration option that resolves this error.

USB data connectivity does come up: the copied kernel log reports the
USB Ethernet adapter's carrier on at line 903. The user subsequently confirmed
that only the power charger and USB-C Ethernet adapter were attached, and
nothing seems to fail. This supports treating the observed error as a failed
capability query without an observed charging or Ethernet failure. It does
not establish the exact firmware/partner cause or test other USB-C functions.

No USB-C driver or power policy change is justified by this evidence. If an
actual USB-C function fails, an authorized hardware reproduction can compare
disconnected and connected boot logs, the exact partner/cable and power
source, and an available packaged Debian kernel. Those results would support
a Lenovo or kernel driver report. No controller reset, firmware flash, kernel
replacement or driver blacklist was performed. A blanket `ucsi_acpi` blacklist
would remove functionality and does not establish a repair.

## Other supplied warnings and errors

- The firstboot snapshot was collected while the boot transaction was still
  running. `systemd-analyze time` reporting an unfinished boot at that point
  does not establish a sustained boot hang. The early validation reports a
  pass; the new Stubby gate closes the specific gap found above.
- The two audit logs contain 13,013 records. All 435 AppArmor AVC records are
  profile `STATUS` records; no AppArmor `DENIED` or `ALLOWED` record was found.
  Failed audited syscalls include ordinary executable PATH searches (`ENOENT`),
  absent unit-link cleanup paths, and nonempty systemd unit directories
  (`ENOTEMPTY`). Those records do not justify widening AppArmor policy.
- Mullvad's package maintainer script reports an AppArmor reload failure
  during installation in the target chroot. Later copied firstboot evidence
  reports the loaded managed AppArmor modes passing validation. No host policy
  reload was attempted.
- CrowdSec's Console synchronization errors state that the machine is not
  enrolled. An enrollment token was staged, but the copied logs do not prove
  completed remote approval. Console enrollment remains an external state
  requirement. The firewall bouncer is separately operating in these logs:
  it reports 15,000 decisions added at 21:15:53.
- CrowdSec's absent qBittorrent log at early boot is covered by its enabled
  30-second file discovery polling. Duplicate grok-name warnings originate
  in the installed parser set; no supplied evidence shows acquisition or
  bouncer failure caused by those warnings.
- The global Labwc Xwayland warning is consistent with the requested private
  Xwayland policy. No Xwayland files or settings were changed.
- Other firmware warnings include the kernel's I2C bus-speed fallback and
  short Wacom HID initialization reports. The supplied records do not prove
  a configuration fix or a later functional failure for those devices.

## Verification boundary

Source inspection, Python AST parsing without imports, diff inspection and
archive/hash inspection are permitted in this checkout. `make build` is the
explicitly permitted serialization step for the three installer products.
No tests, native unit verification, shell validation runner, policy parser,
service operation or hardware experiment was run on the development host.
An approved disposable test image was not available. The new regression
tests and a fresh installed-system boot remain deployment validation gates.
The UCSI capability query warning is explained but has no proven firmware or
driver repair in this change; the user reports no functional impact.
