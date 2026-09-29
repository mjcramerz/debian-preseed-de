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
        self.assertEqual(forward[:5], [bridge.WL_PASTE_BINARY, "--no-newline", "--type", "text", "--watch"])
        self.assertEqual(forward[-2:], [bridge.CLIPBOARD_SINK_MODE, "wayland-1"])
        self.assertEqual(reverse, [bridge.SANDBOX_LIFECYCLE_HELPER, bridge.CLIPBOARD_REVERSE_SINK_MODE, "wayland-1"])
        self.assertNotIn("--watch", reverse)
        self.assertEqual(bridge.parse_clipboard_sink_arguments(forward[-2:]), ("wayland-1", False))
        self.assertEqual(bridge.parse_clipboard_sink_arguments(reverse[-2:]), ("wayland-1", True))

    def test_host_selection_writes_only_to_private_x11(self):
        runtime = f"/run/user/{os.getuid()}"
        with mock.patch.dict(os.environ, {
                "XDG_RUNTIME_DIR": runtime,
                "WAYLAND_DISPLAY": "wayland-0",
                bridge.OUTER_WAYLAND_DISPLAY_ENVIRONMENT: "wayland-0",
                "DISPLAY": ":17",
            }), mock.patch.object(bridge.os, "geteuid", return_value=1000), \
                mock.patch.object(bridge, "sandbox_system_owner", return_value=(0, 0)), \
                mock.patch.object(bridge, "require_system_owned_file"), \
                mock.patch.object(bridge, "require_user_wayland_socket"), \
                mock.patch.object(bridge, "require_private_x11_socket_directory"), \
                mock.patch.object(bridge, "require_private_x11_socket") as socket, \
                mock.patch.object(bridge, "register_signal_handlers"), \
                mock.patch.object(bridge, "clipboard_lock", return_value=-1), \
                mock.patch.object(bridge.os, "close"), \
                mock.patch.object(bridge, "destination_clipboard_text", return_value=b"old"), \
                mock.patch.object(bridge.subprocess, "run") as copy, \
                mock.patch.object(bridge.sys, "stdin", io.TextIOWrapper(io.BytesIO(b"new"))):
                copy.return_value.returncode = 0
                self.assertEqual(bridge.run_clipboard_sink([bridge.CLIPBOARD_SINK_MODE, "wayland-1"]), 0)
                socket.assert_called_with("17")
                self.assertEqual(copy.call_args.args[0][:3], [bridge.XCLIP_BINARY, "-selection", "clipboard"])
                self.assertEqual(copy.call_args.kwargs["env"]["DISPLAY"], ":17")
                self.assertNotIn("WAYLAND_DISPLAY", copy.call_args.kwargs["env"])
                self.assertEqual(copy.call_args.kwargs["input"], b"new")

    def test_matching_selection_does_not_echo_to_the_other_watch(self):
        with mock.patch.dict(os.environ, {
            "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}",
            "WAYLAND_DISPLAY": "wayland-0",
            "DISPLAY": ":17",
            bridge.OUTER_WAYLAND_DISPLAY_ENVIRONMENT: "wayland-0",
        }), mock.patch.object(bridge.os, "geteuid", return_value=1000), \
            mock.patch.object(bridge, "sandbox_system_owner", return_value=(0, 0)), \
            mock.patch.object(bridge, "require_system_owned_file"), \
            mock.patch.object(bridge, "require_user_wayland_socket"), \
            mock.patch.object(bridge, "require_private_x11_socket_directory"), \
            mock.patch.object(bridge, "require_private_x11_socket"), \
            mock.patch.object(bridge, "register_signal_handlers"), \
            mock.patch.object(bridge, "clipboard_lock", return_value=-1), \
            mock.patch.object(bridge.os, "close"), \
            mock.patch.object(bridge, "destination_clipboard_text", return_value=b"same"), \
            mock.patch.object(bridge.subprocess, "run") as copy, \
            mock.patch.object(bridge.sys, "stdin", io.TextIOWrapper(io.BytesIO(b"same"))):
            self.assertEqual(bridge.run_clipboard_sink([bridge.CLIPBOARD_SINK_MODE, "wayland-1"]), 0)
            copy.assert_not_called()

    def test_reverse_poll_mirrors_changes_once_and_skips_host_echo(self):
        readings = iter([None, b"new", b"new", b"other"])
        ticks = 0

        def read(environment, *, x11=False):
            if x11:
                return next(readings)
            return b"other"  # already mirrored by the host-to-Cage watcher

        def tick(_interval):
            nonlocal ticks
            ticks += 1
            if ticks == 4:
                bridge._received_signal = 15

        with mock.patch.object(bridge, "clipboard_process_environment", return_value={"WAYLAND_DISPLAY": "wayland-0"}), \
            mock.patch.object(bridge, "destination_clipboard_text", side_effect=read), \
            mock.patch.object(bridge, "clipboard_lock", return_value=-1), \
            mock.patch.object(bridge.os, "close"), \
            mock.patch.object(bridge.subprocess, "run") as copy, \
            mock.patch.object(bridge.time, "sleep", side_effect=tick):
            try:
                copy.return_value.returncode = 0
                self.assertEqual(bridge.watch_cage_clipboard("wayland-1", "wayland-0", {"DISPLAY": ":17"}), 143)
                self.assertEqual(copy.call_count, 1)
                self.assertEqual(copy.call_args.args[0][0], bridge.WL_COPY_BINARY)
                self.assertEqual(copy.call_args.kwargs["env"]["WAYLAND_DISPLAY"], "wayland-0")
                self.assertEqual(copy.call_args.kwargs["input"], b"new")
            finally:
                bridge._received_signal = None

    def test_private_x11_bridge_rejects_inherited_host_display(self):
        with mock.patch.dict(os.environ, {"DISPLAY": "localhost:10.0"}):
            with self.assertRaisesRegex(bridge.CompatibilityRuntimeError, "Cage DISPLAY"):
                bridge.private_clipboard_x11_environment()

    def test_application_namespace_masks_only_host_socket(self):
        argv = bridge.masked_application_argv(
            "discord", "wayland-0", "wayland-1", ["/opt/discord/Discord"]
        )
        self.assertEqual(argv[:4], ["/usr/bin/bwrap", "--unshare-user", "--unshare-pid", "--die-with-parent"])
        self.assertEqual(argv[argv.index("--bind") + 1:argv.index("--dev-bind")], ["/", "/"])
        self.assertEqual(argv[argv.index("--dev-bind") + 1:argv.index("--ro-bind")], ["/dev", "/dev"])
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
        commands = []
        def oversized_reader(arguments, **kwargs):
            commands.append(arguments[0])
            return popen([sys.executable, "-c", "import os; os.write(1,b'x'*65536)"], **kwargs)
        with mock.patch.object(bridge, "MAX_CLIPBOARD_TEXT_BYTES", 16), \
            mock.patch.object(bridge.subprocess, "Popen", side_effect=oversized_reader):
            self.assertIsNone(bridge.destination_clipboard_text({}))
            self.assertIsNone(bridge.destination_clipboard_text({"DISPLAY": ":17"}, x11=True))
        self.assertEqual(commands, [bridge.WL_PASTE_BINARY, bridge.XCLIP_BINARY])

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

    def test_application_fails_closed_if_private_null_device_is_unusable(self):
        arguments = [bridge.MASKED_APPLICATION_MODE, "discord", "wayland-0", "wayland-1", "--", "/opt/discord/Discord"]
        with mock.patch.dict(os.environ, {
            "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}", "WAYLAND_DISPLAY": "wayland-1",
        }), mock.patch.object(bridge.os, "geteuid", return_value=1000), \
            mock.patch.object(bridge.os, "lstat", return_value=mock.Mock(st_mode=stat.S_IFREG)), \
            mock.patch.object(bridge, "require_user_wayland_socket"), \
            mock.patch.object(bridge.os, "open", side_effect=OSError("nodev")), \
            mock.patch.object(bridge.os, "execve") as execute:
            with self.assertRaisesRegex(bridge.CompatibilityRuntimeError, "cannot open /dev/null"):
                bridge.run_masked_application(arguments)
            execute.assert_not_called()

    def test_null_device_must_be_the_expected_character_device(self):
        metadata = mock.Mock(st_mode=stat.S_IFREG, st_rdev=os.makedev(1, 3))
        with mock.patch.object(bridge.os, "open", return_value=7) as opening, \
            mock.patch.object(bridge.os, "fstat", return_value=metadata), \
            mock.patch.object(bridge.os, "close") as close:
            with self.assertRaisesRegex(bridge.CompatibilityRuntimeError, "invalid /dev/null"):
                bridge.require_private_null_device()
            opening.assert_called_once_with(
                "/dev/null", os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC
            )
            close.assert_called_once_with(7)


if __name__ == "__main__":
    unittest.main()
