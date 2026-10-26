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
    # systemd knows each exact unit/main PID. A failed liveness probe after
    # commit is a refresh warning, not an assertion that file publication failed.
    actions = (
        ('waybar', 'waybar.service', ['reload', 'waybar.service']),
        ('taskview', 'waybar.service', ['reload', 'waybar.service']),
        ('waycal', 'labwc-waycal-popup.service', ['stop', 'labwc-waycal-popup.service']),
        ('theme', 'labwc-compositor.service', ['kill', '--kill-whom=main', '--signal=SIGHUP',
                                               'labwc-compositor.service']),
        ('pointer', 'labwc-compositor.service', ['kill', '--kill-whom=main', '--signal=SIGHUP',
                                                  'labwc-compositor.service']),
    )
    for component, unit, arguments in actions:
        if component not in components:
            continue
        if component == 'taskview' and 'waybar' in components:
            continue
        try:
            if active(unit):
                checked(['/usr/bin/systemctl', '--user', *arguments], timeout=45)
        except (RuntimeError, OSError, subprocess.SubprocessError) as error:
            warnings.append(str(error))
    return warnings
