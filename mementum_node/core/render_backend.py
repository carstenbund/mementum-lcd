"""The renderer seam.

A node's picture comes from *a* renderer, not from *the* renderer. The Python
reference rasteriser and the C/LVGL/ThorVG player are both implementations of
this protocol, and a participant does not know which one it holds -- which is
what lets a simulated swarm mix them (implementation plan §3.7).

The seam is at ``(scene, sceneTime) -> Frame``, deliberately not at
``(evaluated state) -> Frame``. The C player evaluates the scene itself, in the
same code that will run on the device, and that is the entire point: one
evaluator, not two (risk R6). A seam below evaluation would have kept Python's
evaluator in the loop and proved nothing.
"""

from __future__ import annotations

from typing import Protocol

from .evaluator import evaluate
from .framebuffer import Frame
from .protocol import Capabilities
from .renderer import render_scene
from .ripple import Ripple
from .scene import Scene

__all__ = ["ReferenceRenderer", "Renderer"]


class Renderer(Protocol):
    """Turns a loaded scene into frames at arbitrary scene times.

    A renderer is a plugin, chosen for what the platform offers. Not every one
    can draw everything: a vector renderer strokes paths and deforms them, a
    plain RGBA painter fills rectangles and draws text and images and can do
    neither. So a renderer *declares* what it can do, a scene declares what it
    needs, and the sequencer matches the two before scheduling anything
    (proposal §18). A node that cannot render a scene fails visibly rather than
    drifting quietly out of the shared timeline.
    """

    name: str

    #: What this renderer can draw. A node reports its renderer's capabilities
    #: at registration, so the two cannot disagree.
    capabilities: Capabilities

    def bind(self, payload: bytes, scene: Scene, width: int, height: int) -> None:
        """Take a scene package. ``payload`` is the bytes as cached; ``scene``
        is the same thing already parsed, for renderers that want it."""
        ...

    def render(self, scene_time: float) -> Frame:
        """The picture at ``scene_time``. Pure: same time, same frame."""
        ...

    def add_ripple(self, ripple: Ripple) -> None:
        """Start a local disturbance. Not part of the scene: a ripple is
        induced by someone touching a unit, and it is over in a second.

        Required, not optional. The ESP32 units run the C player, so a renderer
        that cannot do this is a unit on which the second layer does not exist
        (decision 0008)."""
        ...


class ReferenceRenderer:
    """The Python reference: evaluate, then rasterise (`core/renderer.py`)."""

    name = "python"
    capabilities = Capabilities(scene_ir=1, vector=True, text=True, lottie=False)

    #: A unit holds only a few live ripples; the oldest is dropped.
    MAX_RIPPLES = 4

    def __init__(self) -> None:
        self._scene: Scene | None = None
        self._width = 0
        self._height = 0
        self._ripples: list[Ripple] = []

    def bind(self, payload: bytes, scene: Scene, width: int, height: int) -> None:
        self._scene = scene
        self._width = width
        self._height = height

    def add_ripple(self, ripple: Ripple) -> None:
        self._ripples.append(ripple)
        if len(self._ripples) > self.MAX_RIPPLES:
            del self._ripples[0]

    def render(self, scene_time: float) -> Frame:
        if self._scene is None:
            raise RuntimeError("renderer holds no scene")
        live = tuple(r for r in self._ripples if r.active_at(scene_time))
        return render_scene(
            evaluate(self._scene, scene_time),
            self._width,
            self._height,
            ripples=live,
            scene_time=scene_time,
        )

    def __repr__(self) -> str:
        return f"<ReferenceRenderer {self._width}x{self._height}>"
