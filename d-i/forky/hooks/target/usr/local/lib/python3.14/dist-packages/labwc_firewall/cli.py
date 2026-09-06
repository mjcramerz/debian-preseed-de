"""Client and privileged CLI roles for the Labwc firewall action."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys

from .files import FirewallPaths, PendingMutation, locked, validate_managed_file
from .nftables import CommandRunner, validate_and_apply
from .renderer import render_fragment
from .state import MAX_RULES, Rule, format_status, load_state, next_rule_id, serialize_state
from .validation import FirewallError, normalize_cidr, require, validate_rule_fields, validate_rule_id


CLIENT_PATH = "/usr/local/bin:/usr/bin:/bin"
ROOT_HELPER = "/usr/local/libexec/labwc-firewall-action-root"
SELF_PATH = "/usr/local/bin/labwc-firewall-action"


def _client_executable(name: str) -> str:
    executable = shutil.which(name, path=CLIENT_PATH)
    if executable is None:
        raise FirewallError(f"{name} is not installed")
    return executable


def _notify(urgency: str, summary: str, body: str) -> None:
    if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        return
    executable = shutil.which("notify-send", path=CLIENT_PATH)
    if executable is None:
        return
    try:
        subprocess.run(
            [
                executable,
                "-a",
                "Firewall",
                "-u",
                urgency,
                "-i",
                "security-high",
                summary,
                body,
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return


def _finish_status(status: int) -> int:
    print(f"\n=== Action finished with status {status} ===")
    if sys.stdin.isatty():
        try:
            input("Press Enter to close this terminal...")
        except EOFError:
            pass
    return status


def _run_root_action(*argv: str) -> int:
    pkexec = _client_executable("pkexec")
    helper = Path(ROOT_HELPER)
    try:
        metadata = helper.lstat()
    except OSError as exc:
        raise FirewallError(f"privileged firewall helper is unavailable: {helper}") from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        or not os.access(helper, os.X_OK)
    ):
        raise FirewallError(f"privileged firewall helper is unavailable: {helper}")
    try:
        return subprocess.run(
            [pkexec, str(helper), *argv],
            check=False,
        ).returncode
    except OSError as exc:
        raise FirewallError(f"cannot start privileged firewall helper: {exc}") from exc


def _client_request(argv: list[str]) -> tuple[list[str], str, str]:
    require(bool(argv), "unsupported firewall action: unset")
    action, *args = argv
    if action == "add-rule":
        require(
            len(args) == 7,
            "add-rule requires direction, verdict, protocol, port, scope, CIDR, and confirmation",
        )
        direction, verdict, protocol, port, scope, cidr, confirmation = args
        require(
            confirmation == "confirmed-firewall-action",
            "firewall change confirmation is missing",
        )
        direction, verdict, protocol, port, scope, cidr = validate_rule_fields(
            direction,
            verdict,
            protocol,
            port,
            scope,
            cidr,
        )
        return (
            [
                action,
                direction,
                verdict,
                protocol,
                str(port),
                scope,
                cidr,
                confirmation,
            ],
            "Firewall rule applied",
            f"Applied {verdict} {direction} {protocol}/{port} with {scope} scope.",
        )
    if action == "remove-rule":
        require(
            len(args) == 2,
            "remove-rule requires an identifier and confirmation",
        )
        rule_id, confirmation = args
        validate_rule_id(rule_id)
        require(
            confirmation == "confirmed-firewall-action",
            "firewall rule removal confirmation is missing",
        )
        return (
            [action, rule_id, confirmation],
            "Firewall rule removed",
            f"Removed managed firewall rule {rule_id}.",
        )
    if action == "reset-rules":
        require(len(args) == 1, "reset-rules requires confirmation")
        require(
            args[0] == "confirmed-firewall-action",
            "firewall reset confirmation is missing",
        )
        return (
            [action, args[0]],
            "Firewall rules reset",
            "Removed every Computer Management firewall rule.",
        )
    raise FirewallError(f"unsupported firewall action: {action}")


def _client_usage() -> str:
    return (
        "usage: labwc-firewall-action "
        "<status|add-rule|remove-rule|reset-rules> [arguments]"
    )


def run_client(argv: list[str]) -> int:
    if not argv:
        raise FirewallError(_client_usage())
    if argv[0] in {"--help", "-h"}:
        print(_client_usage())
        return 0
    require(os.geteuid() != 0, "labwc-firewall-action must run as the logged-in desktop user")
    if argv[0] == "--run-status":
        require(len(argv) == 2, "--run-status requires one action")
        require(argv[1] == "status", f"unsupported firewall status action: {argv[1]}")
        return _finish_status(_run_root_action("status"))
    if argv[0] == "status":
        require(len(argv) == 1, "status does not accept arguments")
        terminal = _client_executable("labwc-terminal")
        os.execv(terminal, [terminal, "-e", SELF_PATH, "--run-status", "status"])

    root_argv, summary, body = _client_request(argv)
    status = _run_root_action(*root_argv)
    if status == 0:
        _notify("normal", summary, body)
        return 0
    _notify(
        "critical",
        "Firewall action failed",
        "The requested nftables change did not complete; the previous rules were retained.",
    )
    return status


def _require_pkexec_invoker(runner: CommandRunner) -> None:
    uid = os.environ.get("PKEXEC_UID", "")
    require(
        uid.isascii() and uid.isdecimal() and int(uid) > 0,
        "privileged firewall helper must be invoked by a non-root desktop user through pkexec",
    )
    getent = runner.require("getent")
    completed = runner.run(
        getent,
        "passwd",
        uid,
        timeout_seconds=10,
        stdout=subprocess.PIPE,
    )
    require(
        completed.returncode == 0 and bool((completed.stdout or "").strip()),
        f"pkexec invoking account does not exist: {uid}",
    )


def _status(paths: FirewallPaths, runner: CommandRunner) -> int:
    with locked(paths.lock_file, exclusive=False):
        validate_managed_file("firewall state file", paths.state_file)
        validate_managed_file("firewall fragment", paths.fragment_file)
        rules = load_state(paths.state_file)
        print("=== Managed firewall rules ===\n")
        print(format_status(rules), end="")
        nft = runner.require("nft")
        print("\n=== nftables local_input chain ===")
        runner.run_or_fail(
            "listing nftables local_input chain",
            nft,
            "list",
            "chain",
            "inet",
            "filter",
            "local_input",
        )
        print("\n=== nftables local_output chain ===")
        runner.run_or_fail(
            "listing nftables local_output chain",
            nft,
            "list",
            "chain",
            "inet",
            "filter",
            "local_output",
        )
    return 0


def _apply_rules(paths: FirewallPaths, rules: list[Rule], runner: CommandRunner) -> None:
    mutation = PendingMutation.create(paths)
    try:
        mutation.write_candidates(serialize_state(rules), render_fragment(rules))
        validate_and_apply(runner, mutation, paths.nft_conf)
    finally:
        mutation.cleanup()


def _add_rule(paths: FirewallPaths, runner: CommandRunner, args: list[str]) -> int:
    require(
        len(args) == 7,
        "add-rule requires direction, verdict, protocol, port, scope, CIDR, and confirmation",
    )
    direction, verdict, protocol, port, scope, cidr, confirmation = args
    require(
        confirmation == "confirmed-firewall-action",
        "firewall change confirmation is missing",
    )
    direction, verdict, protocol, port, scope, cidr = validate_rule_fields(
        direction,
        verdict,
        protocol,
        port,
        scope,
        cidr,
    )
    with locked(paths.lock_file, exclusive=True):
        rules = load_state(paths.state_file)
        require(
            len(rules) < MAX_RULES,
            f"managed firewall rule limit of {MAX_RULES} has been reached",
        )
        rule_id = next_rule_id(rules)
        rules.append(Rule(rule_id, direction, verdict, protocol, port, scope, cidr))
        _apply_rules(paths, rules, runner)
    print(f"added managed firewall rule: {rule_id}")
    return 0


def _remove_rule(paths: FirewallPaths, runner: CommandRunner, args: list[str]) -> int:
    require(len(args) == 2, "remove-rule requires an identifier and confirmation")
    rule_id, confirmation = args
    validate_rule_id(rule_id)
    require(
        confirmation == "confirmed-firewall-action",
        "firewall rule removal confirmation is missing",
    )
    with locked(paths.lock_file, exclusive=True):
        rules = load_state(paths.state_file)
        updated_rules = [rule for rule in rules if rule.rule_id != rule_id]
        require(
            len(updated_rules) != len(rules),
            f"managed firewall rule does not exist: {rule_id}",
        )
        _apply_rules(paths, updated_rules, runner)
    print(f"removed managed firewall rule: {rule_id}")
    return 0


def _reset_rules(paths: FirewallPaths, runner: CommandRunner, args: list[str]) -> int:
    require(len(args) == 1, "reset-rules requires confirmation")
    require(
        args[0] == "confirmed-firewall-action",
        "firewall reset confirmation is missing",
    )
    with locked(paths.lock_file, exclusive=True):
        _apply_rules(paths, [], runner)
    print("removed every managed firewall rule")
    return 0


def run_root(argv: list[str]) -> int:
    require(os.geteuid() == 0, "privileged firewall helper must run as root")
    require(bool(argv), "usage: labwc-firewall-action-root <action> [arguments]")
    runner = CommandRunner()
    _require_pkexec_invoker(runner)
    paths = FirewallPaths()
    action, *args = argv
    if action == "status":
        require(not args, "status does not accept arguments")
        return _status(paths, runner)
    if action == "add-rule":
        return _add_rule(paths, runner, args)
    if action == "remove-rule":
        return _remove_rule(paths, runner, args)
    if action == "reset-rules":
        return _reset_rules(paths, runner, args)
    raise FirewallError(f"unsupported privileged firewall action: {action}")


def main(role: str, argv: list[str]) -> int:
    try:
        if role == "client":
            return run_client(argv)
        if role == "root":
            return run_root(argv)
        raise FirewallError("invalid Labwc firewall action role")
    except FirewallError as exc:
        print(f"fatal: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"fatal: firewall action failed: {exc}", file=sys.stderr)
        return 1
