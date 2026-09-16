# Computer Management action and selector ledger

Literal action calls, backend contracts, and source-indexed dispatch/selector branches. Dynamic selectors, aliases, confirmation branches and shared actions are preserved; counts are not end-to-end test counts. Missing profile locations are explicit; primary profiles are not an exhaustive child-policy closure.

All source paths are relative to the archive root. A backend reference means the literal ID occurs in that source; it is not proof that a particular runtime branch executed. Read REVIEW.md for test results and deployment gates.

## Container Management

**Menu source(s):** `d-i/forky/hooks/target/usr/local/bin/labwc-podman-menu`

**Primary policy definitions:** `managed-labwc-podman-menu`, `managed-podman-client`


**Dispatch and parameter-selector branches (not independent test results):**

`d-i/forky/hooks/target/usr/local/bin/labwc-podman-menu:146`
```text
action in ('Start', 'Stop', 'Restart', 'Pause', 'Unpause') -> args = [action.lower()]; if action in ('Stop', 'Restart'):; execute([PODMAN, *args, ident], 60); message(f'{action} succeeded: {ident[:12]}')
```
`d-i/forky/hooks/target/usr/local/bin/labwc-podman-menu:189`
```text
action == 'Inspect' -> terminal('podman', kind, 'inspect', ident)
```
`d-i/forky/hooks/target/usr/local/bin/labwc-podman-menu:214`
```text
action == 'Pull image' -> image = image_name('Qualified image'); if image:
```
`d-i/forky/hooks/target/usr/local/bin/labwc-podman-menu:148`
```text
action in ('Stop', 'Restart') -> args += ['--time', '20']
```
`d-i/forky/hooks/target/usr/local/bin/labwc-podman-menu:152`
```text
action == 'Logs' -> terminal('podman', 'logs', '--tail', '200', '--follow', ident)
```
`d-i/forky/hooks/target/usr/local/bin/labwc-podman-menu:170`
```text
kind == 'image' -> ident = identifier(item); tags = value(item, 'RepoTags', value(item, 'Names', [])) or ['<untagged>']; if isinstance(tags, str):; label = text(', '.join(tags)) + ' | ' + ident[:12]
```
`d-i/forky/hooks/target/usr/local/bin/labwc-podman-menu:218`
```text
action == 'Run image' -> image = image_name('Qualified image'); name = entry('Container name') if image else None; if image and name:
```
`d-i/forky/hooks/target/usr/local/bin/labwc-podman-menu:154`
```text
action == 'Inspect' -> terminal('podman', 'inspect', ident)
```
`d-i/forky/hooks/target/usr/local/bin/labwc-podman-menu:226`
```text
action == 'Build image' -> context = entry('Build context directory'); if context:
```
`d-i/forky/hooks/target/usr/local/bin/labwc-podman-menu:311`
```text
action in (None, 'Close') -> return 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-podman-menu:156`
```text
action == 'Stats' -> terminal('podman', 'stats', ident)
```
`d-i/forky/hooks/target/usr/local/bin/labwc-podman-menu:235`
```text
action == 'Deploy Compose' -> filename = entry('Compose file (shared bind mounts belong in /pool/podman/workspace)'); if filename:
```
`d-i/forky/hooks/target/usr/local/bin/labwc-podman-menu:314`
```text
action == 'Containers' -> container_menu()
```
`d-i/forky/hooks/target/usr/local/bin/labwc-podman-menu:158`
```text
action == 'Shell' -> terminal('podman', 'exec', '-it', ident, '/bin/sh')
```
`d-i/forky/hooks/target/usr/local/bin/labwc-podman-menu:316`
```text
action in ('Images', 'Volumes', 'Networks') -> object_menu(action[:-1].lower())
```
`d-i/forky/hooks/target/usr/local/bin/labwc-podman-menu:318`
```text
action in ('Pull image', 'Run image', 'Build image', 'Deploy Compose') -> interactive_action(action)
```
`d-i/forky/hooks/target/usr/local/bin/labwc-podman-menu:322`
```text
action == 'Engine info' -> terminal('podman', 'info')
```
`d-i/forky/hooks/target/usr/local/bin/labwc-podman-menu:324`
```text
action == 'Disk usage' -> terminal('podman', 'system', 'df')
```
`d-i/forky/hooks/target/usr/local/bin/labwc-podman-menu:326`
```text
action == 'Events' -> terminal('podman', 'events')
```

## Remote Desktop

**Menu source(s):** `d-i/forky/hooks/target/usr/local/bin/labwc-remote-desktop`

**Primary policy definitions:** `managed-labwc-remote-desktop`, `managed-labwc-generic-app`


**Dispatch and parameter-selector branches (not independent test results):**

`d-i/forky/hooks/target/usr/local/bin/labwc-remote-desktop:1004`
```text
action == 'Connect to Target (Direct)' -> connect_temporary(False)
```
`d-i/forky/hooks/target/usr/local/bin/labwc-remote-desktop:1006`
```text
action == 'Connect to Target (Shared)' -> connect_temporary(True)
```
`d-i/forky/hooks/target/usr/local/bin/labwc-remote-desktop:1008`
```text
action == 'Select Saved Connection' -> connect_saved()
```
`d-i/forky/hooks/target/usr/local/bin/labwc-remote-desktop:1010`
```text
action == 'Save Connection (Direct)' -> save_connection(False)
```
`d-i/forky/hooks/target/usr/local/bin/labwc-remote-desktop:1012`
```text
action == 'Save Connection (Shared)' -> save_connection(True)
```
`d-i/forky/hooks/target/usr/local/bin/labwc-remote-desktop:1014`
```text
action == 'Edit Saved Connection' -> edit_connection()
```
`d-i/forky/hooks/target/usr/local/bin/labwc-remote-desktop:1016`
```text
action == 'Delete Saved Connection' -> delete_connection()
```
`d-i/forky/hooks/target/usr/local/bin/labwc-remote-desktop:1018`
```text
action == 'Open Saved Connections Folder' -> open_profile_directory()
```
`d-i/forky/hooks/target/usr/local/bin/labwc-remote-desktop:1020`
```text
action == 'Show FreeRDP Help' -> show_help()
```

## Endpoint Security

**Menu source(s):** `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu`, `d-i/forky/hooks/target/usr/local/bin/labwc-firewall-menu`

**Primary policy definitions:** `managed-labwc-security-action`, `managed-labwc-security-action-root`, `managed-labwc-firewall-action`, `managed-labwc-firewall-action-root`, `managed-labwc-apparmor-policy-worker`, `managed-labwc-apparmor-boot-state`

- `audit-security-posture` via `run_security_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:289`.
- `analyze-services` via `run_security_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:292`.
- `inspect-service` via `run_security_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:296`.
- `check-firmware-security` via `run_security_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:299`.
- `check-cpu-mitigations` via `run_security_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:302`.
- `scan-rootkits-rkhunter` via `run_security_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:327`.
- `scan-rootkits-chkrootkit` via `run_security_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:330`.
- `show-clamav-signature-status` via `run_security_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:333`.
- `scan-file-clamav` via `run_security_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:338`.
- `scan-folder-clamav` via `run_security_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:343`.
- `update-clamav-signatures` via `run_security_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:346`.
- `check-known-vulnerabilities` via `run_security_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:370`.
- `check-package-integrity` via `run_security_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:373`.
- `retrieve-file-hashes` via `run_security_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:378`.
- `create-folder-hash-manifest` via `run_security_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:383`.
- `verify-file-sha256` via `run_security_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:394`.
- `set-apparmor-application-mode` via `run_security_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:526`.
- `set-apparmor-desktop-state` via `run_security_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:549`.
- `set-apparmor-boot-state` via `run_security_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:568`.
- `set-apparmor-application-audit` via `run_security_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:596`.
- `generate-apparmor-rules` via `run_security_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:613`.
- `apparmor-status` via `run_security_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:634`.
- `apparmor-enabled` via `run_security_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:637`.
- `apparmor-unconfined` via `run_security_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:640`.
- `apparmor-features-abi` via `run_security_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:643`.
- `audit-apparmor-complain` via `run_security_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:646`.
- `audit-apparmor-denied` via `run_security_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:649`.
- `apparmor-list-drafts` via `run_security_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:704`.
- `apparmor-validate-drafts` via `run_security_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:707`.
- `apparmor-activate-draft` via `run_security_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:734`.
- `apparmor-managed-application-modes` via `run_security_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:766`.
- `enforce` via `set_all_apparmor_desktop_profiles_mode` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:772`.
- `complain` via `set_all_apparmor_desktop_profiles_mode` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:775`.
- `disable` via `set_apparmor_boot_state` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:778`.
- `enable` via `set_apparmor_boot_state` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:781`.
- `reload-apparmor-managed-modes` via `run_security_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:797`.
- `apparmor-list-disabled-profiles` via `run_security_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:821`.
- `aa-remove-unknown-dry-run` via `run_security_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:824`.
- `reload-apparmor-service` via `run_security_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:834`.
- `add-rule` via `run_firewall_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-firewall-menu:108`.
- `status` via `run_firewall_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-firewall-menu:213`.
- `remove-rule` via `run_firewall_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-firewall-menu:220`.
- `reset-rules` via `run_firewall_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-firewall-menu:228`.

**Dispatch and parameter-selector branches (not independent test results):**

`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:288`
```text
'Audit Security Posture (lynis)' -> run_security_action audit-security-posture
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:291`
```text
'Service Security Analysis' -> run_security_action analyze-services
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:294`
```text
'Inspect Specific Service' -> service=$(choose_service) [ -n "$service" ] && run_security_action inspect-service "$service"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:298`
```text
'Check Firmware Security' -> run_security_action check-firmware-security
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:301`
```text
'Check CPU Mitigations' -> run_security_action check-cpu-mitigations
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:326`
```text
'Run Rootkit Scan (rkhunter)' -> run_security_action scan-rootkits-rkhunter
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:329`
```text
'Run Rootkit Scan (chkrootkit)' -> run_security_action scan-rootkits-chkrootkit
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:332`
```text
'Show ClamAV Signature Status' -> run_security_action show-clamav-signature-status
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:335`
```text
'Scan File with ClamAV' -> scan_file=$(choose_security_file "ClamAV file path") [ -n "$scan_file" ] && run_security_action scan-file-clamav "$scan_file"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:340`
```text
'Scan Folder Recursively with ClamAV' -> scan_folder=$(choose_security_folder "ClamAV folder path") [ -n "$scan_folder" ] && run_security_action scan-folder-clamav "$scan_folder"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:345`
```text
'Update ClamAV Signatures' -> run_security_action update-clamav-signatures
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:369`
```text
'Check Known Vulnerabilities' -> run_security_action check-known-vulnerabilities
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:372`
```text
'Check Package Integrity' -> run_security_action check-package-integrity
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:375`
```text
'Retrieve File Hashsums (SHA-256/SHA-512)' -> hash_file=$(choose_security_file "File path for SHA-256 and SHA-512") [ -n "$hash_file" ] && run_security_action retrieve-file-hashes "$hash_file"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:380`
```text
'Create Folder Tree SHA-256 Manifest' -> hash_folder=$(choose_security_folder "Folder path for SHA-256 manifest") [ -n "$hash_folder" ] && run_security_action create-folder-hash-manifest "$hash_folder"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:385`
```text
'Verify File Against SHA-256' -> verify_file=$(choose_security_file "File path to verify") if [ -n "$verify_file" ]; then expected_sha256=$( choose_lines \ "Expected SHA-256 (64 hexadecimal characters)" \ 'Paste or type the expected SHA-256 digest' ) [ -n "$expected_sha256" ] && run_security_action verify-file-sha256 "$verify_file" "$expected_sha256" fi
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:633`
```text
'AppArmor Status' -> run_security_action apparmor-status
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:636`
```text
'Kernel Enablement' -> run_security_action apparmor-enabled
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:639`
```text
'Unconfined Network Processes' -> run_security_action apparmor-unconfined
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:642`
```text
'Features ABI' -> run_security_action apparmor-features-abi
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:645`
```text
'Complain Events (24h)' -> run_security_action audit-apparmor-complain
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:648`
```text
'Denied Events (24h)' -> run_security_action audit-apparmor-denied
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:703`
```text
'List Drafts' -> run_security_action apparmor-list-drafts
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:706`
```text
'Validate Drafts' -> run_security_action apparmor-validate-drafts
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:765`
```text
'Show App Modes' -> run_security_action apparmor-managed-application-modes
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:771`
```text
'Enforce All' -> set_all_apparmor_desktop_profiles_mode enforce
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:774`
```text
'Complain All' -> set_all_apparmor_desktop_profiles_mode complain
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:777`
```text
'Disable AppArmor After Reboot' -> set_apparmor_boot_state disable
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:780`
```text
'Enable AppArmor After Reboot' -> set_apparmor_boot_state enable
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:789`
```text
'Reload Modes & Clear Audit' -> confirmation=$( choose_lines \ "Reload modes and clear temporary audit flags" \ 'Cancel' \ 'Continue with AppArmor reload' ) [ "$confirmation" = 'Continue with AppArmor reload' ] && run_security_action \ reload-apparmor-managed-modes \ confirmed-apparmor-reload
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:820`
```text
'Disabled Profiles' -> run_security_action apparmor-list-disabled-profiles
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:823`
```text
'Preview Unknown Cleanup' -> run_security_action aa-remove-unknown-dry-run
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:826`
```text
'Reload AppArmor Service' -> confirmation=$( choose_lines \ "Reload every installed AppArmor profile" \ 'Cancel' \ 'Continue with AppArmor service reload' ) [ "$confirmation" = 'Continue with AppArmor service reload' ] && run_security_action \ reload-apparmor-service \ confirmed-apparmor-service-reload
```
`d-i/forky/hooks/target/usr/local/bin/labwc-firewall-menu:135`
```text
'Allow Incoming Port from Any Source' -> add_rule incoming allow any
```
`d-i/forky/hooks/target/usr/local/bin/labwc-firewall-menu:138`
```text
'Allow Incoming Port from LAN' -> add_rule incoming allow lan
```
`d-i/forky/hooks/target/usr/local/bin/labwc-firewall-menu:141`
```text
'Allow Incoming Port from IP/CIDR' -> add_rule incoming allow ip
```
`d-i/forky/hooks/target/usr/local/bin/labwc-firewall-menu:144`
```text
'Block Incoming Port from Any Source' -> add_rule incoming block any
```
`d-i/forky/hooks/target/usr/local/bin/labwc-firewall-menu:147`
```text
'Block Incoming Port from LAN' -> add_rule incoming block lan
```
`d-i/forky/hooks/target/usr/local/bin/labwc-firewall-menu:150`
```text
'Block Incoming Port from IP/CIDR' -> add_rule incoming block ip
```
`d-i/forky/hooks/target/usr/local/bin/labwc-firewall-menu:153`
```text
'← Back'|'' -> return 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-firewall-menu:175`
```text
'Allow Outgoing Port to Any Destination' -> add_rule outgoing allow any
```
`d-i/forky/hooks/target/usr/local/bin/labwc-firewall-menu:178`
```text
'Allow Outgoing Port to LAN' -> add_rule outgoing allow lan
```
`d-i/forky/hooks/target/usr/local/bin/labwc-firewall-menu:181`
```text
'Allow Outgoing Port to IP/CIDR' -> add_rule outgoing allow ip
```
`d-i/forky/hooks/target/usr/local/bin/labwc-firewall-menu:184`
```text
'Block Outgoing Port to Any Destination' -> add_rule outgoing block any
```
`d-i/forky/hooks/target/usr/local/bin/labwc-firewall-menu:187`
```text
'Block Outgoing Port to LAN' -> add_rule outgoing block lan
```
`d-i/forky/hooks/target/usr/local/bin/labwc-firewall-menu:190`
```text
'Block Outgoing Port to IP/CIDR' -> add_rule outgoing block ip
```
`d-i/forky/hooks/target/usr/local/bin/labwc-firewall-menu:193`
```text
'← Back'|'' -> return 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-firewall-menu:212`
```text
'Show Firewall Status' -> run_firewall_action status
```
`d-i/forky/hooks/target/usr/local/bin/labwc-firewall-menu:215`
```text
'Remove Managed Firewall Rule' -> selection=$(choose_rule) rule_id=${selection%% *} if [ -n "$rule_id" ] && confirm_firewall_change "Remove ${rule_id}"; then run_firewall_action \ remove-rule \ "$rule_id" \ confirmed-firewall-action fi
```
`d-i/forky/hooks/target/usr/local/bin/labwc-firewall-menu:226`
```text
'Reset Managed Firewall Rules' -> if confirm_firewall_change "Remove every managed firewall rule"; then run_firewall_action reset-rules confirmed-firewall-action fi
```
`d-i/forky/hooks/target/usr/local/bin/labwc-firewall-menu:231`
```text
'← Back'|'' -> return 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-firewall-menu:258`
```text
'⮞ Status & Managed Rules' -> managed_rules_menu
```
`d-i/forky/hooks/target/usr/local/bin/labwc-firewall-menu:261`
```text
'⮞ Incoming Traffic' -> incoming_traffic_menu
```
`d-i/forky/hooks/target/usr/local/bin/labwc-firewall-menu:264`
```text
'⮞ Outgoing Traffic' -> outgoing_traffic_menu
```
`d-i/forky/hooks/target/usr/local/bin/labwc-firewall-menu:267`
```text
'← Back'|'' -> exit 0
```

## Digital Assets

**Menu source(s):** `d-i/forky/hooks/target/usr/local/bin/labwc-digital-assets`

**Primary policy definitions:** `managed-labwc-digital-assets`, `managed-labwc-digital-assets-action`, `managed-digital-assets-release-tools`, `managed-digital-assets-python-runtime`

- `docx-to-pdf` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:13`.
- `docx-to-markdown` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:20`.
- `docx-to-text` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:27`.
- `docx-to-html` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:34`.
- `docx-read-metadata` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:41`.
- `docx-edit-metadata` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:48`.
- `docx-remove-metadata` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:55`.
- `pdf-to-png` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:62`.
- `pdf-to-jpeg` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:69`.
- `pdf-to-docx` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:76`.
- `pdf-to-text` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:83`.
- `markdown-to-pdf` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:90`.
- `pdf-extract-images` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:97`.
- `pdf-merge` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:104`.
- `pdf-burst` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:111`.
- `pdf-extract-pages` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:118`.
- `pdf-remove-pages` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:125`.
- `pdf-rotate-pages` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:132`.
- `pdf-edit-content` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:139`.
- `pdf-edit-bookmarks` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:146`.
- `pdf-edit-qdf` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:153`.
- `pdf-repair` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:160`.
- `pdf-inspect` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:167`.
- `pdf-encrypt` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:174`.
- `pdf-decrypt` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:181`.
- `pdf-linearize` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:188`.
- `pdf-add-page-numbers` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:195`.
- `pdf-add-watermark` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:202`.
- `pdf-extract-bookmarks` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:209`.
- `pdf-read-metadata` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:216`.
- `pdf-edit-metadata` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:223`.
- `pdf-remove-metadata` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:230`.
- `image-to-png` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:237`.
- `image-to-jpeg` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:244`.
- `image-to-webp` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:251`.
- `image-resize` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:258`.
- `image-crop` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:265`.
- `image-rotate` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:272`.
- `image-flop` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:279`.
- `image-flip` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:286`.
- `image-grayscale` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:293`.
- `image-optimize-png` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:300`.
- `image-optimize-jpeg` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:307`.
- `image-create-gif` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:314`.
- `image-read-metadata` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:321`.
- `image-edit-metadata` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:328`.
- `image-remove-metadata` via `DigitalAssets::Catalog` at `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets/Catalog.pm:335`.

**Dispatch and parameter-selector branches (not independent test results):**

`d-i/forky/hooks/target/usr/local/bin/labwc-digital-assets:249`
```text
'Finish selection' -> break
```
`d-i/forky/hooks/target/usr/local/bin/labwc-digital-assets:252`
```text
'Cancel'|'' -> rm -f -- "$list_path" rm -f -- "$candidate_path" return 1
```
`d-i/forky/hooks/target/usr/local/bin/labwc-digital-assets:395`
```text
'← Back'|'' -> return 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-digital-assets:428`
```text
'DOCX Actions' -> category_menu docx 'DOCX Actions'
```
`d-i/forky/hooks/target/usr/local/bin/labwc-digital-assets:429`
```text
'PDF Actions' -> category_menu pdf 'PDF Actions'
```
`d-i/forky/hooks/target/usr/local/bin/labwc-digital-assets:430`
```text
'Image Actions' -> category_menu image 'Image Actions'
```
`d-i/forky/hooks/target/usr/local/bin/labwc-digital-assets:431`
```text
'← Back'|'' -> exit 0
```

## Users & Groups

**Menu source(s):** `d-i/forky/hooks/target/usr/local/bin/labwc-users-groups-menu`

**Primary policy definitions:** `managed-labwc-users-groups-menu`, `managed-labwc-security-action`, `managed-labwc-security-action-root`

- `list-users` via `run_account_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-users-groups-menu:58`.
- `list-non-sudo-users` via `run_account_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-users-groups-menu:61`.
- `list-groups` via `run_account_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-users-groups-menu:64`.
- `list-sudo-administrators` via `run_account_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-users-groups-menu:67`.
- `list-passwordless-accounts` via `run_account_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-users-groups-menu:70`.
- `audit-sudo-access` via `run_account_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-users-groups-menu:73`.

**Dispatch and parameter-selector branches (not independent test results):**

`d-i/forky/hooks/target/usr/local/bin/labwc-users-groups-menu:57`
```text
'List User Accounts' -> run_account_action list-users
```
`d-i/forky/hooks/target/usr/local/bin/labwc-users-groups-menu:60`
```text
'List Non-Sudo Users' -> run_account_action list-non-sudo-users
```
`d-i/forky/hooks/target/usr/local/bin/labwc-users-groups-menu:63`
```text
'List Groups' -> run_account_action list-groups
```
`d-i/forky/hooks/target/usr/local/bin/labwc-users-groups-menu:66`
```text
'List Sudo Administrators' -> run_account_action list-sudo-administrators
```
`d-i/forky/hooks/target/usr/local/bin/labwc-users-groups-menu:69`
```text
'List Accounts Without Password' -> run_account_action list-passwordless-accounts
```
`d-i/forky/hooks/target/usr/local/bin/labwc-users-groups-menu:72`
```text
'Audit Sudo Access' -> run_account_action audit-sudo-access
```
`d-i/forky/hooks/target/usr/local/bin/labwc-users-groups-menu:75`
```text
'← Back'|'' -> exit 0
```

## Network Management

**Menu source(s):** `d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu`, `d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu`

**Primary policy definitions:** `managed-labwc-network-control-action`, `managed-labwc-network-control-action-root`, `managed-labwc-network-scan-action`, `managed-labwc-network-scan-action-root`

**Direct category dispatch:**
`d-i/forky/hooks/target/usr/local/bin/labwc-computer-management:224`
```sh
network_management_menu() {
  while :; do
    action=$(
      choose_lines \
        "Network Management" \
        "⮞ Network Scanning" \
        "⮞ Connection Profiles" \
        "⮞ VPN Connections" \
        "⮞ WireGuard Connections" \
        "⮞ DNS Configuration" \
        "← Back"
    )

    case "$action" in
      "⮞ Network Scanning")
        run_command labwc-network-scan-menu
        ;;
      "⮞ Connection Profiles")
        run_command labwc-network-control-menu connections
        ;;
      "⮞ VPN Connections")
        run_command labwc-network-control-menu vpn
        ;;
      "⮞ WireGuard Connections")
        run_command labwc-network-control-menu wireguard
        ;;
      "⮞ DNS Configuration")
        run_command labwc-network-control-menu dns
        ;;
      "← Back")
        return 0
        ;;
      '')
        return 0
        ;;
    esac
  done
}
```

- `activate-connection` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu:225`.
- `deactivate-connection` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu:231`.
- `enable-ethernet` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu:236`.
- `disable-ethernet` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu:241`.
- `enable-wifi` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu:246`.
- `disable-wifi` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu:251`.
- `randomize-macs` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu:255`.
- `activate-vpn` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu:281`.
- `deactivate-vpn` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu:287`.
- `import-openvpn` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu:293`.
- `activate-wireguard` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu:322`.
- `deactivate-wireguard` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu:328`.
- `import-wireguard` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu:334`.
- `show-dns-status` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu:361`.
- `restore-automatic-dns` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu:368`.
- `set-custom-dns` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu:381`.
- `flush-dns-cache` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu:391`.
- `nmap-common-ports` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:136`.
- `show-listening-ports` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:198`.
- `nmap-full-tcp` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:201`.
- `nmap-common-ports` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:206`.
- `nmap-full-tcp` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:211`.
- `nmap-discovery` via `run_selected_nmap_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:217`.
- `nmap-inventory` via `run_selected_nmap_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:220`.
- `nmap-approved-services` via `run_selected_nmap_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:223`.
- `nmap-tls-settings` via `run_selected_nmap_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:226`.
- `nmap-http-headers` via `run_selected_nmap_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:229`.
- `nmap-compliance` via `run_selected_nmap_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:232`.
- `nmap-ssh-settings` via `run_selected_nmap_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:235`.
- `nmap-smb-settings` via `run_selected_nmap_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:238`.
- `nmap-dns-settings` via `run_selected_nmap_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:241`.
- `nmap-common-ports` via `run_selected_nmap_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:244`.
- `nmap-full-tcp` via `run_selected_nmap_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:247`.
- `wireshark-launch` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:269`.
- `wireshark-open-capture` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:274`.
- `dumpcap-list-interfaces` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:300`.
- `dumpcap-capture-general` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:304`.
- `dumpcap-capture-dns` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:308`.
- `dumpcap-capture-dhcp` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:312`.
- `dumpcap-capture-tls` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:316`.
- `dumpcap-capture-discovery` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:320`.
- `tcpdump-list-interfaces` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:348`.
- `tcpdump-capture-general` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:352`.
- `tcpdump-capture-dns` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:356`.
- `tcpdump-capture-dhcp` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:360`.
- `tcpdump-capture-icmp` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:364`.
- `tcpdump-capture-arp` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:368`.
- `tcpdump-capture-syn` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:372`.
- `tcpdump-print-summary` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:376`.
- `tshark-live-endpoints` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:406`.
- `tshark-live-dns` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:410`.
- `tshark-live-tls` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:414`.
- `tshark-live-retransmissions` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:418`.
- `tshark-file-protocols` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:422`.
- `tshark-file-conversations` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:426`.
- `tshark-file-dns` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:430`.
- `tshark-file-tls` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:434`.
- `tshark-file-http-errors` via `run_network_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:438`.

**Dispatch and parameter-selector branches (not independent test results):**

`d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu:221`
```text
'Activate Saved Connection' -> selection=$(choose_connection all saved) connection_uuid=$(connection_uuid_from_selection "$selection" || true) [ -n "$connection_uuid" ] && run_network_action activate-connection "$connection_uuid"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu:227`
```text
'Deactivate Active Connection' -> selection=$(choose_connection all active) connection_uuid=$(connection_uuid_from_selection "$selection" || true) [ -n "$connection_uuid" ] && run_network_action deactivate-connection "$connection_uuid"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu:233`
```text
'Enable Ethernet Adapter' -> ethernet_adapter=$(choose_adapter ethernet) [ -n "$ethernet_adapter" ] && run_network_action enable-ethernet "$ethernet_adapter"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu:238`
```text
'Disable Ethernet Adapter' -> ethernet_adapter=$(choose_adapter ethernet) [ -n "$ethernet_adapter" ] && run_network_action disable-ethernet "$ethernet_adapter"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu:243`
```text
'Enable WiFi Adapter' -> wifi_adapter=$(choose_adapter wifi) [ -n "$wifi_adapter" ] && run_network_action enable-wifi "$wifi_adapter"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu:248`
```text
'Disable WiFi Adapter' -> wifi_adapter=$(choose_adapter wifi) [ -n "$wifi_adapter" ] && run_network_action disable-wifi "$wifi_adapter"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu:253`
```text
'Generate Random MAC Addresses' -> if confirm_action "Randomize saved physical network profiles"; then run_network_action randomize-macs confirmed-network-action fi
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu:258`
```text
'← Back'|'' -> return 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu:277`
```text
'Activate VPN Connection' -> selection=$(choose_connection vpn saved) connection_uuid=$(connection_uuid_from_selection "$selection" || true) [ -n "$connection_uuid" ] && run_network_action activate-vpn "$connection_uuid"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu:283`
```text
'Deactivate VPN Connection' -> selection=$(choose_connection vpn active) connection_uuid=$(connection_uuid_from_selection "$selection" || true) [ -n "$connection_uuid" ] && run_network_action deactivate-vpn "$connection_uuid"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu:289`
```text
'Import OpenVPN Profile' -> profile_path=$(choose_import_file openvpn) if [ -n "$profile_path" ] && confirm_action "Import selected OpenVPN profile"; then run_network_action \ import-openvpn \ "$profile_path" \ confirmed-network-action fi
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu:299`
```text
'← Back'|'' -> return 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu:318`
```text
'Activate WireGuard Connection' -> selection=$(choose_connection wireguard saved) connection_uuid=$(connection_uuid_from_selection "$selection" || true) [ -n "$connection_uuid" ] && run_network_action activate-wireguard "$connection_uuid"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu:324`
```text
'Deactivate WireGuard Connection' -> selection=$(choose_connection wireguard active) connection_uuid=$(connection_uuid_from_selection "$selection" || true) [ -n "$connection_uuid" ] && run_network_action deactivate-wireguard "$connection_uuid"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu:330`
```text
'Import WireGuard Profile' -> profile_path=$(choose_import_file wireguard) if [ -n "$profile_path" ] && confirm_action "Import selected WireGuard profile"; then run_network_action \ import-wireguard \ "$profile_path" \ confirmed-network-action fi
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu:340`
```text
'← Back'|'' -> return 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu:360`
```text
'Show DNS Status' -> run_network_action show-dns-status
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu:363`
```text
'Restore Automatic DNS' -> selection=$(choose_connection all saved) connection_uuid=$(connection_uuid_from_selection "$selection" || true) if [ -n "$connection_uuid" ] && confirm_action "Restore automatic DNS for selected connection"; then run_network_action \ restore-automatic-dns \ "$connection_uuid" \ confirmed-network-action fi
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu:374`
```text
'Set Custom DNS Servers' -> selection=$(choose_connection all saved) connection_uuid=$(connection_uuid_from_selection "$selection" || true) if [ -n "$connection_uuid" ]; then dns_servers=$(choose_text "DNS IPs separated by spaces or commas") if [ -n "$dns_servers" ] && confirm_action "Apply custom DNS to selected connection"; then run_network_action \ set-custom-dns \ "$connection_uuid" \ "$dns_servers" \ confirmed-network-action fi fi
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu:389`
```text
'Flush DNS Cache' -> if confirm_action "Flush managed DNS caches"; then run_network_action flush-dns-cache confirmed-network-action fi
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu:394`
```text
'← Back'|'' -> return 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu:413`
```text
'⮞ Connection Profiles' -> connection_profiles_menu
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu:414`
```text
'⮞ VPN Connections' -> vpn_menu
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu:415`
```text
'⮞ WireGuard Connections' -> wireguard_menu
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu:416`
```text
'⮞ DNS Configuration' -> dns_menu
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-control-menu:417`
```text
'← Back'|'' -> return 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:92`
```text
'Private or loopback target' -> case "$target_kind" in host) target=$(choose_private_host)
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:101`
```text
'Authorized WAN IPv4 host' -> confirmation=$( choose_lines \ "WAN scan authorization" \ 'Cancel' \ 'I am authorized to scan this WAN host' ) [ "$confirmation" = 'I am authorized to scan this WAN host' ] || return 0 target=$( choose_lines \ "Authorized public IPv4 address" \ 'Enter an authorized public IPv4 address' ) [ -n "$target" ] && run_network_action "$nmap_action" "$target" authorized-wan-scan
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:173`
```text
'⮞ Nmap' -> while :; do action=$( choose_lines \ Nmap \ 'Show Listening TCP/UDP Ports' \ 'Scan Localhost TCP Ports' \ 'Scan LAN TCP Ports' \ 'Scan Specific LAN IP' \ 'Scan Specific WAN IP' \ 'Discover Hosts' \ 'Inventory Your Network' \ 'Check Approved Services' \ 'Check TLS Settings' \ 'Check HTTP Security Headers' \ 'Run Compliance Checks' \ 'Check SSH Algorithms' \ 'Check SMB Security' \ 'Check DNS Service' \ 'Check Common Ports' \ 'Scan All TCP Ports (single host)' \ '← Back' ) case "$action" in 'Show Listening TCP/UDP Ports') run_network_action show-listening-ports
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:200`
```text
'Scan Localhost TCP Ports' -> run_network_action nmap-full-tcp 127.0.0.1 private-scan
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:203`
```text
'Scan LAN TCP Ports' -> target=$(choose_private_target) [ -n "$target" ] && run_network_action nmap-common-ports "$target" private-scan
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:208`
```text
'Scan Specific LAN IP' -> target=$(choose_private_host) [ -n "$target" ] && run_network_action nmap-full-tcp "$target" private-scan
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:213`
```text
'Scan Specific WAN IP' -> run_specific_wan_scan
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:216`
```text
'Discover Hosts' -> run_selected_nmap_action nmap-discovery
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:219`
```text
'Inventory Your Network' -> run_selected_nmap_action nmap-inventory
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:222`
```text
'Check Approved Services' -> run_selected_nmap_action nmap-approved-services
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:225`
```text
'Check TLS Settings' -> run_selected_nmap_action nmap-tls-settings
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:228`
```text
'Check HTTP Security Headers' -> run_selected_nmap_action nmap-http-headers
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:231`
```text
'Run Compliance Checks' -> run_selected_nmap_action nmap-compliance
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:234`
```text
'Check SSH Algorithms' -> run_selected_nmap_action nmap-ssh-settings
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:237`
```text
'Check SMB Security' -> run_selected_nmap_action nmap-smb-settings
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:240`
```text
'Check DNS Service' -> run_selected_nmap_action nmap-dns-settings
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:243`
```text
'Check Common Ports' -> run_selected_nmap_action nmap-common-ports
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:246`
```text
'Scan All TCP Ports (single host)' -> run_selected_nmap_action nmap-full-tcp host
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:249`
```text
'← Back' -> break
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:252`
```text
'' -> exit 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:258`
```text
'⮞ Wireshark' -> while :; do action=$( choose_lines \ Wireshark \ 'Launch Wireshark' \ 'Open Managed Capture' \ '← Back' ) case "$action" in 'Launch Wireshark') run_network_action wireshark-launch
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:271`
```text
'Open Managed Capture' -> capture_file=$(choose_capture_file) [ -n "$capture_file" ] && run_network_action wireshark-open-capture "$capture_file"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:276`
```text
'← Back' -> break
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:279`
```text
'' -> exit 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:285`
```text
'⮞ Dumpcap' -> while :; do action=$( choose_lines \ Dumpcap \ 'List Capture Interfaces' \ 'Capture General Traffic (60s)' \ 'Capture DNS Traffic (60s)' \ 'Capture DHCP Traffic (60s)' \ 'Capture TLS Traffic (60s)' \ 'Capture Discovery Traffic (60s)' \ '← Back' ) case "$action" in 'List Capture Interfaces') run_network_action dumpcap-list-interfaces
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:302`
```text
'Capture General Traffic (60s)' -> interface=$(choose_interface) [ -n "$interface" ] && run_network_action dumpcap-capture-general "$interface"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:306`
```text
'Capture DNS Traffic (60s)' -> interface=$(choose_interface) [ -n "$interface" ] && run_network_action dumpcap-capture-dns "$interface"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:310`
```text
'Capture DHCP Traffic (60s)' -> interface=$(choose_interface) [ -n "$interface" ] && run_network_action dumpcap-capture-dhcp "$interface"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:314`
```text
'Capture TLS Traffic (60s)' -> interface=$(choose_interface) [ -n "$interface" ] && run_network_action dumpcap-capture-tls "$interface"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:318`
```text
'Capture Discovery Traffic (60s)' -> interface=$(choose_interface) [ -n "$interface" ] && run_network_action dumpcap-capture-discovery "$interface"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:322`
```text
'← Back' -> break
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:325`
```text
'' -> exit 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:331`
```text
'⮞ Tcpdump' -> while :; do action=$( choose_lines \ Tcpdump \ 'List Capture Interfaces' \ 'Capture General Traffic (60s)' \ 'Capture DNS Traffic (60s)' \ 'Capture DHCP Traffic (60s)' \ 'Capture ICMP Traffic (60s)' \ 'Capture ARP Traffic (60s)' \ 'Capture TCP SYN Traffic (60s)' \ 'Print Traffic Summary (30s)' \ '← Back' ) case "$action" in 'List Capture Interfaces') run_network_action tcpdump-list-interfaces
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:350`
```text
'Capture General Traffic (60s)' -> interface=$(choose_interface) [ -n "$interface" ] && run_network_action tcpdump-capture-general "$interface"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:354`
```text
'Capture DNS Traffic (60s)' -> interface=$(choose_interface) [ -n "$interface" ] && run_network_action tcpdump-capture-dns "$interface"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:358`
```text
'Capture DHCP Traffic (60s)' -> interface=$(choose_interface) [ -n "$interface" ] && run_network_action tcpdump-capture-dhcp "$interface"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:362`
```text
'Capture ICMP Traffic (60s)' -> interface=$(choose_interface) [ -n "$interface" ] && run_network_action tcpdump-capture-icmp "$interface"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:366`
```text
'Capture ARP Traffic (60s)' -> interface=$(choose_interface) [ -n "$interface" ] && run_network_action tcpdump-capture-arp "$interface"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:370`
```text
'Capture TCP SYN Traffic (60s)' -> interface=$(choose_interface) [ -n "$interface" ] && run_network_action tcpdump-capture-syn "$interface"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:374`
```text
'Print Traffic Summary (30s)' -> interface=$(choose_interface) [ -n "$interface" ] && run_network_action tcpdump-print-summary "$interface"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:378`
```text
'← Back' -> break
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:381`
```text
'' -> exit 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:387`
```text
'⮞ TShark' -> while :; do action=$( choose_lines \ TShark \ 'Show Live IP Endpoints (30s)' \ 'Show Live DNS Queries (30s)' \ 'Show Live TLS Server Names (30s)' \ 'Show TCP Retransmissions (30s)' \ 'Analyze Protocol Hierarchy' \ 'Analyze IP Conversations' \ 'Extract DNS Queries' \ 'Extract TLS Server Names' \ 'Show HTTP Error Responses' \ '← Back' ) case "$action" in 'Show Live IP Endpoints (30s)') interface=$(choose_interface) [ -n "$interface" ] && run_network_action tshark-live-endpoints "$interface"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:408`
```text
'Show Live DNS Queries (30s)' -> interface=$(choose_interface) [ -n "$interface" ] && run_network_action tshark-live-dns "$interface"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:412`
```text
'Show Live TLS Server Names (30s)' -> interface=$(choose_interface) [ -n "$interface" ] && run_network_action tshark-live-tls "$interface"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:416`
```text
'Show TCP Retransmissions (30s)' -> interface=$(choose_interface) [ -n "$interface" ] && run_network_action tshark-live-retransmissions "$interface"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:420`
```text
'Analyze Protocol Hierarchy' -> capture_file=$(choose_capture_file) [ -n "$capture_file" ] && run_network_action tshark-file-protocols "$capture_file"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:424`
```text
'Analyze IP Conversations' -> capture_file=$(choose_capture_file) [ -n "$capture_file" ] && run_network_action tshark-file-conversations "$capture_file"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:428`
```text
'Extract DNS Queries' -> capture_file=$(choose_capture_file) [ -n "$capture_file" ] && run_network_action tshark-file-dns "$capture_file"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:432`
```text
'Extract TLS Server Names' -> capture_file=$(choose_capture_file) [ -n "$capture_file" ] && run_network_action tshark-file-tls "$capture_file"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:436`
```text
'Show HTTP Error Responses' -> capture_file=$(choose_capture_file) [ -n "$capture_file" ] && run_network_action tshark-file-http-errors "$capture_file"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:440`
```text
'← Back' -> break
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:443`
```text
'' -> exit 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-network-scan-menu:449`
```text
'' -> exit 0
```

## System Configuration

**Menu source(s):** `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu`, `d-i/forky/hooks/target/usr/local/bin/labwc-display-configuration`, `d-i/forky/hooks/target/usr/local/bin/labwc-power-settings`, `d-i/forky/hooks/target/usr/local/bin/labwc-keyboard-layout`

**Primary policy definitions:** `managed-labwc-system-action`, `managed-labwc-system-action-root`, `managed-labwc-generic-app`

**Direct category dispatch:**
`d-i/forky/hooks/target/usr/local/bin/labwc-computer-management:263`
```sh
system_configuration_menu() {
  while :; do
    action=$(
      choose_lines \
        "System Configuration" \
        "⮞ System Maintenance & Diagnostics" \
        "Display Configuration" \
        "Refresh Display Layout" \
        "Power Profile" \
        "Keyboard Layout" \
        "Audio Control" \
        "Restart Dock" \
        "← Back"
    )

    case "$action" in
      "⮞ System Maintenance & Diagnostics")
        run_command labwc-maintenance-menu system
        ;;
      "Display Configuration")
        run_command labwc-display-configuration
        ;;
      "Refresh Display Layout")
        run_command /usr/local/libexec/labwc-output-watch --refresh
        ;;
      "Power Profile")
        run_command labwc-power-settings
        ;;
      "Keyboard Layout")
        run_command labwc-keyboard-layout
        ;;
      "Audio Control")
        run_command labwc-wayland-app auto -- /usr/bin/pavucontrol
        ;;
      "Restart Dock")
        run_command systemctl --user --no-block restart crystal-dock.service
        ;;
      "← Back")
        return 0
        ;;
      '')
        return 0
        ;;
    esac
  done
}
```

- `system-overview` via `run_system_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1001`.
- `failed-services` via `run_system_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1004`.
- `boot-performance` via `run_system_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1007`.
- `recent-errors` via `run_system_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1010`.
- `kernel-warnings` via `run_system_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1013`.
- `storage-overview` via `run_system_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1016`.
- `memory-overview` via `run_system_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1022`.
- `network-overview` via `run_system_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1025`.
- `package-health` via `run_system_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1028`.
- `pending-upgrades` via `run_system_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1031`.
- `inspect-service` via `run_system_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1035`.
- `firmware-devices` via `run_system_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1038`.
- `refresh-firmware-metadata` via `run_system_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1041`.
- `firmware-updates` via `run_system_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1044`.
- `apply-firmware-updates` via `run_confirmed_system_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1047`.
- `upgradeable-packages` via `run_system_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1052`.
- `run-unattended-upgrades` via `run_confirmed_system_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1055`.
- `nvme-smart-health` via `run_system_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1062`.
- `nvme-firmware-slots` via `run_system_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1067`.
- `nvme-identify-data` via `run_system_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1072`.
- `nvme-smartctl` via `run_system_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1077`.
- `btrfs-usage` via `run_system_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1080`.
- `btrfs-df` via `run_system_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1083`.
- `btrfs-scrub-status` via `run_system_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1086`.
- `journal-disk-usage` via `run_system_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1089`.
- `journal-vacuum-time` via `run_confirmed_system_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1094`.
- `journal-vacuum-size` via `run_confirmed_system_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1102`.
- `top-disk-root` via `run_system_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1108`.
- `top-disk-home` via `run_system_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1111`.
- `failed-system-units` via `run_system_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1114`.
- `failed-user-units` via `run_system_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1117`.
- `show-timers` via `run_system_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1120`.
- `pipewire-status` via `run_system_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1123`.
- `wireplumber-status` via `run_system_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1126`.
- `restart-pipewire` via `run_confirmed_system_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1129`.
- `restart-wireplumber` via `run_confirmed_system_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1132`.
- `flush-dns-cache` via `run_system_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1135`.
- `reset-resolver-features` via `run_system_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1138`.
- `resolver-statistics` via `run_system_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1141`.
- `test-mako-notification` via `run_system_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1144`.
- `refresh-waybar-custom-module` via `run_system_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1147`.

**Dispatch and parameter-selector branches (not independent test results):**

`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:949`
```text
'⮞ System' -> while :; do action=$( choose_lines \ System \ 'Show System Overview' \ 'Show Failed Services' \ 'Show Boot Performance' \ 'Show Recent System Errors' \ 'Show Kernel Warnings' \ 'Show Storage Overview' \ 'Manage External Drives' \ 'Show Memory and Swap' \ 'Show Network Overview' \ 'Check Package Health' \ 'List Pending Upgrades' \ 'Inspect Service and Logs' \ 'List Firmware-Capable Devices' \ 'Refresh Firmware Metadata' \ 'Check Firmware Updates' \ 'Apply Firmware Updates' \ 'Show Upgradeable Packages' \ 'Run Unattended Upgrades Now' \ 'Show NVMe SMART Health' \ 'Show NVMe Firmware Slots' \ 'Show NVMe Identify Data' \ 'Show NVMe SMART via smartctl' \ 'Show Btrfs Usage' \ 'Show Btrfs DF Summary' \ 'Show Last Btrfs Scrub Status' \ 'Show Journal Disk Usage' \ 'Rotate and Vacuum Journals by Time' \ 'Rotate and Vacuum Journals by Size' \ 'Top Disk Usage in Root' \ 'Top Disk Usage in Home' \ 'Show Failed System Units' \ 'Show Failed User Units' \ 'Show Timers' \ 'Show PipeWire Status' \ 'Show WirePlumber Status' \ 'Restart PipeWire' \ 'Restart WirePlumber' \ 'Flush DNS Cache' \ 'Reset Resolver Server Features' \ 'Show Resolver Statistics' \ 'Test Mako Notification' \ 'Refresh Waybar Custom Module' \ '← Back' ) case "$action" in 'Show System Overview') run_system_action system-overview
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1003`
```text
'Show Failed Services' -> run_system_action failed-services
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1006`
```text
'Show Boot Performance' -> run_system_action boot-performance
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1009`
```text
'Show Recent System Errors' -> run_system_action recent-errors
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1012`
```text
'Show Kernel Warnings' -> run_system_action kernel-warnings
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1015`
```text
'Show Storage Overview' -> run_system_action storage-overview
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1021`
```text
'Show Memory and Swap' -> run_system_action memory-overview
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1024`
```text
'Show Network Overview' -> run_system_action network-overview
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1027`
```text
'Check Package Health' -> run_system_action package-health
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1030`
```text
'List Pending Upgrades' -> run_system_action pending-upgrades
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1033`
```text
'Inspect Service and Logs' -> service=$(choose_service) [ -n "$service" ] && run_system_action inspect-service "$service"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1037`
```text
'List Firmware-Capable Devices' -> run_system_action firmware-devices
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1040`
```text
'Refresh Firmware Metadata' -> run_system_action refresh-firmware-metadata
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1043`
```text
'Check Firmware Updates' -> run_system_action firmware-updates
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1046`
```text
'Apply Firmware Updates' -> run_confirmed_system_action \ apply-firmware-updates \ "Apply available firmware updates"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1051`
```text
'Show Upgradeable Packages' -> run_system_action upgradeable-packages
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1054`
```text
'Run Unattended Upgrades Now' -> run_confirmed_system_action \ run-unattended-upgrades \ "Run unattended upgrades now"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1059`
```text
'Show NVMe SMART Health' -> nvme_device=$(choose_nvme_controller) [ -n "$nvme_device" ] && run_system_action nvme-smart-health "$nvme_device"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1064`
```text
'Show NVMe Firmware Slots' -> nvme_device=$(choose_nvme_controller) [ -n "$nvme_device" ] && run_system_action nvme-firmware-slots "$nvme_device"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1069`
```text
'Show NVMe Identify Data' -> nvme_device=$(choose_nvme_controller) [ -n "$nvme_device" ] && run_system_action nvme-identify-data "$nvme_device"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1074`
```text
'Show NVMe SMART via smartctl' -> nvme_device=$(choose_nvme_controller) [ -n "$nvme_device" ] && run_system_action nvme-smartctl "$nvme_device"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1079`
```text
'Show Btrfs Usage' -> run_system_action btrfs-usage
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1082`
```text
'Show Btrfs DF Summary' -> run_system_action btrfs-df
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1085`
```text
'Show Last Btrfs Scrub Status' -> run_system_action btrfs-scrub-status
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1088`
```text
'Show Journal Disk Usage' -> run_system_action journal-disk-usage
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1091`
```text
'Rotate and Vacuum Journals by Time' -> retention=$(choose_journal_vacuum_time) [ -n "$retention" ] && run_confirmed_system_action \ journal-vacuum-time \ "Rotate journals and retain ${retention}" \ "$retention"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1099`
```text
'Rotate and Vacuum Journals by Size' -> retention=$(choose_journal_vacuum_size) [ -n "$retention" ] && run_confirmed_system_action \ journal-vacuum-size \ "Rotate journals and cap usage at ${retention}" \ "$retention"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1107`
```text
'Top Disk Usage in Root' -> run_system_action top-disk-root
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1110`
```text
'Top Disk Usage in Home' -> run_system_action top-disk-home
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1113`
```text
'Show Failed System Units' -> run_system_action failed-system-units
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1116`
```text
'Show Failed User Units' -> run_system_action failed-user-units
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1119`
```text
'Show Timers' -> run_system_action show-timers
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1122`
```text
'Show PipeWire Status' -> run_system_action pipewire-status
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1125`
```text
'Show WirePlumber Status' -> run_system_action wireplumber-status
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1128`
```text
'Restart PipeWire' -> run_confirmed_system_action restart-pipewire "Restart PipeWire services"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1131`
```text
'Restart WirePlumber' -> run_confirmed_system_action restart-wireplumber "Restart WirePlumber"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1134`
```text
'Flush DNS Cache' -> run_system_action flush-dns-cache
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1137`
```text
'Reset Resolver Server Features' -> run_system_action reset-resolver-features
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1140`
```text
'Show Resolver Statistics' -> run_system_action resolver-statistics
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1143`
```text
'Test Mako Notification' -> run_system_action test-mako-notification
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1146`
```text
'Refresh Waybar Custom Module' -> run_system_action refresh-waybar-custom-module
```

## Phone Management

**Menu source(s):** `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu`

**Primary policy definitions:** `managed-labwc-adb-menu`, `managed-labwc-adb-action`, `managed-android-platform-tools`

- `server-status` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:141`.
- `wait-any-device` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:145`.
- `server-status` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:147`.
- `diagnose-devices` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:151`.
- `fastboot-list` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:166`.
- `fastboot-list` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:170`.
- `server-status` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:240`.
- `start-server` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:241`.
- `repair-server` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:242`.
- `stop-server` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:243`.
- `reconnect-usb` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:244`.
- `reconnect-offline` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:245`.
- `wait-any-device` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:246`.
- `list-devices` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:247`.
- `diagnose-devices` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:248`.
- `adb-version` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:249`.
- `host-features` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:250`.
- `device-summary` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:273`.
- `interactive-shell` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:274`.
- `list-packages` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:275`.
- `current-activity` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:276`.
- `battery-status` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:277`.
- `storage-status` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:278`.
- `cpu-memory` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:279`.
- `list-android-users` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:280`.
- `install-apk` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:305`.
- `install-apk-replace` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:310`.
- `uninstall-package` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:317`.
- `clear-app-data` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:329`.
- `grant-permission` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:343`.
- `push-download` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:354`.
- `pull-path` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:359`.
- `diagnose-devices` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:381`.
- `screenshot` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:382`.
- `screenrecord` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:383`.
- `logcat-recent` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:384`.
- `logcat-live` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:385`.
- `bugreport` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:386`.
- `pair-wireless` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:410`.
- `connect-wireless` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:416`.
- `disconnect-wireless` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:421`.
- `disconnect-all` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:424`.
- `mdns-services` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:427`.
- `enable-tcpip-5555` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:432`.
- `list-forwards` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:456`.
- `forward-tcp` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:462`.
- `reverse-tcp` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:473`.
- `reboot-system` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:504`.
- `reboot-recovery` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:509`.
- `reboot-bootloader` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:514`.
- `reboot-sideload` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:519`.
- `backup-device` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:524`.
- `samsung-download-firmware` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:540`.
- `samsung-flash-keep-data` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:555`.
- `samsung-flash-factory-reset` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:569`.
- `fastboot-list` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:594`.
- `fastboot-info` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:598`.
- `fastboot-reboot` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:603`.
- `fastboot-reboot-bootloader` via `run_adb_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:612`.

**Dispatch and parameter-selector branches (not independent test results):**

`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:221`
```text
'⮞ ADB Server' -> while :; do action=$( choose_lines \ "ADB Server" \ 'Show Server Status' \ 'Start ADB Server' \ 'Repair / Restart ADB Server' \ 'Stop ADB Server' \ 'Reconnect USB Devices' \ 'Reconnect Offline Devices' \ 'Wait for Any Device (60s)' \ 'List Devices with Details' \ 'Diagnose Device Connections' \ 'Show ADB Version' \ 'Show Host Features' \ '← Back' ) case "$action" in 'Show Server Status') run_adb_action server-status
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:241`
```text
'Start ADB Server' -> run_adb_action start-server
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:242`
```text
'Repair / Restart ADB Server' -> run_adb_action repair-server
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:243`
```text
'Stop ADB Server' -> run_adb_action stop-server
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:244`
```text
'Reconnect USB Devices' -> run_adb_action reconnect-usb
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:245`
```text
'Reconnect Offline Devices' -> run_adb_action reconnect-offline
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:246`
```text
'Wait for Any Device (60s)' -> run_adb_action wait-any-device
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:247`
```text
'List Devices with Details' -> run_adb_action list-devices
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:248`
```text
'Diagnose Device Connections' -> run_adb_action diagnose-devices
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:249`
```text
'Show ADB Version' -> run_adb_action adb-version
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:250`
```text
'Show Host Features' -> run_adb_action host-features
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:251`
```text
'← Back' -> break
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:252`
```text
'' -> exit 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:256`
```text
'⮞ Devices & Shell' -> device_serial=$(choose_device) || continue while :; do action=$( choose_lines \ "ADB Device: ${device_serial}" \ 'Show Device Summary' \ 'Open Interactive Shell' \ 'List User Applications' \ 'Show Current Activity' \ 'Show Battery Status' \ 'Show Storage Status' \ 'Show CPU and Memory' \ 'List Android Users' \ '← Back' ) case "$action" in 'Show Device Summary') run_adb_action device-summary "$device_serial"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:274`
```text
'Open Interactive Shell' -> run_adb_action interactive-shell "$device_serial"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:275`
```text
'List User Applications' -> run_adb_action list-packages "$device_serial"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:276`
```text
'Show Current Activity' -> run_adb_action current-activity "$device_serial"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:277`
```text
'Show Battery Status' -> run_adb_action battery-status "$device_serial"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:278`
```text
'Show Storage Status' -> run_adb_action storage-status "$device_serial"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:279`
```text
'Show CPU and Memory' -> run_adb_action cpu-memory "$device_serial"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:280`
```text
'List Android Users' -> run_adb_action list-android-users "$device_serial"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:281`
```text
'← Back' -> break
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:282`
```text
'' -> exit 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:286`
```text
'⮞ Files & Applications' -> device_serial=$(choose_device) || continue while :; do action=$( choose_lines \ "ADB Files & Apps: ${device_serial}" \ 'Install APK' \ 'Install / Replace APK' \ 'Uninstall Application' \ 'Clear Application Data' \ 'Grant Runtime Permission' \ 'Push File to Download' \ 'Pull Device File or Folder' \ '← Back' ) case "$action" in 'Install APK') local_file=$(choose_local_file "APK file") [ -n "$local_file" ] && run_adb_action install-apk "$device_serial" "$local_file"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:307`
```text
'Install / Replace APK' -> local_file=$(choose_local_file "Replacement APK file") [ -n "$local_file" ] && run_adb_action install-apk-replace "$device_serial" "$local_file"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:312`
```text
'Uninstall Application' -> package_name=$(choose_package) if [ -n "$package_name" ] && confirm_action "Uninstall ${package_name}" then run_adb_action \ uninstall-package \ "$device_serial" \ "$package_name" \ confirmed-adb-action fi
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:324`
```text
'Clear Application Data' -> package_name=$(choose_package) if [ -n "$package_name" ] && confirm_action "Clear all data for ${package_name}" then run_adb_action \ clear-app-data \ "$device_serial" \ "$package_name" \ confirmed-adb-action fi
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:336`
```text
'Grant Runtime Permission' -> package_name=$(choose_package) permission_name=$(choose_text "Android permission" "android.permission.POST_NOTIFICATIONS") if [ -n "$package_name" ] && [ -n "$permission_name" ] && confirm_action "Grant ${permission_name} to ${package_name}" then run_adb_action \ grant-permission \ "$device_serial" \ "$package_name" \ "$permission_name" \ confirmed-adb-action fi
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:351`
```text
'Push File to Download' -> local_file=$(choose_local_file "Local file to push") [ -n "$local_file" ] && run_adb_action push-download "$device_serial" "$local_file"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:356`
```text
'Pull Device File or Folder' -> remote_path=$(choose_text "Absolute Android path" "/sdcard/Download") [ -n "$remote_path" ] && run_adb_action pull-path "$device_serial" "$remote_path"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:361`
```text
'← Back' -> break
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:362`
```text
'' -> exit 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:366`
```text
'⮞ Diagnostics & Capture' -> device_serial=$(choose_device) || continue while :; do action=$( choose_lines \ "ADB Diagnostics: ${device_serial}" \ 'Diagnose All Connections' \ 'Save Screenshot' \ 'Record Screen (30s)' \ 'Show Recent Logcat' \ 'Follow Live Logcat' \ 'Collect Bugreport' \ '← Back' ) case "$action" in 'Diagnose All Connections') run_adb_action diagnose-devices
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:382`
```text
'Save Screenshot' -> run_adb_action screenshot "$device_serial"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:383`
```text
'Record Screen (30s)' -> run_adb_action screenrecord "$device_serial"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:384`
```text
'Show Recent Logcat' -> run_adb_action logcat-recent "$device_serial"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:385`
```text
'Follow Live Logcat' -> run_adb_action logcat-live "$device_serial"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:386`
```text
'Collect Bugreport' -> run_adb_action bugreport "$device_serial"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:387`
```text
'← Back' -> break
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:388`
```text
'' -> exit 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:392`
```text
'⮞ Wireless Debugging' -> while :; do action=$( choose_lines \ "ADB Wireless Debugging" \ 'Pair with Pairing Code' \ 'Connect to Wireless Device' \ 'Disconnect Wireless Device' \ 'Disconnect All Wireless Devices' \ 'Show mDNS Services' \ 'Enable Legacy TCP/IP Port 5555' \ '← Back' ) case "$action" in 'Pair with Pairing Code') endpoint=$(choose_text "Pairing host:port" "192.168.1.100:37099") pairing_code=$(choose_text "Six-digit pairing code" "") if [ -n "$endpoint" ] && [ -n "$pairing_code" ]; then run_adb_action pair-wireless "$endpoint" "$pairing_code" fi
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:413`
```text
'Connect to Wireless Device' -> endpoint=$(choose_text "ADB host:port" "192.168.1.100:5555") [ -n "$endpoint" ] && run_adb_action connect-wireless "$endpoint"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:418`
```text
'Disconnect Wireless Device' -> endpoint=$(choose_text "ADB host:port" "192.168.1.100:5555") [ -n "$endpoint" ] && run_adb_action disconnect-wireless "$endpoint"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:423`
```text
'Disconnect All Wireless Devices' -> run_adb_action disconnect-all
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:426`
```text
'Show mDNS Services' -> run_adb_action mdns-services
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:429`
```text
'Enable Legacy TCP/IP Port 5555' -> device_serial=$(choose_device) || continue if confirm_action "Enable unencrypted TCP/IP debugging on ${device_serial}"; then run_adb_action \ enable-tcpip-5555 \ "$device_serial" \ confirmed-adb-action fi
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:438`
```text
'← Back' -> break
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:439`
```text
'' -> exit 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:443`
```text
'⮞ Port Forwarding' -> device_serial=$(choose_device) || continue while :; do action=$( choose_lines \ "ADB Port Forwarding: ${device_serial}" \ 'List Forward and Reverse Rules' \ 'Forward Host TCP to Device TCP' \ 'Reverse Device TCP to Host TCP' \ '← Back' ) case "$action" in 'List Forward and Reverse Rules') run_adb_action list-forwards "$device_serial"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:458`
```text
'Forward Host TCP to Device TCP' -> host_port=$(choose_text "Host TCP port" "8080") device_port=$(choose_text "Device TCP port" "8080") if [ -n "$host_port" ] && [ -n "$device_port" ]; then run_adb_action \ forward-tcp \ "$device_serial" \ "$host_port" \ "$device_port" fi
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:469`
```text
'Reverse Device TCP to Host TCP' -> device_port=$(choose_text "Device TCP port" "8080") host_port=$(choose_text "Host TCP port" "8080") if [ -n "$device_port" ] && [ -n "$host_port" ]; then run_adb_action \ reverse-tcp \ "$device_serial" \ "$host_port" \ "$device_port" fi
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:480`
```text
'← Back' -> break
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:481`
```text
'' -> exit 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:485`
```text
'⮞ Reboot & Recovery' -> device_serial=$(choose_device) || continue while :; do action=$( choose_lines \ "ADB Reboot: ${device_serial}" \ 'Reboot Android' \ 'Reboot to Recovery' \ 'Reboot to Bootloader' \ 'Reboot to Sideload' \ 'Backup Device' \ 'Download Official Samsung Firmware' \ 'Flash Official Firmware (Keep Data)' \ 'Flash Official Firmware (Factory Reset)' \ '← Back' ) case "$action" in 'Reboot Android') if confirm_action "Reboot Android device ${device_serial}"; then run_adb_action reboot-system "$device_serial" confirmed-adb-action fi
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:507`
```text
'Reboot to Recovery' -> if confirm_action "Reboot ${device_serial} to recovery"; then run_adb_action reboot-recovery "$device_serial" confirmed-adb-action fi
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:512`
```text
'Reboot to Bootloader' -> if confirm_action "Reboot ${device_serial} to bootloader"; then run_adb_action reboot-bootloader "$device_serial" confirmed-adb-action fi
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:517`
```text
'Reboot to Sideload' -> if confirm_action "Reboot ${device_serial} to sideload"; then run_adb_action reboot-sideload "$device_serial" confirmed-adb-action fi
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:522`
```text
'Backup Device' -> if confirm_action "Back up all ADB-readable data from ${device_serial}"; then run_adb_action backup-device "$device_serial" confirmed-adb-action fi
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:527`
```text
'Download Official Samsung Firmware' -> samsung_model=$( choose_text "Samsung model" "SM-S931U1" | tr '[:lower:]' '[:upper:]' ) samsung_region=$( choose_text "Samsung region CSC" "XAA" | tr '[:lower:]' '[:upper:]' ) if [ -n "$samsung_model" ] && [ -n "$samsung_region" ] && confirm_action "Download latest official firmware for ${samsung_model}/${samsung_region}" then run_adb_action \ samsung-download-firmware \ "$device_serial" \ "$samsung_model" \ "$samsung_region" \ confirmed-samsung-download fi
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:548`
```text
'Flash Official Firmware (Keep Data)' -> firmware_directory=$(choose_samsung_firmware_directory) if [ -n "$firmware_directory" ] && confirm_phrase \ "Flash verified official firmware while requesting data preservation" \ "FLASH HOME_CSC" then run_adb_action \ samsung-flash-keep-data \ "$device_serial" \ "$firmware_directory" \ confirmed-samsung-keep-data-flash fi
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:562`
```text
'Flash Official Firmware (Factory Reset)' -> firmware_directory=$(choose_samsung_firmware_directory) if [ -n "$firmware_directory" ] && confirm_phrase \ "ERASE DEVICE and flash verified official firmware" \ "FACTORY RESET" then run_adb_action \ samsung-flash-factory-reset \ "$device_serial" \ "$firmware_directory" \ confirmed-samsung-factory-reset fi
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:576`
```text
'← Back' -> break
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:577`
```text
'' -> exit 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:581`
```text
'⮞ Fastboot' -> while :; do action=$( choose_lines \ "Fastboot" \ 'List Fastboot Devices' \ 'Show Fastboot Device Information' \ 'Reboot Fastboot Device' \ 'Reboot Fastboot Device to Bootloader' \ '← Back' ) case "$action" in 'List Fastboot Devices') run_adb_action fastboot-list
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:596`
```text
'Show Fastboot Device Information' -> fastboot_serial=$(choose_fastboot_device) || continue run_adb_action fastboot-info "$fastboot_serial"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:600`
```text
'Reboot Fastboot Device' -> fastboot_serial=$(choose_fastboot_device) || continue if confirm_action "Reboot fastboot device ${fastboot_serial}"; then run_adb_action \ fastboot-reboot \ "$fastboot_serial" \ confirmed-adb-action fi
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:609`
```text
'Reboot Fastboot Device to Bootloader' -> fastboot_serial=$(choose_fastboot_device) || continue if confirm_action "Reboot ${fastboot_serial} back to bootloader"; then run_adb_action \ fastboot-reboot-bootloader \ "$fastboot_serial" \ confirmed-adb-action fi
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:618`
```text
'← Back' -> break
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:619`
```text
'' -> exit 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu:623`
```text
'← Back'|'' -> exit 0
```

## Backup & Recovery

**Menu source(s):** `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu`, `d-i/forky/hooks/target/usr/local/bin/labwc-external-drives`

**Primary policy definitions:** `managed-labwc-recovery-action`, `managed-labwc-recovery-action-root`, `managed-labwc-external-drives`

**Direct category dispatch:**
`d-i/forky/hooks/target/usr/local/bin/labwc-computer-management:310`
```sh
backup_recovery_menu() {
  while :; do
    action=$(
      choose_lines \
        "Backup & Recovery" \
        "⮞ Troubleshooting" \
        "⮞ Backup Drives" \
        "← Back"
    )

    case "$action" in
      "⮞ Troubleshooting")
        run_command labwc-maintenance-menu recovery
        ;;
      "⮞ Backup Drives")
        run_command labwc-external-drives
        ;;
      "← Back")
        return 0
        ;;
      '')
        return 0
        ;;
    esac
  done
}
```

- `restart-waybar` via `run_recovery_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1189`.
- `restart-audio` via `run_recovery_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1192`.
- `restart-portals` via `run_recovery_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1195`.
- `refresh-displays` via `run_recovery_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1198`.
- `reset-failed-units` via `run_confirmed_recovery_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1201`.
- `restart-networkmanager` via `run_confirmed_recovery_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1204`.
- `restart-bluetooth` via `run_confirmed_recovery_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1207`.
- `restart-udisks` via `run_confirmed_recovery_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1210`.
- `restart-polkit` via `run_confirmed_recovery_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1213`.
- `refresh-package-index` via `run_confirmed_recovery_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1216`.
- `repair-dpkg` via `run_confirmed_recovery_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1219`.
- `repair-apt` via `run_confirmed_recovery_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1222`.
- `rebuild-initramfs` via `run_confirmed_recovery_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1225`.
- `refresh-grub` via `run_confirmed_recovery_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1228`.
- `create-timeshift-snapshot` via `run_confirmed_recovery_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1231`.
- `drop-page-cache` via `run_confirmed_recovery_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1234`.
- `drop-dentries-inodes` via `run_confirmed_recovery_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1237`.
- `drop-all-clean-caches` via `run_confirmed_recovery_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1240`.
- `reset-zram-swap` via `run_confirmed_recovery_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1243`.
- `aggressive-journal-vacuum` via `run_confirmed_recovery_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1246`.
- `emergency-btrfs-reclaim` via `run_confirmed_recovery_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1249`.

**Dispatch and parameter-selector branches (not independent test results):**

`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1158`
```text
'⮞ Troubleshooting' -> while :; do action=$( choose_lines \ Troubleshooting \ 'Restart Waybar' \ 'Restart Audio Services' \ 'Restart Desktop Portals' \ 'Refresh Display Configuration' \ 'Reset Failed System Units' \ 'Restart NetworkManager' \ 'Restart Bluetooth Service' \ 'Restart UDisks Service' \ 'Restart Polkit Service' \ 'Refresh Package Index' \ 'Complete Interrupted Package Configuration' \ 'Repair Package Dependencies' \ 'Rebuild Initramfs' \ 'Refresh GRUB Configuration' \ 'Create Timeshift Recovery Snapshot' \ 'Drop Page Cache Only' \ 'Drop Dentries and Inodes' \ 'Drop All Clean Caches' \ 'Reset zram Swap' \ 'Aggressive Journal Vacuum' \ 'Emergency Btrfs Unused-Chunk Reclaim' \ '← Back' ) case "$action" in 'Restart Waybar') run_recovery_action restart-waybar
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1191`
```text
'Restart Audio Services' -> run_recovery_action restart-audio
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1194`
```text
'Restart Desktop Portals' -> run_recovery_action restart-portals
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1197`
```text
'Refresh Display Configuration' -> run_recovery_action refresh-displays
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1200`
```text
'Reset Failed System Units' -> run_confirmed_recovery_action reset-failed-units "Reset failed units"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1203`
```text
'Restart NetworkManager' -> run_confirmed_recovery_action restart-networkmanager "Restart NetworkManager"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1206`
```text
'Restart Bluetooth Service' -> run_confirmed_recovery_action restart-bluetooth "Restart Bluetooth"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1209`
```text
'Restart UDisks Service' -> run_confirmed_recovery_action restart-udisks "Restart UDisks"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1212`
```text
'Restart Polkit Service' -> run_confirmed_recovery_action restart-polkit "Restart Polkit"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1215`
```text
'Refresh Package Index' -> run_confirmed_recovery_action refresh-package-index "Refresh package index"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1218`
```text
'Complete Interrupted Package Configuration' -> run_confirmed_recovery_action repair-dpkg "Complete dpkg configuration"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1221`
```text
'Repair Package Dependencies' -> run_confirmed_recovery_action repair-apt "Repair package dependencies"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1224`
```text
'Rebuild Initramfs' -> run_confirmed_recovery_action rebuild-initramfs "Rebuild all initramfs images"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1227`
```text
'Refresh GRUB Configuration' -> run_confirmed_recovery_action refresh-grub "Refresh GRUB configuration"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1230`
```text
'Create Timeshift Recovery Snapshot' -> run_confirmed_recovery_action create-timeshift-snapshot "Create Timeshift recovery snapshot"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1233`
```text
'Drop Page Cache Only' -> run_confirmed_recovery_action drop-page-cache "Drop clean page cache after sync"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1236`
```text
'Drop Dentries and Inodes' -> run_confirmed_recovery_action drop-dentries-inodes "Drop clean dentries and inode caches after sync"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1239`
```text
'Drop All Clean Caches' -> run_confirmed_recovery_action drop-all-clean-caches "Drop all clean filesystem caches after sync"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1242`
```text
'Reset zram Swap' -> run_confirmed_recovery_action reset-zram-swap "Restart the managed zram swap lifecycle"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1245`
```text
'Aggressive Journal Vacuum' -> run_confirmed_recovery_action aggressive-journal-vacuum "Rotate journals and retain only 3 days"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-maintenance-menu:1248`
```text
'Emergency Btrfs Unused-Chunk Reclaim' -> run_confirmed_recovery_action emergency-btrfs-reclaim "Reclaim completely unused Btrfs chunks"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-external-drives:841`
```text
'Mount Volume' -> mount_volume \ "$device" \ "$expected_devnum" \ "$expected_type" || true
```
`d-i/forky/hooks/target/usr/local/bin/labwc-external-drives:847`
```text
'Unmount Volume' -> unmount_volume \ "$device" \ "$expected_devnum" \ "$expected_type" || true
```
`d-i/forky/hooks/target/usr/local/bin/labwc-external-drives:853`
```text
'Safely Power Off Drive' -> power_off_drive \ "$parent_device" \ "$selected_disk_devnum" || true
```

## Hardware & Peripherals

**Menu source(s):** `d-i/forky/hooks/target/usr/local/bin/labwc-external-drives`, `d-i/forky/hooks/target/usr/local/bin/labwc-bluetooth`, `d-i/forky/hooks/target/usr/local/bin/labwc-brightness-control`

**Primary policy definitions:** `managed-labwc-external-drives`, `managed-labwc-bluetooth`, `managed-labwc-brightness-control`

**Direct category dispatch:**
`d-i/forky/hooks/target/usr/local/bin/labwc-computer-management:337`
```sh
hardware_peripherals_menu() {
  while :; do
    action=$(
      choose_lines \
        "Hardware & Peripherals" \
        "⮞ External Drives" \
        "⮞ Bluetooth Devices" \
        "⮞ Brightness" \
        "← Back"
    )

    case "$action" in
      "⮞ External Drives")
        run_command labwc-external-drives
        ;;
      "⮞ Bluetooth Devices")
        run_command labwc-bluetooth menu
        ;;
      "⮞ Brightness")
        run_command labwc-brightness-control
        ;;
      "← Back")
        return 0
        ;;
      '')
        return 0
        ;;
    esac
  done
}
```


**Dispatch and parameter-selector branches (not independent test results):**

`d-i/forky/hooks/target/usr/local/bin/labwc-external-drives:841`
```text
'Mount Volume' -> mount_volume \ "$device" \ "$expected_devnum" \ "$expected_type" || true
```
`d-i/forky/hooks/target/usr/local/bin/labwc-external-drives:847`
```text
'Unmount Volume' -> unmount_volume \ "$device" \ "$expected_devnum" \ "$expected_type" || true
```
`d-i/forky/hooks/target/usr/local/bin/labwc-external-drives:853`
```text
'Safely Power Off Drive' -> power_off_drive \ "$parent_device" \ "$selected_disk_devnum" || true
```
`d-i/forky/hooks/target/usr/local/bin/labwc-bluetooth:350`
```text
'Connect Device' -> if run_device_command connect "$address"; then notify_bluetooth normal bluetooth device.changed \ "Bluetooth device connected" \ "Connected to ${address}." refresh_waybar else notify_bluetooth critical dialog-error device.error \ "Bluetooth connection failed" \ "Could not connect to ${address}." fi
```
`d-i/forky/hooks/target/usr/local/bin/labwc-bluetooth:362`
```text
'Disconnect Device' -> if run_device_command disconnect "$address"; then notify_bluetooth normal bluetooth device.changed \ "Bluetooth device disconnected" \ "Disconnected ${address}." refresh_waybar else notify_bluetooth critical dialog-error device.error \ "Bluetooth disconnect failed" \ "Could not disconnect ${address}." fi
```
`d-i/forky/hooks/target/usr/local/bin/labwc-bluetooth:374`
```text
'Trust Device' -> run_device_command trust "$address" && notify_bluetooth normal bluetooth device.changed \ "Bluetooth device trusted" \ "Trusted ${address}."
```
`d-i/forky/hooks/target/usr/local/bin/labwc-bluetooth:380`
```text
'Untrust Device' -> run_device_command untrust "$address" && notify_bluetooth normal bluetooth device.changed \ "Bluetooth device untrusted" \ "Removed trust from ${address}."
```
`d-i/forky/hooks/target/usr/local/bin/labwc-bluetooth:386`
```text
'Unpair Device' -> run_device_command remove "$address" && notify_bluetooth normal bluetooth device.changed \ "Bluetooth device unpaired" \ "Removed ${address}." refresh_waybar
```
`d-i/forky/hooks/target/usr/local/bin/labwc-bluetooth:393`
```text
'Device Information' -> exec labwc-terminal -e labwc-bluetooth info "$address"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-bluetooth:413`
```text
'Make Discoverable' -> set_visibility discoverable
```
`d-i/forky/hooks/target/usr/local/bin/labwc-bluetooth:414`
```text
'Hide from Discovery' -> set_visibility hidden
```
`d-i/forky/hooks/target/usr/local/bin/labwc-bluetooth:415`
```text
'Enable Bluetooth' -> set_power on
```
`d-i/forky/hooks/target/usr/local/bin/labwc-bluetooth:416`
```text
'Disable Bluetooth' -> set_power off
```
`d-i/forky/hooks/target/usr/local/bin/labwc-bluetooth:441`
```text
'Scan for Devices' -> scan_devices
```
`d-i/forky/hooks/target/usr/local/bin/labwc-bluetooth:442`
```text
'Pair Device' -> pair_device
```
`d-i/forky/hooks/target/usr/local/bin/labwc-bluetooth:443`
```text
'Connect Device' -> perform_device_action connect paired "Connect device" \ "Bluetooth device connected" "Connected to the selected device"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-bluetooth:447`
```text
'Disconnect Device' -> perform_device_action disconnect connected "Disconnect device" \ "Bluetooth device disconnected" "Disconnected the selected device"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-bluetooth:451`
```text
'Manage Device' -> manage_device
```
`d-i/forky/hooks/target/usr/local/bin/labwc-bluetooth:452`
```text
'Adapter Settings' -> run_adapter_menu
```
`d-i/forky/hooks/target/usr/local/bin/labwc-bluetooth:453`
```text
'Open Interactive Console' -> open_interactive_console
```
`d-i/forky/hooks/target/usr/local/bin/labwc-brightness-control:133`
```text
'Increase +10%' -> apply_brightness +10%
```
`d-i/forky/hooks/target/usr/local/bin/labwc-brightness-control:134`
```text
'Decrease -10%' -> apply_brightness 10%-
```
`d-i/forky/hooks/target/usr/local/bin/labwc-brightness-control:135`
```text
'Night 15%' -> apply_brightness 15%
```
`d-i/forky/hooks/target/usr/local/bin/labwc-brightness-control:136`
```text
'Dim 30%' -> apply_brightness 30%
```
`d-i/forky/hooks/target/usr/local/bin/labwc-brightness-control:137`
```text
'Balanced 55%' -> apply_brightness 55%
```
`d-i/forky/hooks/target/usr/local/bin/labwc-brightness-control:138`
```text
'Bright 80%' -> apply_brightness 80%
```
`d-i/forky/hooks/target/usr/local/bin/labwc-brightness-control:139`
```text
'Maximum 100%' -> apply_brightness 100%
```

## AI & Copilots

**Menu source(s):** `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots`

**Primary policy definitions:** `managed-labwc-ai-copilots`, `managed-labwc-ai-copilots-action`, `managed-ai-copilots-model-download`

- `llama-download-model` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:225`.
- `whisper-download-model` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:243`.
- `llama-download-catalog-model` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:293`.
- `whisper-download-catalog-model` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:302`.
- `llama-model-info` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:310`.
- `codex-task` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:660`.
- `codex-new-session` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:667`.
- `codex-resume-last` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:668`.
- `codex-resume-picker` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:669`.
- `codex-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:670`.
- `codex-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:671`.
- `codex-clear-recent-projects` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:672`.
- `codex-set-project` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:701`.
- `codex-set-project` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:703`.
- `codex-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:704`.
- `codex-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:705`.
- `codex-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:706`.
- `codex-open-project-terminal` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:707`.
- `codex-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:708`.
- `codex-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:709`.
- `codex-set-model` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:719`.
- `codex-set-model` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:722`.
- `codex-set-reasoning` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:729`.
- `codex-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:731`.
- `codex-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:732`.
- `codex-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:733`.
- `codex-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:743`.
- `codex-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:744`.
- `codex-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:745`.
- `codex-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:746`.
- `codex-open-home-terminal` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:747`.
- `codex-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:748`.
- `codex-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:758`.
- `codex-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:759`.
- `codex-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:760`.
- `codex-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:761`.
- `codex-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:762`.
- `codex-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:763`.
- `codex-new-session` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:773`.
- `codex-resume-last` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:774`.
- `llama-memory` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:791`.
- `llama-memory` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:792`.
- `llama-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:793`.
- `llama-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:794`.
- `llama-memory` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:795`.
- `llama-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:805`.
- `llama-favorite` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:806`.
- `llama-favorite` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:807`.
- `llama-set-active-model` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:810`.
- `llama-set-active-model` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:823`.
- `llama-open-model-search` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:828`.
- `llama-open-model-search` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:830`.
- `llama-open-model-search` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:831`.
- `llama-open-model-search` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:832`.
- `llama-open-model-search` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:833`.
- `llama-open-model-search` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:834`.
- `llama-open-model-search` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:835`.
- `llama-open-model-search` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:836`.
- `llama-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:837`.
- `llama-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:839`.
- `llama-set-default-model` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:842`.
- `llama-set-model-alias` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:848`.
- `llama-new-chat` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:867`.
- `llama-resume-last-chat` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:868`.
- `llama-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:869`.
- `llama-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:870`.
- `llama-clear-chat-history` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:871`.
- `llama-set-system-prompt` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:874`.
- `llama-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:876`.
- `llama-set-system-prompt` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:877`.
- `llama-set-preset` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:887`.
- `llama-set-preset` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:888`.
- `llama-set-preset` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:889`.
- `llama-set-preset` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:890`.
- `llama-set-preset` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:891`.
- `llama-set-preset` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:892`.
- `llama-set-preset` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:893`.
- `llama-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:894`.
- `llama-set-preset` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:895`.
- `llama-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:905`.
- `llama-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:906`.
- `llama-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:907`.
- `llama-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:908`.
- `llama-new-chat` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:909`.
- `llama-reset-runtime` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:910`.
- `llama-performance-preset` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:920`.
- `llama-performance-preset` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:921`.
- `llama-performance-preset` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:922`.
- `llama-set-runtime` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:925`.
- `llama-set-runtime` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:929`.
- `llama-set-runtime` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:933`.
- `llama-set-runtime` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:937`.
- `llama-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:939`.
- `llama-start-server` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:949`.
- `llama-stop-server` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:950`.
- `llama-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:951`.
- `llama-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:952`.
- `llama-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:953`.
- `llama-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:954`.
- `llama-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:964`.
- `llama-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:965`.
- `llama-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:966`.
- `llama-prune-partials` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:967`.
- `llama-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:968`.
- `llama-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:978`.
- `llama-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:979`.
- `llama-model-info` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:980`.
- `llama-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:981`.
- `llama-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:982`.
- `llama-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:983`.
- `llama-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:984`.
- `llama-ask` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:996`.
- `llama-new-chat` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:998`.
- `llama-resume-last-chat` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:999`.
- `llama-set-active-model` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1002`.
- `whisper-transcribe-file` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1021`.
- `whisper-control` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1028`.
- `whisper-control` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1029`.
- `whisper-control` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1030`.
- `whisper-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1031`.
- `whisper-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1032`.
- `whisper-open` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1033`.
- `whisper-transcribe-last` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1044`.
- `whisper-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1045`.
- `whisper-open` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1046`.
- `whisper-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1047`.
- `whisper-set-language` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1057`.
- `whisper-set-language` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1058`.
- `whisper-set-language` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1059`.
- `whisper-set-language` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1060`.
- `whisper-set-language` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1061`.
- `whisper-set-language` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1062`.
- `whisper-set-language` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1065`.
- `whisper-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1067`.
- `whisper-set-output` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1077`.
- `whisper-set-output` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1078`.
- `whisper-set-output` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1079`.
- `whisper-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1080`.
- `whisper-open` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1081`.
- `whisper-set-post-processing` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1091`.
- `whisper-set-post-processing` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1092`.
- `whisper-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1093`.
- `whisper-set-active-model` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1105`.
- `whisper-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1108`.
- `whisper-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1109`.
- `whisper-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1110`.
- `whisper-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1111`.
- `whisper-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1112`.
- `whisper-prune-partials` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1113`.
- `whisper-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1114`.
- `whisper-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1124`.
- `whisper-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1125`.
- `whisper-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1126`.
- `whisper-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1127`.
- `whisper-open` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1128`.
- `whisper-open` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1129`.
- `whisper-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1139`.
- `whisper-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1140`.
- `whisper-audio` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1141`.
- `whisper-audio` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1142`.
- `whisper-audio` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1143`.
- `whisper-open` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1144`.
- `whisper-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1154`.
- `whisper-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1155`.
- `whisper-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1156`.
- `whisper-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1157`.
- `whisper-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1158`.
- `whisper-diagnostic` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1159`.
- `whisper-control` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1169`.
- `whisper-dictation` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1170`.
- `whisper-transcribe-last` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1172`.
- `whisper-set-active-model` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1175`.
- `whisper-dictation` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1178`.
- `whisper-control` via `run_action` at `d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1179`.

**Complete backend action/argument contract:**

- `codex-new-session`: 0, 0 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:61`.
- `codex-resume-last`: 0, 0 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:62`.
- `codex-resume-picker`: 0, 0 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:63`.
- `codex-task`: 1, 1 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:64`.
- `codex-set-project`: 1, 1 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:65`.
- `codex-set-model`: 1, 1 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:66`.
- `codex-set-reasoning`: 1, 1 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:67`.
- `codex-clear-recent-projects`: 0, 0 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:68`.
- `codex-open-project-terminal`: 0, 0 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:69`.
- `codex-open-home-terminal`: 0, 0 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:70`.
- `codex-diagnostic`: 1, 1 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:71`.
- `llama-ask`: 1, 1 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:72`.
- `llama-new-chat`: 0, 0 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:73`.
- `llama-resume-last-chat`: 0, 0 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:74`.
- `llama-set-active-model`: 1, 1 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:75`.
- `llama-set-default-model`: 1, 1 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:76`.
- `llama-set-model-alias`: 2, 2 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:77`.
- `llama-download-catalog-model`: 1, 1 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:78`.
- `llama-download-model`: 4, 4 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:79`.
- `llama-open-model-search`: 1, 2 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:80`.
- `llama-favorite`: 1, 1 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:81`.
- `llama-memory`: 1, 1 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:82`.
- `llama-clear-chat-history`: 0, 0 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:83`.
- `llama-set-system-prompt`: 1, 1 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:84`.
- `llama-set-preset`: 1, 1 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:85`.
- `llama-set-runtime`: 2, 2 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:86`.
- `llama-performance-preset`: 1, 1 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:87`.
- `llama-reset-runtime`: 0, 0 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:88`.
- `llama-start-server`: 0, 0 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:89`.
- `llama-stop-server`: 0, 0 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:90`.
- `llama-prune-partials`: 0, 0 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:91`.
- `llama-model-info`: 2, 2 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:92`.
- `llama-diagnostic`: 1, 1 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:93`.
- `whisper-control`: 1, 1 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:94`.
- `whisper-dictation`: 1, 1 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:95`.
- `whisper-transcribe-file`: 1, 1 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:96`.
- `whisper-transcribe-last`: 0, 0 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:97`.
- `whisper-set-active-model`: 1, 1 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:98`.
- `whisper-download-catalog-model`: 1, 1 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:99`.
- `whisper-download-model`: 4, 4 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:100`.
- `whisper-prune-partials`: 0, 0 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:101`.
- `whisper-set-language`: 1, 1 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:102`.
- `whisper-set-output`: 1, 1 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:103`.
- `whisper-set-post-processing`: 1, 1 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:104`.
- `whisper-open`: 1, 1 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:105`.
- `whisper-audio`: 1, 1 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:106`.
- `whisper-diagnostic`: 1, 1 arguments; `d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm:107`.

**Dispatch and parameter-selector branches (not independent test results):**

`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:292`
```text
'' -> return 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:301`
```text
'' -> return 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:667`
```text
"New Coding Session" -> run_action codex-new-session
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:668`
```text
"Resume Last Session" -> run_action codex-resume-last
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:669`
```text
"Browse Sessions" -> run_action codex-resume-picker
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:670`
```text
"Show Session Storage" -> run_action codex-diagnostic session-storage
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:671`
```text
"Show Recent Session Index" -> run_action codex-diagnostic session-index
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:672`
```text
"Clear Recent Projects" -> run_action codex-clear-recent-projects
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:673`
```text
"← Back"|'' -> return 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:682`
```text
"Implement Task…" -> codex_prompt_action "Implement this task safely and completely: " "Codex task"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:683`
```text
"Review Current Project…" -> codex_prompt_action "Review the current project, focusing on: " "Review focus"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:684`
```text
"Explain Code…" -> codex_prompt_action "Explain this code or behavior clearly: " "Code to explain"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:685`
```text
"Fix Failing Tests…" -> codex_prompt_action "Diagnose and fix these failing tests without weakening coverage: " "Failing tests"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:686`
```text
"Refactor Safely…" -> codex_prompt_action "Refactor this area while preserving behavior: " "Refactor goal"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:687`
```text
"Generate Tests…" -> codex_prompt_action "Add focused tests for this behavior: " "Test objective"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:688`
```text
"Security Review…" -> codex_prompt_action "Perform a repository-grounded security review of: " "Security review scope"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:689`
```text
"Update Documentation…" -> codex_prompt_action "Update the relevant documentation for: " "Documentation objective"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:690`
```text
"← Back"|'' -> return 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:699`
```text
"Choose Project…" -> project=$(choose_project) [ -n "$project" ] && run_action codex-set-project "$project"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:703`
```text
"Use Home Directory" -> run_action codex-set-project "$HOME"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:704`
```text
"Show Current Project" -> run_action codex-diagnostic current-project
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:705`
```text
"Show Git Status" -> run_action codex-diagnostic git-status
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:706`
```text
"Show Project Files" -> run_action codex-diagnostic project-files
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:707`
```text
"Open Project Terminal" -> run_action codex-open-project-terminal
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:708`
```text
"Show Project AGENTS.md" -> run_action codex-diagnostic project-agents
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:709`
```text
"Show Recent Projects" -> run_action codex-diagnostic recent-projects
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:710`
```text
"← Back"|'' -> return 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:719`
```text
"Use Default Model" -> run_action codex-set-model default
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:720`
```text
"Set Model…" -> model=$(choose_text "Codex model" "Enter model identifier") [ -n "$model" ] && run_action codex-set-model "$model"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:724`
```text
"Set Reasoning Effort…" -> effort=$( printf '%s\n' low medium high xhigh default | choose_menu_input "Codex reasoning effort" ) [ -n "$effort" ] && run_action codex-set-reasoning "$effort"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:731`
```text
"Show Model & Reasoning Settings" -> run_action codex-diagnostic model-settings
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:732`
```text
"Show Codex Version" -> run_action codex-diagnostic version
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:733`
```text
"Show Codex Help" -> run_action codex-diagnostic help
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:734`
```text
"← Back"|'' -> return 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:743`
```text
"List Installed Skills" -> run_action codex-diagnostic skills
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:744`
```text
"Show Codex Home" -> run_action codex-diagnostic codex-home
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:745`
```text
"Show Memory Directory" -> run_action codex-diagnostic memories
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:746`
```text
"Show Configuration Files" -> run_action codex-diagnostic config-files
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:747`
```text
"Open Codex Home Terminal" -> run_action codex-open-home-terminal
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:748`
```text
"Check Managed Wrapper" -> run_action codex-diagnostic wrapper
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:749`
```text
"← Back"|'' -> return 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:758`
```text
"Run Wrapper Health Check" -> run_action codex-diagnostic health
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:759`
```text
"Show Runtime Paths" -> run_action codex-diagnostic runtime-paths
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:760`
```text
"Show Recent Session Index" -> run_action codex-diagnostic session-index
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:761`
```text
"Show Recent Codex Logs" -> run_action codex-diagnostic recent-logs
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:762`
```text
"Show Codex Version" -> run_action codex-diagnostic version
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:763`
```text
"Show Codex Help" -> run_action codex-diagnostic help
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:764`
```text
"← Back"|'' -> return 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:773`
```text
"★ New Coding Session" -> run_action codex-new-session
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:774`
```text
"★ Resume Last Session" -> run_action codex-resume-last
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:775`
```text
"★ Implement Task…" -> codex_prompt_action "Implement this task safely and completely: " "Codex task"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:776`
```text
"⮞ Sessions" -> codex_sessions_menu
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:777`
```text
"⮞ Code Actions" -> codex_code_actions_menu
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:778`
```text
"⮞ Project Context" -> codex_project_context_menu
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:779`
```text
"⮞ Models & Reasoning" -> codex_models_reasoning_menu
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:780`
```text
"⮞ Skills & Tools" -> codex_skills_tools_menu
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:781`
```text
"⮞ Diagnostics" -> codex_diagnostics_menu
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:782`
```text
"← Back"|'' -> return 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:791`
```text
"Enable Persistent Prompt Memory" -> run_action llama-memory enable
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:792`
```text
"Disable Persistent Prompt Memory" -> run_action llama-memory disable
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:793`
```text
"Show Memory Status" -> run_action llama-diagnostic memory-status
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:794`
```text
"Show Remembered Prompts" -> run_action llama-diagnostic remembered-prompts
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:795`
```text
"Clear Remembered Prompts" -> run_action llama-memory clear
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:796`
```text
"← Back"|'' -> return 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:805`
```text
"Show Favorite Models" -> run_action llama-diagnostic favorites
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:806`
```text
"Add Active Model to Favorites" -> run_action llama-favorite add
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:807`
```text
"Remove Active Model from Favorites" -> run_action llama-favorite remove
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:808`
```text
"Use Favorite Model…" -> model=$(choose_favorite_model) [ -n "$model" ] && run_action llama-set-active-model "$model"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:812`
```text
"← Back"|'' -> return 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:821`
```text
"Change Model…" -> model=$(choose_model) [ -n "$model" ] && run_action llama-set-active-model "$model"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:825`
```text
"Download New Model…" -> download_llama_model
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:826`
```text
"Search Models…" -> query=$(choose_text "Search Hugging Face models" "coding GGUF") [ -n "$query" ] && run_action llama-open-model-search search "$query"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:830`
```text
"Browse Recommended Models" -> run_action llama-open-model-search recommended
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:831`
```text
"Browse Coding Models" -> run_action llama-open-model-search coding
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:832`
```text
"Browse Reasoning Models" -> run_action llama-open-model-search reasoning
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:833`
```text
"Browse Small / Fast Models" -> run_action llama-open-model-search small-fast
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:834`
```text
"Browse Vision Models" -> run_action llama-open-model-search vision
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:835`
```text
"Browse Embedding Models" -> run_action llama-open-model-search embedding
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:836`
```text
"Browse Recently Added Models" -> run_action llama-open-model-search recent
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:837`
```text
"Show Installed Models" -> run_action llama-diagnostic installed-models
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:838`
```text
"⮞ Favorite Models" -> llama_favorites_menu
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:839`
```text
"Recent Models" -> run_action llama-diagnostic recent-models
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:840`
```text
"Set Default Model" -> model=$(choose_model) [ -n "$model" ] && run_action llama-set-default-model "$model"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:844`
```text
"Set Model Alias" -> model=$(choose_model) [ -n "$model" ] || continue alias_name=$(choose_text "Model alias" "coding") [ -n "$alias_name" ] && run_action llama-set-model-alias "$alias_name" "$model"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:850`
```text
"Show Model Details" -> run_model_info details
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:851`
```text
"Show Model License" -> run_model_info license
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:852`
```text
"Show Model Architecture" -> run_model_info architecture
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:853`
```text
"Show Parameter Count" -> run_model_info parameter-count
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:854`
```text
"Show Quantization" -> run_model_info quantization
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:855`
```text
"Show Model Size" -> run_model_info size
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:856`
```text
"Show Context Length" -> run_model_info context-length
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:857`
```text
"Show Disk Location" -> run_model_info location
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:858`
```text
"← Back"|'' -> return 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:867`
```text
"New Chat" -> run_action llama-new-chat
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:868`
```text
"Resume Last Chat" -> run_action llama-resume-last-chat
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:869`
```text
"Show Last Prompt" -> run_action llama-diagnostic last-prompt
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:870`
```text
"Show Recent Chats" -> run_action llama-diagnostic recent-chats
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:871`
```text
"Clear Chat History" -> run_action llama-clear-chat-history
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:872`
```text
"Set System Prompt…" -> prompt=$(choose_text "Llama system prompt" "You are a careful local assistant.") [ -n "$prompt" ] && run_action llama-set-system-prompt "$prompt"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:876`
```text
"Show System Prompt" -> run_action llama-diagnostic system-prompt
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:877`
```text
"Clear System Prompt" -> run_action llama-set-system-prompt clear
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:878`
```text
"← Back"|'' -> return 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:887`
```text
"Coding Assistant" -> run_action llama-set-preset coding
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:888`
```text
"Code Review" -> run_action llama-set-preset code-review
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:889`
```text
"Security Review" -> run_action llama-set-preset security-review
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:890`
```text
"Deep Reasoning" -> run_action llama-set-preset deep-reasoning
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:891`
```text
"Concise Summary" -> run_action llama-set-preset concise-summary
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:893`
```text
"Shell Safety Review" -> run_action llama-set-preset shell-safety
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:894`
```text
"Show Active Preset" -> run_action llama-diagnostic active-preset
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:895`
```text
"Clear Active Preset" -> run_action llama-set-preset clear
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:896`
```text
"← Back"|'' -> return 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:905`
```text
"Show Runtime Configuration" -> run_action llama-diagnostic runtime
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:906`
```text
"Show Active Model" -> run_action llama-diagnostic active-model
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:907`
```text
"Show Llama Version" -> run_action llama-diagnostic version
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:908`
```text
"Show Llama Help" -> run_action llama-diagnostic help
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:909`
```text
"Start Interactive CLI" -> run_action llama-new-chat
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:910`
```text
"Reset Runtime Overrides" -> run_action llama-reset-runtime
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:911`
```text
"← Back"|'' -> return 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:920`
```text
"Balanced Preset" -> run_action llama-performance-preset balanced
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:921`
```text
"Low-Memory Preset" -> run_action llama-performance-preset low-memory
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:922`
```text
"High-Context Preset" -> run_action llama-performance-preset high-context
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:923`
```text
"Set Context Length…" -> value=$(choose_text "Llama context length" "8192") [ -n "$value" ] && run_action llama-set-runtime context "$value"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:927`
```text
"Set Thread Count…" -> value=$(choose_text "Llama thread count" "4") [ -n "$value" ] && run_action llama-set-runtime threads "$value"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:931`
```text
"Set Batch Size…" -> value=$(choose_text "Llama batch size" "256") [ -n "$value" ] && run_action llama-set-runtime batch "$value"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:935`
```text
"Set GPU Layers…" -> value=$(choose_text "Llama GPU layers" "0") [ -n "$value" ] && run_action llama-set-runtime gpu-layers "$value"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:939`
```text
"Show Performance Settings" -> run_action llama-diagnostic performance
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:940`
```text
"← Back"|'' -> return 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:949`
```text
"Start Llama Server" -> run_action llama-start-server
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:950`
```text
"Stop Llama Server" -> run_action llama-stop-server
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:951`
```text
"Show Server Status" -> run_action llama-diagnostic server-status
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:952`
```text
"Show Server Configuration" -> run_action llama-diagnostic server-config
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:953`
```text
"Show Server Endpoint" -> run_action llama-diagnostic server-endpoint
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:954`
```text
"Show Server Help" -> run_action llama-diagnostic server-help
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:955`
```text
"← Back"|'' -> return 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:964`
```text
"Show Model Directories" -> run_action llama-diagnostic model-directories
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:965`
```text
"Show Model Storage Usage" -> run_action llama-diagnostic storage-usage
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:966`
```text
"Show Download Directory" -> run_action llama-diagnostic download-directory
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:967`
```text
"Prune Partial Downloads" -> run_action llama-prune-partials
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:968`
```text
"Show State File" -> run_action llama-diagnostic state-file
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:969`
```text
"← Back"|'' -> return 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:978`
```text
"Run Llama Health Check" -> run_action llama-diagnostic health
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:979`
```text
"Show Wrapper Configuration" -> run_action llama-diagnostic wrapper-config
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:980`
```text
"Show Active Model Details" -> run_action llama-model-info details active
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:981`
```text
"Show Installed Models" -> run_action llama-diagnostic installed-models
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:982`
```text
"Show Recent Chats" -> run_action llama-diagnostic recent-chats
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:983`
```text
"Show Llama Version" -> run_action llama-diagnostic version
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:984`
```text
"Show Llama Help" -> run_action llama-diagnostic help
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:985`
```text
"← Back"|'' -> return 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:994`
```text
"★ Ask Llama…" -> prompt=$(choose_text "Ask Llama" "Enter a question") [ -n "$prompt" ] && run_action llama-ask "$prompt"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:998`
```text
"★ New Chat" -> run_action llama-new-chat
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:999`
```text
"★ Resume Last Chat" -> run_action llama-resume-last-chat
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1000`
```text
"★ Change Model…" -> model=$(choose_model) [ -n "$model" ] && run_action llama-set-active-model "$model"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1004`
```text
"★ Download New Model…" -> download_llama_model
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1005`
```text
"⮞ ★ Persistent Memory" -> llama_memory_menu
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1006`
```text
"⮞ Models" -> llama_models_menu
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1007`
```text
"⮞ Chat & Context" -> llama_chat_context_menu
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1008`
```text
"⮞ Prompt Presets" -> llama_prompt_presets_menu
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1009`
```text
"⮞ Runtime" -> llama_runtime_menu
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1010`
```text
"⮞ Performance" -> llama_performance_menu
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1011`
```text
"⮞ Server" -> llama_server_menu
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1012`
```text
"⮞ Storage" -> llama_storage_menu
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1013`
```text
"⮞ Diagnostics" -> llama_diagnostics_menu
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1014`
```text
"← Back"|'' -> return 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1028`
```text
"Start Recording" -> run_action whisper-control start
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1029`
```text
"Stop Recording" -> run_action whisper-control stop
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1030`
```text
"Toggle Recording" -> run_action whisper-control toggle
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1031`
```text
"Show Recording Status" -> run_action whisper-diagnostic recording-status
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1032`
```text
"Show Latest Recording" -> run_action whisper-diagnostic latest-recording
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1033`
```text
"Open Recording Folder" -> run_action whisper-open recording-folder
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1034`
```text
"← Back"|'' -> return 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1043`
```text
"Transcribe File…" -> whisper_transcribe_file
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1044`
```text
"Transcribe Last Recording" -> run_action whisper-transcribe-last
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1045`
```text
"Show Latest Transcript" -> run_action whisper-diagnostic latest-transcript
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1046`
```text
"Open Transcript Folder" -> run_action whisper-open transcript-folder
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1047`
```text
"Show Transcription Service Status" -> run_action whisper-diagnostic transcription-status
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1048`
```text
"← Back"|'' -> return 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1057`
```text
"Auto-Detect Language" -> run_action whisper-set-language auto
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1063`
```text
"Set Language Code…" -> language=$(choose_text "Whisper language code" "en") [ -n "$language" ] && run_action whisper-set-language "$language"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1067`
```text
"Show Selected Language" -> run_action whisper-diagnostic language
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1068`
```text
"← Back"|'' -> return 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1077`
```text
"Save Transcript to File" -> run_action whisper-set-output file
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1078`
```text
"Copy Transcript to Clipboard" -> run_action whisper-set-output clipboard
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1079`
```text
"Save and Copy Transcript" -> run_action whisper-set-output both
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1080`
```text
"Show Output Mode" -> run_action whisper-diagnostic output-mode
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1081`
```text
"Open Transcript Folder" -> run_action whisper-open transcript-folder
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1082`
```text
"← Back"|'' -> return 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1091`
```text
"Raw Transcript" -> run_action whisper-set-post-processing raw
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1092`
```text
"Normalize Whitespace" -> run_action whisper-set-post-processing normalize
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1093`
```text
"Show Post-Processing Mode" -> run_action whisper-diagnostic post-processing
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1094`
```text
"← Back"|'' -> return 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1103`
```text
"Change Model…" -> model=$(choose_whisper_model) [ -n "$model" ] && run_action whisper-set-active-model "$model"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1107`
```text
"Download New Model…" -> download_whisper_model
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1108`
```text
"Show Installed Models" -> run_action whisper-diagnostic installed-models
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1109`
```text
"Show Configured Model" -> run_action whisper-diagnostic model
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1110`
```text
"Show Model Size" -> run_action whisper-diagnostic model-size
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1111`
```text
"Show Model Location" -> run_action whisper-diagnostic model-location
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1112`
```text
"Check Model Readability" -> run_action whisper-diagnostic model-health
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1113`
```text
"Prune Partial Downloads" -> run_action whisper-prune-partials
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1114`
```text
"Show Whisper Configuration" -> run_action whisper-diagnostic config
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1115`
```text
"← Back"|'' -> return 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1124`
```text
"Show Recent Recordings" -> run_action whisper-diagnostic recent-recordings
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1125`
```text
"Show Recent Transcripts" -> run_action whisper-diagnostic recent-transcripts
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1126`
```text
"Show Latest Recording" -> run_action whisper-diagnostic latest-recording
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1127`
```text
"Show Latest Transcript" -> run_action whisper-diagnostic latest-transcript
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1128`
```text
"Open Recording Folder" -> run_action whisper-open recording-folder
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1129`
```text
"Open Transcript Folder" -> run_action whisper-open transcript-folder
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1130`
```text
"← Back"|'' -> return 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1139`
```text
"Show PipeWire Status" -> run_action whisper-diagnostic pipewire
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1140`
```text
"Show Default Capture Source" -> run_action whisper-diagnostic default-source
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1141`
```text
"Toggle Default Microphone Mute" -> run_action whisper-audio toggle-mute
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1142`
```text
"Mute Default Microphone" -> run_action whisper-audio mute
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1143`
```text
"Unmute Default Microphone" -> run_action whisper-audio unmute
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1144`
```text
"Open Audio Control" -> run_action whisper-open audio-control
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1145`
```text
"← Back"|'' -> return 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1154`
```text
"Run Whisper Health Check" -> run_action whisper-diagnostic health
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1155`
```text
"Show User Service Status" -> run_action whisper-diagnostic services
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1156`
```text
"Show Recent Whisper Logs" -> run_action whisper-diagnostic logs
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1157`
```text
"Show Persistent Server Status" -> run_action whisper-diagnostic server-status
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1158`
```text
"Show Whisper Configuration" -> run_action whisper-diagnostic config
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1159`
```text
"Show Whisper CLI Help" -> run_action whisper-diagnostic help
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1160`
```text
"← Back"|'' -> return 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1169`
```text
"★ Push-to-Talk" -> run_action whisper-control toggle
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1170`
```text
"★ Toggle Dictation" -> run_action whisper-dictation toggle
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1171`
```text
"★ Transcribe File…" -> whisper_transcribe_file
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1172`
```text
"★ Transcribe Last Recording" -> run_action whisper-transcribe-last
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1173`
```text
"★ Change Model…" -> model=$(choose_whisper_model) [ -n "$model" ] && run_action whisper-set-active-model "$model"
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1177`
```text
"★ Download New Model…" -> download_whisper_model
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1178`
```text
"★ Live Captions" -> run_action whisper-dictation toggle
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1179`
```text
"★ Voice Note" -> run_action whisper-control toggle
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1180`
```text
"⮞ Recording" -> whisper_recording_menu
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1181`
```text
"⮞ Transcription" -> whisper_transcription_menu
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1182`
```text
"⮞ Languages" -> whisper_languages_menu
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1183`
```text
"⮞ Output" -> whisper_output_menu
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1184`
```text
"⮞ Post-Processing" -> whisper_post_processing_menu
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1185`
```text
"⮞ Models" -> whisper_models_menu
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1186`
```text
"⮞ History" -> whisper_history_menu
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1187`
```text
"⮞ Audio Devices" -> whisper_audio_devices_menu
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1188`
```text
"⮞ Diagnostics" -> whisper_diagnostics_menu
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1189`
```text
"← Back"|'' -> return 0
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1204`
```text
'' -> [ "$#" -eq 0 ] || fatal "usage: labwc-ai-copilots [--terminal|--catalog <name>]" [ "$(id -u)" -ne 0 ] || fatal "labwc-ai-copilots must run as the logged-in desktop user" command -v labwc-terminal >/dev/null 2>&1 || fatal "labwc-terminal is not installed" exec labwc-terminal -e "$TERMINAL_LAUNCHER" --terminal
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1229`
```text
"⮞ Codex" -> codex_menu
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1230`
```text
"⮞ Llama" -> llama_menu
```
`d-i/forky/hooks/target/usr/local/bin/labwc-ai-copilots:1231`
```text
"⮞ Whisper" -> whisper_menu
```
