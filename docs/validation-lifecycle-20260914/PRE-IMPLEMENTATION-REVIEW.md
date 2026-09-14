# Pre-implementation review - 14 September 2026

This record was written before this pass changed any repository source. The
input is the complete previously delivered tarball, not the older source ZIP.
The hash/mode baseline contains 1,685 regular files. The supplied SSH integration
blueprint remains design background; observed code takes precedence over prose.

## Scope and inspection

Reviewed the managed SSH installer, temporary agent and pipe/memfd transport,
GPG seal/askpass, desktop agent drop-ins, Labwc target teardown, DevOps entry,
host-key policy and Codex isolation; GitOps parsing/tree publication/recovery;
debugsys bounds, sudo wrapper, reports and initramfs rollback; privileged power
worker, polkit routing, lock/save/teardown and transient app lifetimes; AppArmor
transitions and system/user service definitions and vendor drop-ins. The machine
readable inventory lists every service definition/template/drop-in found.

## Findings to fix

1. GitOps installs no TERM/HUP handler although Git children start independent
   process groups. Default signal termination bypasses Python finally cleanup.
   Its pattern parser also accepts ./ and repeated separators that silently fail
   to match protected paths; trailing-slash globs are treated as literal strings.
2. git-ssh unlock trusts systemctl start's exit status. A skipped ExecCondition
   can return success without loading a key. The vendor agent drop-ins have only
   PartOf/ConditionEnvironment, not an explicit active-target Requisite/order.
3. The loader AppArmor profile has a pinentry transition and the child receives
   signals, but the parent lacks the matching send permission to terminate that
   differently confined child. Add exact peer/signal rules, not broad access.
4. Installer public-key rereads assume mode 0600 even though runtime and the guide
   accept 0644. Preserve encrypted-private-key restrictions and rollback modes.
5. Power transport cleanup covers TimeoutExpired but not other exceptions during
   communicate. Retain the existing authorization/save/commit/force sequence,
   and make cleanup unconditional. Mark the host and forking-lock boundaries.
6. Diagnostics do not expose the selected services' PID/user namespace settings;
   add bounded metadata-only probes. Keep the collector in the host namespace.
   A filesystem-type probe bypasses the report's remaining-time budget.
7. The known-hosts provenance comment names an absent guide; point it at the
   actual operations guide without changing host keys.

## PID namespace decision

Enable PrivatePIDs=yes only for four system-manager services: Bluetooth
controller initialization, NVIDIA character-device link reconciliation, zram
maintenance and the foreground zram PSI handler. Explicit PrivateUsers=no keeps
host identity/capabilities; for zram, ProcSubset=all preserves meminfo and PSI.
Do not add it to the agent/loader, power service, forking screen lock, compositor,
terminals, diagnostic collector, firstboot, tmpfs pre-clean, container services,
application broker/launcher families, or unverified vendor daemons. No new
PrivateUsers=self/identity/full mapping is proposed anywhere.

systemd v257 introduced PrivatePIDs; it gives each Exec process a separate PID
namespace, is incompatible with Type=forking, implies MountAPIVFS and may need
unprivileged user namespaces for user-manager services. An identity user mapping
still isolates capabilities. These decisions use upstream versioned documentation,
not an assumption that visible UID 0 has host-root capabilities.

## Validation plan and honest limits

Add behavioral regressions for cancellation, pattern matching, public-key modes,
unit gates, metadata coverage and the AppArmor peers. Retest existing SSH/GitOps,
Codex, lifecycle/security, power and hardware suites. Regenerate payload/hash
products and check the extracted delivery. Syntax parsing is not enforce-mode
acceptance. Actual logind/Labwc, graphical pinentry, PID namespace activation,
initramfs rebuild and reboot require a disposable target.

The baseline focused managed-Git/debugsys suite ran 56 tests: 55 passed, one
OpenSSH-binary availability skip. An initial full baseline run was stopped at
its time bound; it is not a pass. A test-dependency package-index attempt also
hit its time bound without installing packages. No component was compiled.

## Primary references checked

- https://raw.githubusercontent.com/systemd/systemd/v257/man/systemd.exec.xml
- https://raw.githubusercontent.com/systemd/systemd/v258/man/systemd.exec.xml
- https://manpages.debian.org/testing/systemd/systemd.exec.5.en.html
- https://www.gnupg.org/documentation/manuals/gnupg24/gpg-agent.1.html
- https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints
- https://www.kernel.org/doc/html/latest/admin-guide/LSM/apparmor.html
