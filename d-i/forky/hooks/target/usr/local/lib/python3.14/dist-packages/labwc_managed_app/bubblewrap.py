"""Shared invariants for every package-owned Bubblewrap command."""

from __future__ import annotations

from .runtime import fail


PRIVATE_PROCFS_ARGUMENTS = ("--proc", "/proc")
PID_NAMESPACE_ARGUMENTS = frozenset(("--unshare-all", "--unshare-pid"))


def add_private_procfs(command: list[str]) -> None:
    if "--proc" in command:
        fail("Bubblewrap command already contains a procfs mount")
    command.extend(PRIVATE_PROCFS_ARGUMENTS)


def validate_private_procfs(command: list[str]) -> None:
    indexes = [index for index, argument in enumerate(command) if argument == "--proc"]
    if len(indexes) != 1:
        fail("Bubblewrap command must contain exactly one private procfs mount")
    index = indexes[0]
    if index + 1 >= len(command) or command[index + 1] != "/proc":
        fail("Bubblewrap private procfs must be mounted at /proc")
    if PID_NAMESPACE_ARGUMENTS.isdisjoint(command):
        fail("Bubblewrap private procfs requires a private PID namespace")
