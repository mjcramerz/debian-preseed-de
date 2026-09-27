"""Expected single-force PID 1 handoff; never execute these commands in tests."""


def handoff_argv(action):
    if action not in {"reboot", "poweroff"}:
        raise ValueError("invalid test power action")
    return ["/usr/bin/systemctl", "--force", action]


def is_handoff(argv):
    # Detect malformed/double-force and legacy logind submissions too, so a
    # negative safety assertion cannot overlook an unexpected alternate path.
    return (any(item in {"RebootWithFlags", "PowerOffWithFlags"} for item in argv)
            or bool(argv) and argv[0] == "/usr/bin/systemctl"
            and any(item in {"reboot", "poweroff"} for item in argv[1:]))
