"""Sinks -- siblings of the DRM backend, not a new layer (proposal §14).

`drm_screen` ends at a backend adapter that receives a composited RGBA frame. A
headless sink, a record sink and a stream sink all sit at that same position;
only the destination differs, and each does its own single colour conversion
(invariant 1). Capture (plan §3.6) happens here too, which is why the same tool
works for a simulated node, a headless test and a real Pi.
"""

from __future__ import annotations

from typing import Callable, Protocol

from .framebuffer import Frame

__all__ = ["CallbackSink", "HeadlessSink", "NullSink", "Sink"]


class Sink(Protocol):
    """Receives composited frames. The only thing a node's output is.

    ``wants_pixels`` says whether this sink needs the frame composited at all.
    A panel and an encoder do; a counting sink does not, and a node feeding one
    still runs the whole core -- it evaluates every frame and simply has
    nowhere to put the picture. That distinction is real on the device too,
    where the frame-hash tier is always on and the thumbnail tier is not
    (plan §3.6).
    """

    wants_pixels: bool

    def present(self, frame: Frame | None, scene_time: float) -> None: ...

    def close(self) -> None: ...


class HeadlessSink:
    """Keeps the last composited frame in memory.

    Nothing about being headless makes a node invisible: the frame is complete,
    it is simply not scanned out. This is the capture point.
    """

    wants_pixels = True

    def __init__(self, keep_history: bool = False):
        self.frame: Frame | None = None
        self.scene_time: float | None = None
        self.presented = 0
        self.keep_history = keep_history
        self.history: list[tuple[float, str]] = []

    def present(self, frame: Frame | None, scene_time: float) -> None:
        if frame is None:
            raise ValueError("HeadlessSink requires composited frames")
        self.frame = frame
        self.scene_time = scene_time
        self.presented += 1
        if self.keep_history:
            self.history.append((scene_time, frame.hash()))

    def close(self) -> None:  # pragma: no cover - nothing to release
        pass


class NullSink:
    """Counts frames and discards them.

    For scale scenarios (300 nodes), where evaluation and protocol behaviour are
    the subject and compositing 300 buffers would only measure Python. A node
    with a null sink still runs the whole core; it just has nowhere to put the
    picture.
    """

    wants_pixels = False

    def __init__(self) -> None:
        self.presented = 0
        self.scene_time: float | None = None

    def present(self, frame: Frame | None, scene_time: float) -> None:
        self.presented += 1
        self.scene_time = scene_time

    def close(self) -> None:  # pragma: no cover
        pass


class CallbackSink:
    """Hands each frame to a callable -- the shape a record or stream sink takes
    once an encoder is on the other end (plan 0b.2)."""

    wants_pixels = True

    def __init__(self, callback: Callable[[Frame, float], None]):
        self._callback = callback
        self.presented = 0

    def present(self, frame: Frame | None, scene_time: float) -> None:
        if frame is None:
            raise ValueError("CallbackSink requires composited frames")
        self.presented += 1
        self._callback(frame, scene_time)

    def close(self) -> None:  # pragma: no cover
        pass
