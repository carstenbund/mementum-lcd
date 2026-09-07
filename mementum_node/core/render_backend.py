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
from .renderer import render_scene
from .scene import Scene

__all__ = ["ReferenceRenderer", "Renderer"]


class Renderer(Protocol):
    """Turns a loaded scene into frames at arbitrary scene times."""

    name: str

    def bind(self, payload: bytes, scene: Scene, width: int, height: int) -> None:
        """Take a scene package. ``payload`` is the bytes as cached; ``scene``
        is the same thing already parsed, for renderers that want it."""
        ...

    def render(self, scene_time: float) -> Frame:
        """The picture at ``scene_time``. Pure: same time, same frame."""
        ...


class ReferenceRenderer:
    """The Python reference: evaluate, then rasterise (`core/renderer.py`)."""

    name = "python"

    def __init__(self) -> None:
        self._scene: Scene | None = None
        self._width = 0
        self._height = 0

    def bind(self, payload: bytes, scene: Scene, width: int, height: int) -> None:
        self._scene = scene
        self._width = width
        self._height = height

    def render(self, scene_time: float) -> Frame:
        if self._scene is None:
            raise RuntimeError("renderer holds no scene")
        return render_scene(evaluate(self._scene, scene_time), self._width, self._height)

    def __repr__(self) -> str:
        return f"<ReferenceRenderer {self._width}x{self._height}>"
