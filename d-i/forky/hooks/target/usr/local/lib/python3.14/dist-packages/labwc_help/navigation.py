"""Pure bounded navigation state, independent of GTK and filesystem state."""
from __future__ import annotations


class History:
    def __init__(self):
        self.entries: list[tuple[str, float]] = []
        self.position = -1

    def remember(self, scroll: float):
        if 0 <= self.position < len(self.entries):
            self.entries[self.position] = (self.entries[self.position][0], max(0, min(scroll, 1_000_000)))

    def visit(self, topic: str, scroll: float = 0):
        self.remember(scroll)
        if self.position >= 0 and self.entries[self.position][0] == topic:
            return
        self.entries = self.entries[:self.position + 1]
        self.entries.append((topic, 0))
        self.entries = self.entries[-100:]
        self.position = len(self.entries) - 1

    def move(self, delta: int, scroll: float) -> tuple[str, float] | None:
        destination = self.position + delta
        if not 0 <= destination < len(self.entries):
            return None
        self.remember(scroll)
        self.position = destination
        return self.entries[destination]
