"""Private clipboard routing and the application-only host socket mask."""
from __future__ import annotations

import io
import os
from pathlib import Path
import stat
import subprocess
import sys
import unittest
from unittest import mock

from payload_fixture import python_library

FORKY = Path(__file__).resolve().parents[1]
LIB = python_library(FORKY / "hooks/target/usr/local/lib/python3.14/dist-packages")
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))

from labwc_managed_app import wayland_compat_runtime as bridge


class ClipboardRoutingTests(unittest.TestCase):
    def test_watchers_use_opposite_sources_and_sink_modes(self):
        forward = bridge.clipboard_bridge_argv("wayland-1")
        reverse = bridge.clipboard_bridge_argv("wayland-1", reverse=True)
        self.assertEqual(forward[:5], reverse[:5])
        self.assertEqual(forward[-2:], [bridge.CLIPBOARD_SINK_MODE, "wayland-1"])
        self.assertEqual(reverse[-2:], [bridge.CLIPBOARD_REVERSE_SINK_MODE, "wayland-1"])
        self.assertEqual(bridge.parse_clipboard_sink_arguments(forward[-2:]), ("wayland-1", False))
        self.assertEqual(bridge.parse_clipboard_sink_arguments(reverse[-2:]), ("wayland-1", True))

    def test_each_direction_writes_only_to_the_opposite_display(self):
        runtime = f"/run/user/{os.getuid()}"
        for reverse, source, target in (
            (False, "wayland-0", "wayland-1"),
            (True, "wayland-1", "wayland-0"),
        ):
            with self.subTest(reverse=reverse), mock.patch.dict(os.environ, {
                "XDG_RUNTIME_DIR": runtime,
                "WAYLAND_DISPLAY": source,
                bridge.OUTER_WAYLAND_DISPLAY_ENVIRONMENT: "wayland-0",
            }), mock.patch.object(bridge.os, "geteuid", return_value=1000), \
                mock.patch.object(bridge, "sandbox_system_owner", return_value=(0, 0)), \
                mock.patch.object(bridge, "require_system_owned_file"), \
                mock.patch.object(bridge, "require_user_wayland_socket"), \
                mock.patch.object(bridge, "register_signal_handlers"), \
                mock.patch.object(bridge, "clipboard_lock", return_value=-1), \
                mock.patch.object(bridge.os, "close"), \
                mock.patch.object(bridge, "destination_clipboard_text", return_value=b"old"), \
                mock.patch.object(bridge, "clipboard_process_environment", return_value={
                    "WAYLAND_DISPLAY": target,
                }), mock.patch.object(bridge.subprocess, "run") as copy, \
                mock.patch.object(bridge.sys, "stdin", io.TextIOWrapper(io.BytesIO(b"new"))):
                copy.return_value.returncode = 0
                arguments = [
                    bridge.CLIPBOARD_REVERSE_SINK_MODE if reverse else bridge.CLIPBOARD_SINK_MODE,
                    "wayland-1",
                ]
                self.assertEqual(bridge.run_clipboard_sink(arguments), 0)
                self.assertEqual(copy.call_args.kwargs["env"]["WAYLAND_DISPLAY"], target)
                self.assertEqual(copy.call_args.kwargs["input"], b"new")

    def test_matching_selection_does_not_echo_to_the_other_watch(self):
        with mock.patch.dict(os.environ, {
            "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}",
            "WAYLAND_DISPLAY": "wayland-1",
            bridge.OUTER_WAYLAND_DISPLAY_ENVIRONMENT: "wayland-0",
        }), mock.patch.object(bridge.os, "geteuid", return_value=1000), \
            mock.patch.object(bridge, "sandbox_system_owner", return_value=(0, 0)), \
            mock.patch.object(bridge, "require_system_owned_file"), \
            mock.patch.object(bridge, "require_user_wayland_socket"), \
            mock.patch.object(bridge, "register_signal_handlers"), \
            mock.patch.object(bridge, "clipboard_lock", return_value=-1), \
            mock.patch.object(bridge.os, "close"), \
            mock.patch.object(bridge, "clipboard_process_environment", return_value={}), \
            mock.patch.object(bridge, "destination_clipboard_text", return_value=b"same"), \
            mock.patch.object(bridge.subprocess, "run") as copy, \
            mock.patch.object(bridge.sys, "stdin", io.TextIOWrapper(io.BytesIO(b"same"))):
            self.assertEqual(bridge.run_clipboard_sink([bridge.CLIPBOARD_REVERSE_SINK_MODE, "wayland-1"]), 0)
            copy.assert_not_called()

    def test_application_namespace_masks_only_host_socket(self):
        argv = bridge.masked_application_argv(
            "discord", "wayland-0", "wayland-1", ["/opt/discord/Discord"]
        )
        self.assertEqual(argv[:4], ["/usr/bin/bwrap", "--unshare-user", "--unshare-pid", "--die-with-parent"])
        mask = argv.index("--ro-bind")
        self.assertEqual(argv[mask + 1:mask + 3], [
            "/dev/null", f"/run/user/{os.getuid()}/wayland-0"
        ])
        self.assertIn("--proc", argv)
        self.assertEqual(argv[-6:], [bridge.MASKED_APPLICATION_MODE, "discord", "wayland-0", "wayland-1", "--", "/opt/discord/Discord"])
        with self.assertRaises(bridge.CompatibilityRuntimeError):
            bridge.masked_application_argv(
                "discord", "wayland-0", "wayland-0", ["/opt/discord/Discord"]
            )

    def test_destination_clipboard_read_is_bounded(self):
        popen = subprocess.Popen
        def oversized_reader(_arguments, **kwargs):
            return popen([sys.executable, "-c", "import os; os.write(1,b'x'*65536)"], **kwargs)
        with mock.patch.object(bridge, "MAX_CLIPBOARD_TEXT_BYTES", 16), \
            mock.patch.object(bridge.subprocess, "Popen", side_effect=oversized_reader):
            self.assertIsNone(bridge.destination_clipboard_text({}))

    def test_application_fails_closed_if_host_socket_remains_visible(self):
        arguments = [bridge.MASKED_APPLICATION_MODE, "zoom", "wayland-0", "wayland-1", "--", "/usr/bin/zoom"]
        with mock.patch.dict(os.environ, {
            "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}", "WAYLAND_DISPLAY": "wayland-1",
        }), mock.patch.object(bridge.os, "geteuid", return_value=1000), \
            mock.patch.object(bridge.os, "lstat", return_value=mock.Mock(st_mode=stat.S_IFSOCK)), \
            mock.patch.object(bridge.os, "execve") as execute:
            with self.assertRaisesRegex(bridge.CompatibilityRuntimeError, "host Wayland socket"):
                bridge.run_masked_application(arguments)
            execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
