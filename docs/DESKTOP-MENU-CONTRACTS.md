# Desktop menu and AppArmor contracts

The graphical Main Menu uses `labwc-main-menu` and GIO's application catalog.
Its fixed Computer Management action enters `labwc-computer-management`, which
opens the existing managed terminal. Only that terminal's management menus set
`LABWC_MENU_BACKEND=fzf`; application search and ordinary graphical menus remain
Fuzzel. Six management groups retain their 23 fixed routes and their existing
privilege-separated workers, confirmations, terminal lifetime and cgroup policy.

## Picker protocol

A chooser transports data, never a shell command. Fixed action labels must match
an offered choice. Free text is enabled only at explicit data prompts through
`LABWC_MENU_INPUT_MODE=text`; this includes both authorized public IPv4 prompts.
Authorization confirmation and the action worker's address validation remain
required. Neither a menu prompt nor a test performs an automatic network scan.

The fzf adapter removes inherited `FZF_*` options and commands. The independent
AI & Copilots picker also launches fzf with a closed environment; header rows and
its original catalogs remain intact. Internal fzf bindings provide selection,
back/cancel and typed input, not preview/reload/execute shell commands. Unknown
input modes and control/bidi characters in text suggestions are rejected.

Status 1 is dismissal at the common picker boundary. The fzf adapter normalizes
native status 130 to dismissal. Other errors retain diagnostics and do not
masquerade as cancellation. Shell confirmation helpers explicitly propagate
picker failures because POSIX shell `errexit` is suppressed inside conditions.
Multi-file selection removes its own temporary lists on picker failure.
Cancelled address entry returns to the parent menu without invoking an action.

The graphical wrapper serializes launches with its existing lock and closes the
lock descriptor in its child. HUP/INT/TERM terminate the wrapper with the matching
status; EXIT cleanup terminates and reaps the tracked child and removes its PID
file. It does not signal arbitrary processes or use process-name matching.

## AppArmor ownership

The Main Menu has an explicit strict transition to Computer Management. Existing
management action attachments, privileged action profiles, worker isolation and
vendor-profile adaptation remain authoritative. Fuzzel cleanup has matching TERM
send/receive permissions between `managed-labwc-fuzzel` and
`managed-desktop-launcher`; there is no new unrestricted signal rule. The AI
picker has read-only access to the normal terminal-information directories.

All managed top-level policy files are compiled with the available parser in a
private include tree using `-Q -K -T`: no profiles are loaded into the running
kernel. Required managed includes and their installer staging references are
checked, including the conditional hardware-tuning bridges. Explicit named
transitions resolve to managed profiles or the existing vendor-owned Chromium,
Microsoft Edge and Mullvad Browser attachments.

## Regression checks and acceptance boundary

`test_menu_apparmor_integration_20260919.py` tests the 23 management route vectors,
all 42 maintenance and 21 recovery menu dispatches against the actual client
request validators, picker error/cancellation behavior, confirmations, strict
catalog validation, temporary-file cleanup, fzf environment isolation, exact
selection, wrapper child lifecycle and offline AppArmor compilation. UI and
privileged action endpoints are controlled fixtures; no destructive action is
executed. Existing menu, security transaction, Perl-method and isolation tests
remain in place.

Run the normal `make build`, `make check`, `make test`, `make audit` and
`make validate` entry points. The release report under
`validation/menu-apparmor-20260919/` records actual results and baseline-only
exceptions. Offline compilation and fixtures do not replace target acceptance
with a live Wayland terminal, actual fzf/Fuzzel binaries, authorization agents,
physical devices and kernel AppArmor enforcement.
