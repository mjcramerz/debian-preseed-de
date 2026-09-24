# Final repository validation

Recorded: 2026-09-24T17:35:13.666120+00:00

All seven validation stages returned zero against the frozen source tree. This is repository validation, not certification of a booted Forky installation.

## Reproduce

```sh
python3 -B tools/build.py --check
python3 -B tools/validate.py --output-dir .build/validation --test-timeout 1200
```

Run in a disposable environment with the required tools. The suite contains loopback and child-process fixtures; some syntax checks execute trusted Perl BEGIN blocks. Test availability depends on installed tools and permissions.

## Results

| Check | Result |
|---|---|
| Installer suite | 2,654 tests: 2,600 passed, 54 skipped; no failures or errors. |
| Tooling suite | 187 tests: 187 passed, 0 skipped; no failures or errors. |
| Shell syntax | 310 files, 631 parser/dependency checks; no failures. |
| Browser, generated build and preseed checks | All passed. |
| Changed AppArmor policies | Offline compilation passed for rendered desktop wrappers (including importer and extraction domains), Tuta AppRun and the permanent TPM enrollment profile. |
| Frozen-source comparison | All 1,812 tracked-in-the-snapshot source/test/product files unchanged during the final run. |
| Preservation | 93 specifically checked hardware/private-Xwayland files unchanged; every profile differs from the upload only by the two rsyslog assignments. Shared Zoom/Discord policy blocks and launch dictionaries also match the upload. |

`summary.json` contains stage return codes, durations and generated-product hashes. `logs/` contains full test output, including exact skip reasons. `preservation.json` names the preserved files; `evidence.json` records tool versions, policy compilation and remaining boundaries.

### Audit categories are not interchangeable

```json
{
  "blocked-dependency": 158,
  "blocked-tool": 11,
  "inventory-only": 582,
  "pass": 485,
  "structure-pass": 215,
  "template-needs-render": 11
}
```

Only `pass` is a completed check; `structure-pass` is a structural/lexical check, not service activation. Blocked dependencies/tools, inventory-only entries and unrendered templates are explicitly not passing runtime tests. Missing Perl Moo/MooX dependencies and optional tools are recorded per file in `audit.json`. An AppArmor policy whose attachment filename ends in `.sh` is classified as policy, not shell; the changed rendered policies were separately compiled as described above.

## Security regression coverage

The focused tests exercise actual spool emission and the actual initramfs negative-check function, safe/unsafe tailscaled metadata, anchored sudo arguments, fixed firewall ownership, privilege-dropped OpenVPN reads and snapshot handoff, AppImage metadata and publication rejection, mandatory helper AppArmor transitions, TPM policy/token/event-log/state-machine checks, and idempotent journal-key management using fixtures. The live nftables transaction is skipped when the executable/capability is unavailable. The generator tests include bad input rejection, host override independence, immutable-source checks and rollback after injected publication failure.

Golden-contract fixtures were adjusted explicitly for the requested policy changes, generated canonical-source inputs and relocation of historical reports. The historical hardware/workload expectations were not retuned to conceal changes. Focused reruns are also included, but are subsets of or supplemental checks to the final full-suite result, not extra tests added to its total.

## Required target acceptance

Validation ran on Debian 13.3 with systemd 257.9, not the requested Forky/systemd 261.2 target. The environment did not provide nftables, bubblewrap, SquashFS extraction tools, cryptsetup or a physical TPM. No target installer was booted and no hardware performance claim is made.

Before release, install on a disposable target; verify the rsyslog mount, ownership and restart/queue behavior; reload the firewall with independently owned tables present; exercise authorized and rejected VPN imports under enforcing AppArmor; and run the real Tuta extraction/update and GPU launch paths. Check the existing private Zoom/Discord Xwayland sessions without enabling a global Xwayland server.

Crypto release additionally requires measured-event/PCR verification, offline recovery and wrong-PIN tests, altered initrd/command-line rejection, a separate successful confirmation boot, and the TPM release check. Persistent disk-backed journal sealing requires off-host verification-key export/acknowledgment and independent archived-journal verification. The supplied RAM-backed logging profiles intentionally do not claim forward-secure persistent sealing.

See `../../security-hardening.md` for operating instructions, migration constraints and the precise policy boundaries.
