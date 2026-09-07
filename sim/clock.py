"""Substitution 1 of 3: the clock (plan §3.1).

Real: ``CristianClock`` over HTTP ``/time``. Simulated: the same
``CristianClock``, over a virtual time source whose offset, drift and jitter we
choose. The clock *logic* under test is identical -- only the source of time
and the round trip are ours.

Three knobs, each modelling something real:

* **offset** -- a node's local ``millis()`` origin. Boards do not boot together.
* **drift** -- crystal error in ppm; what makes an unre-synced node wander.
* **jitter** -- noise on each local time read, which is what makes Cristian's
  best-of-three sampling do any work at all.

Their *parameters* must come from hardware measurement (§3.4). The simulator
models a jitter distribution; it does not know the real one, and calibration
runs hardware-to-simulator, never the reverse (risk R9).
"""

from __future__ import annotations

import random

__all__ = ["NodeTimeSource", "SimulationClock"]


class SimulationClock:
    """Master virtual time. Advanced explicitly by the harness, never by
    wall-clock, so a scenario runs faster than real time and identically on
    every machine."""

    def __init__(self, start_ms: float = 0.0):
        self.now = float(start_ms)

    def advance(self, ms: float) -> float:
        if ms < 0:
            raise ValueError("virtual time does not go backwards")
        self.now += ms
        return self.now

    def monotonic_ms(self) -> float:
        return self.now


class NodeTimeSource:
    """One node's view of local time -- its ``millis()``.

    ``stall_ms`` is set by the transport for the duration of a round trip: it is
    how long the node believes has passed while it was blocked, and it is what
    gives Cristian's algorithm a non-zero RTT to work with.
    """

    def __init__(
        self,
        master: SimulationClock,
        offset_ms: float = 0.0,
        drift_ppm: float = 0.0,
        jitter_ms: float = 0.0,
        seed: int = 0,
    ):
        self.master = master
        self.offset_ms = float(offset_ms)
        self.drift_ppm = float(drift_ppm)
        self.jitter_ms = float(jitter_ms)
        self.stall_ms = 0.0
        self._rng = random.Random(seed)

    def monotonic_ms(self) -> float:
        t = self.master.now
        local = self.offset_ms + t * (1.0 + self.drift_ppm / 1e6) + self.stall_ms
        if self.jitter_ms:
            local += (self._rng.random() * 2.0 - 1.0) * self.jitter_ms
        return local

    def true_local_ms(self) -> float:
        """Local time without jitter -- for the harness's own bookkeeping, not
        for anything the node is allowed to see."""
        return self.offset_ms + self.master.now * (1.0 + self.drift_ppm / 1e6) + self.stall_ms
