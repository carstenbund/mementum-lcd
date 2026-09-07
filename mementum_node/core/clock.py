"""The shared clock -- ``sharedNow()`` and nothing else (proposal §11, §20).

Playback derives *exclusively* from ``sharedNow() - displayAt``. This module is
therefore the one seam the simulator substitutes for time: the real node runs
:class:`CristianClock` over an HTTP ``/time`` endpoint, the simulated node runs
the same class over a virtual time source with an injected offset. The clock
logic being exercised is identical either way.

Two properties matter beyond the arithmetic:

* **Unsigned-difference arithmetic** (§11). The device's ``millis()`` wraps
  every ~49.7 days; :func:`elapsed` is how a duration is computed so that the
  wrap is a non-event. Python integers do not wrap, so the rule is enforced by
  using this helper rather than by the language.
* **Clock epoch.** A leader change produces a new time domain. The epoch is
  carried alongside the time so a node can *notice* rather than silently
  reinterpret a stranger's ``millis()`` as continuity.
"""

from __future__ import annotations

import time
from typing import Callable, Protocol

__all__ = [
    "Clock",
    "CristianClock",
    "FixedClock",
    "MILLIS_MASK",
    "SystemTimeSource",
    "TimeSample",
    "TimeSource",
    "elapsed",
]

#: 32-bit ``millis()`` domain, mirrored here so host and device agree.
MILLIS_MASK = 0xFFFFFFFF


def elapsed(start: int, now: int, mask: int = MILLIS_MASK) -> int:
    """``now - start`` in unsigned-difference arithmetic; rollover-safe."""
    return (int(now) - int(start)) & mask


class TimeSource(Protocol):
    """A local monotonic millisecond source (``millis()`` on the device)."""

    def monotonic_ms(self) -> float: ...


class SystemTimeSource:
    def __init__(self) -> None:
        self._origin = time.monotonic()

    def monotonic_ms(self) -> float:
        return (time.monotonic() - self._origin) * 1000.0


class Clock(Protocol):
    def shared_now(self) -> float: ...


class TimeSample:
    __slots__ = ("server_now", "rtt", "offset", "epoch")

    def __init__(self, server_now: float, rtt: float, offset: float, epoch: int):
        self.server_now = server_now
        self.rtt = rtt
        self.offset = offset
        self.epoch = epoch

    def __repr__(self) -> str:
        return f"<TimeSample rtt={self.rtt:.1f} offset={self.offset:.1f} epoch={self.epoch}>"


class CristianClock:
    """Cristian's algorithm, best of N samples -- the ``mementum-led`` model.

    ``query`` performs one round trip and returns ``(server_now_ms, epoch)``. It
    is the transport's business how that happens; over HTTP it is ``GET /time``,
    in simulation it is an in-process call with injected latency.

    Sync is client-initiated (§20: "clock sync scales fine"), performed on
    register and refreshed on heartbeat, so the server only ever answers.
    """

    def __init__(
        self,
        source: TimeSource,
        query: Callable[[], tuple[float, int]],
        samples: int = 3,
    ):
        self._source = source
        self._query = query
        self.samples = samples
        self.offset = 0.0
        self.epoch = 0
        self.last_rtt: float | None = None
        self.last_sync_at: float | None = None
        self.sync_count = 0
        self.synced = False

    def local_now(self) -> float:
        return self._source.monotonic_ms()

    def shared_now(self) -> float:
        return self._source.monotonic_ms() + self.offset

    def sync(self) -> TimeSample | None:
        """Take ``samples`` round trips and adopt the one with the lowest RTT.

        Returns the adopted sample, or ``None`` if every round trip failed --
        in which case the previous offset is kept rather than replaced by a
        guess."""
        best: TimeSample | None = None
        for _ in range(self.samples):
            t0 = self._source.monotonic_ms()
            try:
                server_now, epoch = self._query()
            except TimeoutError:
                continue
            t1 = self._source.monotonic_ms()
            rtt = t1 - t0
            sample = TimeSample(server_now, rtt, server_now + rtt / 2.0 - t1, epoch)
            if best is None or sample.rtt < best.rtt:
                best = sample
        if best is None:
            return None
        self.offset = best.offset
        self.last_rtt = best.rtt
        self.last_sync_at = self._source.monotonic_ms()
        self.epoch = best.epoch
        self.sync_count += 1
        self.synced = True
        return best


class FixedClock:
    """A clock that is simply told the time. For the sequencer's own use and
    for offline (record-pacer) rendering, where there is no clock domain."""

    def __init__(self, source: TimeSource):
        self._source = source

    def shared_now(self) -> float:
        return self._source.monotonic_ms()
