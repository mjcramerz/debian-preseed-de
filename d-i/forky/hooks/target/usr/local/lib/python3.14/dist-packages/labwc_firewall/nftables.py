"""Bounded fixed-argv nftables operations."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import selectors
import subprocess
import time

from .files import PendingMutation, _sync_directory, _write_temporary
from .state import load_state
from .validation import FirewallError, OutcomeUnknown


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
        child = None
        try:
            child = subprocess.Popen(
                list(argv),
                stdout=stdout,
                cwd="/",
                env=dict(COMMAND_ENVIRONMENT),
                stdin=subprocess.DEVNULL,
            )
            timeout = self.timeout_seconds if timeout_seconds is None else timeout_seconds
            deadline = time.monotonic() + timeout
            output = bytearray()
            if stdout == subprocess.PIPE:
                with selectors.DefaultSelector() as selector:
                    selector.register(child.stdout, selectors.EVENT_READ)
                    while selector.get_map():
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise subprocess.TimeoutExpired(argv, timeout)
                        for key, _ in selector.select(remaining):
                            chunk = os.read(key.fd, 65536)
                            if not chunk:
                                selector.unregister(key.fileobj)
                                continue
                            if len(output) + len(chunk) > 16 * 1024 * 1024:
                                raise FirewallError("firewall command output exceeds 16 MiB")
                            output.extend(chunk)
            status = child.wait(timeout=max(0.01, deadline - time.monotonic()))
            return subprocess.CompletedProcess(argv, status,
                output.decode('utf-8') if stdout == subprocess.PIPE else None)
        except OSError as exc:
            raise FirewallError(f"cannot execute {argv[0]}: {exc}") from exc
        except UnicodeError as exc:
            raise FirewallError("firewall command returned invalid UTF-8") from exc
        except subprocess.TimeoutExpired as exc:
            raise OutcomeUnknown(
                f"firewall command outcome unknown after {exc.timeout} seconds: {argv[0]}"
            ) from exc
        finally:
            if child is not None:
                if child.returncode is None:
                    # These fixed native commands do not daemonize. Retain the
                    # direct child's identity until bounded cancellation ends.
                    child.kill()
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired as exc:
                        raise OutcomeUnknown("firewall command termination outcome unknown") from exc
                if child.stdout is not None:
                    child.stdout.close()

    def run_or_fail(self, label: str, *argv: str) -> None:
        completed = self.run(*argv)
        if completed.returncode != 0:
            raise FirewallError(f"{label} failed with status {completed.returncode}")


def _rollback_or_fail(mutation: PendingMutation, message: str) -> None:
    try:
        mutation.rollback()
    except FirewallError as exc:
        raise OutcomeUnknown(
            f"{message}; previous rules could not be restored: {exc}"
        ) from exc
    mutation.rollback_failed = False
    raise FirewallError(f"{message}; previous rules restored")


def validate_and_apply(
    runner: CommandRunner,
    mutation: PendingMutation,
    nft_conf: Path,
) -> None:
    nft = runner.require("nft")
    systemctl = runner.require("systemctl")
    if mutation.fragment_candidate is None or mutation.state_candidate is None:
        raise FirewallError("firewall candidates were not prepared")
    expected = {"local_input": [], "local_output": []}
    for rule in load_state(mutation.state_candidate):
        chain = "local_input" if rule.direction == "incoming" else "local_output"
        expected[chain].extend([f"firewall-security {rule.rule_id}"] * (2 if rule.scope == "lan" else 1))
    candidate_check = runner.run(nft, "-c", "-f", str(mutation.fragment_candidate))
    if candidate_check.returncode:
        raise FirewallError("candidate firewall fragment failed validation before publication")
    previous = _snapshot_live(runner, nft, mutation)
    try:
        mutation.install()
    except FirewallError:
        _rollback_or_fail(
            mutation,
            "candidate nftables policy installation failed",
        )

    try:
        syntax = runner.run(nft, "-c", "-f", str(nft_conf))
    except FirewallError as exc:
        _rollback_or_fail(mutation, f"candidate nftables policy validation failed: {exc}")
    if syntax.returncode != 0:
        _rollback_or_fail(
            mutation,
            "candidate nftables policy failed syntax validation",
        )

    failure = "nftables reload failed"
    # Preserve recovery through live application, including asynchronous manager
    # completion after a client timeout. Do not start a conflicting restoration.
    mutation.rollback_failed = True
    try:
        reload = runner.run(systemctl, "reload", "nftables.service")
    except OutcomeUnknown as exc:
        raise OutcomeUnknown(
            f"{exc}; reconcile nftables.service before retrying; recovery backups retained: "
            f"{mutation.state_backup}, {mutation.fragment_backup}"
        ) from exc
    except FirewallError as exc:
        # A definite client failure still requires restoration of both states.
        failure += f": {exc}"
    else:
        if reload.returncode == 0:
            try:
                _verify_managed_rules(runner, nft, expected)
            except FirewallError as exc:
                failure = f"nftables loaded-policy verification failed: {exc}"
            else:
                mutation.rollback_failed = False
                return

    try:
        mutation.rollback()
    except FirewallError as exc:
        raise OutcomeUnknown(
            f"{failure}; previous rules could not be restored: {exc}"
        ) from exc
    try:
        restore = runner.run(nft, "-f", str(mutation.recovery_directory / 'live.nft'))
        if restore.returncode == 0 and _live_identity(runner, nft) != previous:
            raise FirewallError("restored owned live tables do not match their snapshot")
    except FirewallError as exc:
        raise OutcomeUnknown(
            f"{failure}; previous live rules could not be restored: {exc}; "
            f"recovery retained at {mutation.recovery_directory}"
        ) from exc
    if restore.returncode != 0:
        raise OutcomeUnknown(
            f"{failure}; previous live rules could not be restored; "
            f"recovery retained at {mutation.recovery_directory}"
        )
    mutation.rollback_failed = False
    raise FirewallError(f"{failure}; previous rules restored")


OWNED_TABLES = (("inet", "labwc_filter"), ("ip", "labwc_nat"))


def _capture(runner: CommandRunner, *argv: str) -> str:
    completed = runner.run(*argv, stdout=subprocess.PIPE)
    if completed.returncode:
        raise FirewallError("cannot inspect owned live firewall policy")
    return completed.stdout


def _json_rules(text: str) -> list[dict]:
    try:
        records = json.loads(text)["nftables"]
        if not isinstance(records, list) or any(not isinstance(row, dict) for row in records):
            raise ValueError("invalid records")
    except (ValueError, KeyError, TypeError) as exc:
        raise FirewallError("invalid nftables inspection response") from exc
    return records


def _without_handles(value):
    if isinstance(value, dict):
        return {key: _without_handles(item) for key, item in value.items() if key != "handle"}
    if isinstance(value, list):
        return [_without_handles(item) for item in value]
    return value


def _live_identity(runner: CommandRunner, nft: str) -> dict:
    tables = _json_rules(_capture(runner, nft, "-j", "list", "tables"))
    try:
        present = {(row["table"]["family"], row["table"]["name"])
                   for row in tables if "table" in row}
    except (KeyError, TypeError) as exc:
        raise FirewallError("invalid nftables table inspection response") from exc
    return {f"{family} {name}": [_without_handles(row) for row in _json_rules(
                _capture(runner, nft, "-s", "-j", "list", "table", family, name))
                if "metainfo" not in row]
            for family, name in OWNED_TABLES if (family, name) in present}


def _snapshot_live(runner: CommandRunner, nft: str, mutation: PendingMutation) -> dict:
    previous = _live_identity(runner, nft)
    lines = [f"destroy table {family} {name}" for family, name in OWNED_TABLES]
    for family, name in OWNED_TABLES:
        if f"{family} {name}" in previous:
            lines.append(_capture(runner, nft, "list", "table", family, name))
    # Private recovery records contain only the two project-owned tables.
    for name, content in (("live.nft", "\n".join(lines) + "\n"),
                          ("live.json", json.dumps(previous, sort_keys=True) + "\n")):
        candidate = _write_temporary(mutation.recovery_directory, ".live.", content, mode=0o600)
        os.replace(candidate, mutation.recovery_directory / name)
    _sync_directory(mutation.recovery_directory)
    return previous


def _verify_managed_rules(runner: CommandRunner, nft: str, expected: dict[str, list[str]]) -> None:
    for chain, comments in expected.items():
        actual = []
        for row in _json_rules(_capture(runner, nft, "-j", "list", "chain", "inet", "labwc_filter", chain)):
            rule = row.get("rule", {})
            if not isinstance(rule, dict):
                raise FirewallError("invalid nftables rule inspection response")
            comment = rule.get("comment", "")
            if isinstance(comment, str) and comment.startswith("firewall-security "):
                actual.append(comment)
        if actual != comments:
            raise FirewallError("loaded managed firewall rules do not match the candidate")
