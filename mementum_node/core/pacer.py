"""Pacers -- the only thing that differs between node implementations (§14).

    display    driven by the display (vsync / page flip)   sharedNow()
    stream     wall clock at a fixed rate, CFR             sharedNow()
    record     a loop over t, no wall clock at all         scene time

Every pacer asks the same question -- *what should be on screen now?* -- and the
answer is always ``evaluate(sharedNow() - displayAt)``. A pacer decides only
*when* to ask. There is no accumulator here, and adding one would be a bug
rather than a tuning parameter (§10).
"""

from __future__ import annotations

from typing import Callable

__all__ = ["DisplayPacer", "RecordPacer", "StreamPacer"]


class _IntervalPacer:
    def __init__(self, interval_ms: float):
        if interval_ms <= 0:
            raise ValueError("pacer interval must be positive")
        self.interval_ms = float(interval_ms)
        self._next_due: float | None = None
        self.ticks = 0

    def due(self, now: float) -> bool:
        return self._next_due is None or now >= self._next_due

    def mark(self, now: float) -> None:
        """Schedule the next tick. Absolute, never accumulated from the last
        actual tick, so a late frame does not push the whole sequence back."""
        if self._next_due is None:
            self._next_due = now + self.interval_ms
        else:
            missed = int((now - self._next_due) // self.interval_ms) + 1
            self._next_due += self.interval_ms * max(1, missed)
        self.ticks += 1

    def step(self, now: float, render: Callable[[], None]) -> bool:
        if not self.due(now):
            return False
        self.mark(now)
        render()
        return True


class DisplayPacer(_IntervalPacer):
    """A display node evaluates whenever it can present."""

    def __init__(self, fps: float = 30.0):
        super().__init__(1000.0 / fps)
        self.fps = fps


class StreamPacer(_IntervalPacer):
    """A streaming node must emit at a constant rate whether or not anything
    changed, because encoders want CFR (§14)."""

    def __init__(self, fps: float = 25.0):
        super().__init__(1000.0 / fps)
        self.fps = fps


class RecordPacer:
    """A recording node is not bound to wall clock at all: it walks scene time.

    Rendering the same scene twice must therefore produce byte-identical output
    -- the cheapest available test of the whole determinism claim (plan 0b.3).
    """

    def __init__(self, fps: float = 30.0):
        self.fps = fps
        self.interval_ms = 1000.0 / fps

    def times(self, duration_ms: float, start_ms: float = 0.0):
        n = int(duration_ms / self.interval_ms) + 1
        for i in range(n):
            yield start_ms + i * self.interval_ms
