"""Live refreshes target existing systemd units, never process-name matches."""
from __future__ import annotations
import subprocess
from managed_workflows.process import checked, environment


def active(unit: str) -> bool:
    return subprocess.run(['/usr/bin/systemctl', '--user', 'is-active', '--quiet', unit],
                          env=environment(desktop=True), timeout=15, check=False).returncode == 0


def dock_stop() -> bool:
    running = active('crystal-dock.service')
    if running:
        # QSettings applications may save their old in-memory settings at exit.
        # Stop first, then write; restarting after writing can undo the profile.
        checked(['/usr/bin/systemctl', '--user', 'stop', 'crystal-dock.service'], timeout=30)
    return running


def dock_start() -> None:
    checked(['/usr/bin/systemctl', '--user', 'start', 'crystal-dock.service'], timeout=45)


def refresh(components: set[str]) -> list[str]:
    warnings = []
    actions = []
    if 'waybar' in components and active('waybar.service'):
        actions.append(['/usr/bin/systemctl', '--user', 'reload', 'waybar.service'])
    if 'mode' in components and active('labwc-compositor.service'):
        # systemd knows the exact compositor main PID and owns its lifecycle.
        actions.append(['/usr/bin/systemctl', '--user', 'kill', '--kill-whom=main',
                        '--signal=SIGHUP', 'labwc-compositor.service'])
    for command in actions:
        try:
            checked(command, timeout=45)
        except (RuntimeError, OSError, subprocess.SubprocessError) as error:
            warnings.append(str(error))
    return warnings
