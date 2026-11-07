from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Literal

State = Literal["running", "stopping", "stopped"]


class Claim:
    """One occupied slot. Only the worker's own exit path calls release(), never a request handler's finally."""

    def __init__(self, owner: Capacity) -> None:
        self._owner = owner
        self._state: State = "running"
        self._lock = threading.Lock()

    @property
    def state(self) -> State:
        return self._state

    def stopping(self) -> None:
        with self._lock:
            if self._state == "running":
                self._state = "stopping"

    def release(self) -> bool:
        with self._lock:
            if self._state == "stopped":
                return False
            self._state = "stopped"
        self._owner._free(self)
        return True


@dataclass(frozen=True)
class Usage:
    limit: int
    running: int
    stopping: int

    @property
    def busy(self) -> bool:
        return self.running + self.stopping >= self.limit


class Capacity:
    """Process-local slot counter. A slot stays taken while its worker is stopping, so cleanup still counts as busy.
    Several server processes would need a shared store before this can act as a global limit."""

    def __init__(self, limit: int) -> None:
        if limit < 1:
            raise ValueError("capacity limit must be at least 1")
        self.limit = limit
        self._claims: set[Claim] = set()
        self._lock = threading.Lock()

    def try_claim(self) -> Claim | None:
        with self._lock:
            if len(self._claims) >= self.limit:
                return None
            claim = Claim(self)
            self._claims.add(claim)
            return claim

    def usage(self) -> Usage:
        with self._lock:
            states = [c.state for c in self._claims]
        return Usage(self.limit, states.count("running"), states.count("stopping"))

    def _free(self, claim: Claim) -> None:
        with self._lock:
            self._claims.discard(claim)
