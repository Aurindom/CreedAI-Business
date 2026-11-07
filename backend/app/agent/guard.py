from __future__ import annotations

from typing import Iterable

WINDOW = 8


class LeakGuard:
    """Any WINDOW consecutive characters of a guarded value count as a leak, so a partial echo is caught too.
    The last WINDOW-1 characters of streamed text are held back so a fragment split across deltas is still seen.
    Exact characters only: a runtime that spaces out or re-encodes a value is not caught here, which is why private
    values must never reach the model in the first place."""

    def __init__(self, secrets: Iterable[str]) -> None:
        values = [s for s in secrets if s]
        if any(len(s) < WINDOW for s in values):
            raise ValueError(f"guarded values must be at least {WINDOW} characters")
        self._windows = {s[i:i + WINDOW] for s in values for i in range(len(s) - WINDOW + 1)}
        self._hold = WINDOW - 1 if values else 0
        self._pending = ""
        self.tripped = False

    def leaks(self, *texts: str) -> bool:
        return any(w in t for t in texts for w in self._windows)

    def feed(self, text: str) -> str | None:
        if self.tripped:
            return None
        buffer = self._pending + text
        if self.leaks(buffer):
            self.tripped, self._pending = True, ""
            return None
        cut = max(len(buffer) - self._hold, 0)
        out, self._pending = buffer[:cut], buffer[cut:]
        return out

    def flush(self) -> str:
        out, self._pending = ("" if self.tripped else self._pending), ""
        return out
