"""Private network namespace supervision for Bubblewrap sandboxes."""

from __future__ import annotations

from collections.abc import Callable

import json
import os
import select
import subprocess
import time

from .runtime import fail, managed_subprocess_environment


BWRAP_INFO_MAX_BYTES = 16_384
BWRAP_NETWORK_SETUP_TIMEOUT_SECONDS = 15
SLIRP4NETNS_BINARY = "/usr/bin/slirp4netns"
SLIRP4NETNS_DIAGNOSTIC_MAX_BYTES = 4_096
SLIRP4NETNS_DNS_ADDRESS = "10.0.2.3"
SLIRP4NETNS_MTU = 65_520
SLIRP4NETNS_STOP_TIMEOUT_SECONDS = 2
SLIRP4NETNS_TAP_NAME = "tap0"

def close_file_descriptor(file_descriptor: int | None) -> None:
    if file_descriptor is None:
        return
    try:
        os.close(file_descriptor)
    except OSError:
        pass


def _stop_subprocess(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=SLIRP4NETNS_STOP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=SLIRP4NETNS_STOP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            pass


def _read_bwrap_sandbox_pid(
    info_fd: int,
    bwrap_process: subprocess.Popen,
) -> int:
    deadline = time.monotonic() + BWRAP_NETWORK_SETUP_TIMEOUT_SECONDS
    payload = bytearray()

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            status = bwrap_process.poll()
            if status is not None:
                fail(
                    "Bubblewrap exited before reporting a sandbox process ID "
                    f"(status {status})"
                )
            fail("Bubblewrap did not report a sandbox process ID before timeout")

        try:
            readable, _, _ = select.select(
                [info_fd],
                [],
                [],
                min(remaining, 0.25),
            )
        except InterruptedError:
            continue
        if not readable:
            status = bwrap_process.poll()
            if status is not None:
                fail(
                    "Bubblewrap exited before reporting a sandbox process ID "
                    f"(status {status})"
                )
            continue

        remaining_bytes = BWRAP_INFO_MAX_BYTES + 1 - len(payload)
        if remaining_bytes <= 0:
            fail("Bubblewrap sandbox information exceeds the managed size limit")
        try:
            chunk = os.read(info_fd, min(4_096, remaining_bytes))
        except InterruptedError:
            continue
        if not chunk:
            break
        payload.extend(chunk)
        if len(payload) > BWRAP_INFO_MAX_BYTES:
            fail("Bubblewrap sandbox information exceeds the managed size limit")

    if not payload:
        fail("Bubblewrap returned empty sandbox information")
    try:
        information = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        fail("Bubblewrap returned invalid sandbox information")
    if not isinstance(information, dict):
        fail("Bubblewrap sandbox information must be a JSON object")

    sandbox_pid = information.get("child-pid")
    if (
        isinstance(sandbox_pid, bool)
        or not isinstance(sandbox_pid, int)
        or sandbox_pid <= 1
    ):
        fail("Bubblewrap returned an invalid sandbox process ID")
    if bwrap_process.poll() is not None:
        fail(
            "Bubblewrap exited while preparing the isolated network namespace "
            f"(status {bwrap_process.returncode})"
        )
    return sandbox_pid


def _slirp4netns_diagnostic(stderr_handle) -> str:
    try:
        stderr_handle.flush()
        stderr_handle.seek(0)
        payload = stderr_handle.read(SLIRP4NETNS_DIAGNOSTIC_MAX_BYTES + 1)
    except OSError:
        return ""
    truncated = len(payload) > SLIRP4NETNS_DIAGNOSTIC_MAX_BYTES
    payload = payload[:SLIRP4NETNS_DIAGNOSTIC_MAX_BYTES]
    message = " ".join(payload.decode("utf-8", errors="replace").split())
    if truncated:
        message = f"{message} [truncated]" if message else "[truncated]"
    return message


def _slirp4netns_exit_message(
    status: int,
    stderr_handle,
    context: str,
) -> str:
    diagnostic = _slirp4netns_diagnostic(stderr_handle)
    suffix = f": {diagnostic}" if diagnostic else ""
    return f"slirp4netns exited {context} (status {status}){suffix}"


def _wait_for_slirp4netns_ready(
    ready_fd: int,
    bwrap_process: subprocess.Popen,
    slirp_process: subprocess.Popen,
    stderr_handle,
) -> None:
    deadline = time.monotonic() + BWRAP_NETWORK_SETUP_TIMEOUT_SECONDS

    while True:
        bwrap_status = bwrap_process.poll()
        if bwrap_status is not None:
            fail(
                "Bubblewrap exited before isolated network setup completed "
                f"(status {bwrap_status})"
            )
        slirp_status = slirp_process.poll()
        if slirp_status is not None:
            fail(
                _slirp4netns_exit_message(
                    slirp_status,
                    stderr_handle,
                    "before configuring the isolated network namespace",
                )
            )

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            fail(
                "slirp4netns did not configure the isolated network namespace "
                "before timeout"
            )
        try:
            readable, _, _ = select.select(
                [ready_fd],
                [],
                [],
                min(remaining, 0.25),
            )
        except InterruptedError:
            continue
        if not readable:
            continue
        try:
            readiness = os.read(ready_fd, 2)
        except InterruptedError:
            continue
        if readiness != b"1":
            try:
                slirp_status = slirp_process.wait(timeout=0.1)
            except subprocess.TimeoutExpired:
                slirp_status = None
            if slirp_status is not None:
                fail(
                    _slirp4netns_exit_message(
                        slirp_status,
                        stderr_handle,
                        "before configuring the isolated network namespace",
                    )
                )
            fail("slirp4netns returned an invalid readiness marker")
        return


def _wait_for_bwrap_with_slirp4netns(
    bwrap_process: subprocess.Popen,
    slirp_process: subprocess.Popen,
    stderr_handle,
) -> int:
    while True:
        slirp_status = slirp_process.poll()
        if slirp_status is not None:
            fail(
                _slirp4netns_exit_message(
                    slirp_status,
                    stderr_handle,
                    "while the managed application sandbox was running",
                )
            )
        try:
            bwrap_status = bwrap_process.wait(timeout=0.25)
        except subprocess.TimeoutExpired:
            continue
        slirp_status = slirp_process.poll()
        if slirp_status is not None:
            fail(
                _slirp4netns_exit_message(
                    slirp_status,
                    stderr_handle,
                    "while the managed application sandbox was running",
                )
            )
        return bwrap_status


def run_slirp4netns_sandbox(
    command: list[str],
    payload_argv: list[str],
    temp_root: str,
    inherited_fds: tuple[int, ...],
    *,
    slirp_binary: str,
    pre_payload_check: Callable[[], None] | None = None,
) -> int:
    info_read_fd = None
    info_write_fd = None
    block_read_fd = None
    block_write_fd = None
    ready_read_fd = None
    ready_write_fd = None
    exit_read_fd = None
    exit_write_fd = None
    bwrap_process = None
    slirp_process = None
    stderr_handle = None

    try:
        info_read_fd, info_write_fd = os.pipe()
        block_read_fd, block_write_fd = os.pipe()
        ready_read_fd, ready_write_fd = os.pipe()
        exit_read_fd, exit_write_fd = os.pipe()

        bwrap_command = [
            *command,
            "--info-fd",
            str(info_write_fd),
            "--block-fd",
            str(block_read_fd),
            *payload_argv,
        ]
        bwrap_pass_fds = tuple(
            dict.fromkeys(
                (*inherited_fds, info_write_fd, block_read_fd)
            )
        )
        bwrap_process = subprocess.Popen(
            bwrap_command,
            cwd="/",
            env=managed_subprocess_environment(),
            pass_fds=bwrap_pass_fds,
        )
        close_file_descriptor(info_write_fd)
        info_write_fd = None
        close_file_descriptor(block_read_fd)
        block_read_fd = None

        sandbox_pid = _read_bwrap_sandbox_pid(
            info_read_fd,
            bwrap_process,
        )
        close_file_descriptor(info_read_fd)
        info_read_fd = None

        stderr_path = os.path.join(temp_root, "slirp4netns.stderr")
        stderr_handle = open(stderr_path, "w+b", buffering=0)
        os.chmod(stderr_path, 0o600)
        slirp_process = subprocess.Popen(
            [
                slirp_binary,
                "--configure",
                f"--mtu={SLIRP4NETNS_MTU}",
                "--disable-host-loopback",
                "--ready-fd",
                str(ready_write_fd),
                "--exit-fd",
                str(exit_read_fd),
                str(sandbox_pid),
                SLIRP4NETNS_TAP_NAME,
            ],
            cwd="/",
            env=managed_subprocess_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=stderr_handle,
            pass_fds=(ready_write_fd, exit_read_fd),
        )
        close_file_descriptor(ready_write_fd)
        ready_write_fd = None
        close_file_descriptor(exit_read_fd)
        exit_read_fd = None

        _wait_for_slirp4netns_ready(
            ready_read_fd,
            bwrap_process,
            slirp_process,
            stderr_handle,
        )
        close_file_descriptor(ready_read_fd)
        ready_read_fd = None
        if pre_payload_check is not None:
            pre_payload_check()
        bwrap_status = bwrap_process.poll()
        if bwrap_status is not None:
            fail(
                "Bubblewrap exited after isolated network setup completed "
                f"but before payload release (status {bwrap_status})"
            )
        slirp_status = slirp_process.poll()
        if slirp_status is not None:
            fail(
                _slirp4netns_exit_message(
                    slirp_status,
                    stderr_handle,
                    "after configuring the isolated network namespace "
                    "but before payload release",
                )
            )
        try:
            os.write(block_write_fd, b"1")
        except (BrokenPipeError, OSError):
            status = bwrap_process.poll()
            suffix = f" (status {status})" if status is not None else ""
            fail(f"cannot release the configured Bubblewrap sandbox{suffix}")
        close_file_descriptor(block_write_fd)
        block_write_fd = None

        return _wait_for_bwrap_with_slirp4netns(
            bwrap_process,
            slirp_process,
            stderr_handle,
        )
    finally:
        if bwrap_process is not None and bwrap_process.poll() is None:
            _stop_subprocess(bwrap_process)
        for file_descriptor in (
            info_read_fd,
            info_write_fd,
            block_read_fd,
            block_write_fd,
            ready_read_fd,
            ready_write_fd,
            exit_read_fd,
        ):
            close_file_descriptor(file_descriptor)
        close_file_descriptor(exit_write_fd)
        if slirp_process is not None and slirp_process.poll() is None:
            try:
                slirp_process.wait(timeout=SLIRP4NETNS_STOP_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                _stop_subprocess(slirp_process)
        if stderr_handle is not None:
            stderr_handle.close()


