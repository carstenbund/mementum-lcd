"""Touch ripples — a disturbance that travels along a stroke, and across a room.

Someone touches a unit. That unit answers immediately, and the touch is also
reported to the sequencer, which schedules the same ripple on every other unit
at a time derived from how far away it stands. The gesture then crosses the
installation at a speed we choose, which is the point: a meme acquiring
momentum by moving through the network rather than merely being copied onto it.

Two properties make it fit the rest of the architecture rather than fighting it:

* **A ripple is a function of time, like everything else.** Its shape at any
  moment is ``f(distance along the stroke, time since it started)`` — no
  accumulator, so a node that misses a frame is still correct on the next one.
* **A ripple is transient, so it is fire-and-forget.** The schedule is state
  because a scene outlives a delivery failure (§19); a ripple does not. It is
  over in a second and a half, long before the next heartbeat, so a node that
  misses the push simply does not ripple. That is a deliberate exception, and
  the only one.

The touch point is mapped to an *arc position* on the stroke, not to a point on
the canvas: the disturbance travels along the line, the way a wave travels down
a rope.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

__all__ = ["Ripple", "RIPPLE_DEFAULTS"]

#: Chosen by eye rather than derived: fast enough to read as a disturbance,
#: slow enough to watch cross the stroke.
RIPPLE_DEFAULTS = {
    "amplitude": 16.0,      # design units, in-plane
    "wavelength": 110.0,    # design units
    "speed": 420.0,         # design units per second, along the stroke
    "life_ms": 1500.0,
    "width": 150.0,         # how wide the travelling crest is
}


@dataclass(frozen=True)
class Ripple:
    """One live disturbance on one stroke.

    ``origin`` is an arc distance along the path and ``start`` a scene time, so
    a ripple lives in the same coordinates as everything else the player
    evaluates.
    """

    origin: float
    start: float
    amplitude: float = RIPPLE_DEFAULTS["amplitude"]
    wavelength: float = RIPPLE_DEFAULTS["wavelength"]
    speed: float = RIPPLE_DEFAULTS["speed"]
    life_ms: float = RIPPLE_DEFAULTS["life_ms"]
    width: float = RIPPLE_DEFAULTS["width"]

    def active_at(self, scene_time: float) -> bool:
        return 0.0 <= scene_time - self.start <= self.life_ms

    def offset(self, distance: float, scene_time: float) -> float:
        """In-plane offset at ``distance`` along the stroke. Pure."""
        age = scene_time - self.start
        if age < 0.0 or age > self.life_ms:
            return 0.0

        travelled = abs(distance - self.origin) - self.speed * age / 1000.0
        envelope = math.exp(-(travelled * travelled) / (2.0 * self.width * self.width))
        decay = 1.0 - age / self.life_ms
        return (
            self.amplitude
            * decay
            * decay
            * envelope
            * math.sin(2.0 * math.pi * travelled / self.wavelength)
        )
