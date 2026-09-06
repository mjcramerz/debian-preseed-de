"""Bounded fixed-argv nftables operations."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess

from .files import PendingMutation
from .validation import FirewallError


ROOT_PATH = "/usr/sbin:/usr/bin:/sbin:/bin"
COMMAND_PATHS = {
    "getent": "/usr/bin/getent",
    "nft": "/usr/sbin/nft",
    "systemctl": "/usr/bin/systemctl",
}
COMMAND_ENVIRONMENT = {
    "HOME": "/root",
    "LANG": "C",
    "LC_ALL": "C",
    "PATH": ROOT_PATH,
    "SYSTEMD_COLORS": "0",
    "SYSTEMD_PAGER": "cat",
}


@dataclass(frozen=True)
class CommandRunner:
    timeout_seconds: int = 120

    def require(self, name: str) -> str:
        executable = COMMAND_PATHS.get(name)
        if executable is None:
            raise FirewallError(f"unsupported firewall command: {name}")
        if not Path(executable).is_file() or not os.access(executable, os.X_OK):
            raise FirewallError(f"required firewall command is not installed: {name}")
        return executable

    def run(
        self,
        *argv: str,
        timeout_seconds: int | None = None,
        stdout: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if not argv or not argv[0]:
            raise FirewallError("cannot run an empty firewall command")
        try:
            return subprocess.run(
                list(argv),
                check=False,
                stdout=stdout,
                cwd="/",
                env=dict(COMMAND_ENVIRONMENT),
                stdin=subprocess.DEVNULL,
                timeout=self.timeout_seconds
                if timeout_seconds is None
                else timeout_seconds,
                text=True,
            )
        except OSError as exc:
            raise FirewallError(f"cannot execute {argv[0]}: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise FirewallError(
                f"firewall command timed out after {exc.timeout} seconds: {argv[0]}"
            ) from exc

    def run_or_fail(self, label: str, *argv: str) -> None:
        completed = self.run(*argv)
        if completed.returncode != 0:
            raise FirewallError(f"{label} failed with status {completed.returncode}")


def _rollback_or_fail(mutation: PendingMutation, message: str) -> None:
    try:
        mutation.rollback()
    except FirewallError as exc:
        raise FirewallError(
            f"{message}; previous rules could not be restored: {exc}"
        ) from exc
    raise FirewallError(f"{message}; previous rules restored")


def validate_and_apply(
    runner: CommandRunner,
    mutation: PendingMutation,
    nft_conf: Path,
) -> None:
    nft = runner.require("nft")
    systemctl = runner.require("systemctl")
    try:
        mutation.install()
    except FirewallError:
        _rollback_or_fail(
            mutation,
            "candidate nftables policy installation failed",
        )

    syntax = runner.run(nft, "-c", "-f", str(nft_conf))
    if syntax.returncode != 0:
        _rollback_or_fail(
            mutation,
            "candidate nftables policy failed syntax validation",
        )

    reload = runner.run(systemctl, "reload", "nftables.service")
    if reload.returncode == 0:
        return

    try:
        mutation.rollback()
    except FirewallError as exc:
        raise FirewallError(
            "nftables reload failed and the previous rules could not be restored: "
            f"{exc}"
        ) from exc
    restore = runner.run(nft, "-f", str(nft_conf))
    if restore.returncode != 0:
        raise FirewallError(
            "nftables reload failed and the previous rules could not be restored"
        )
    raise FirewallError("nftables reload failed; previous rules restored")
