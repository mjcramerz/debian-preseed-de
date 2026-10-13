"""Expected single-force PID 1 handoff; never execute these commands in tests."""

# Refuse host execution before importing runtime helpers or creating fixtures.
from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
# Copied checker/GUI fixtures still use the verified private checkout gate.
_isolation_sys.path.insert(0, '/workspace/repository/tools')
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()


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
