"""The `drm_screen` command records, borrowed rather than reinvented.

`drm_screen.commands` is the stable contract between `drm_composer` and the
screen: commands are data, so the same batch survives a socket hop or a direct
enqueue. That contract does not change because the compositor underneath it
changed, so when `drm_screen` is installed these *are* its records -- code that
already builds batches keeps working, unmodified, against an LVGL screen.

Where it is not installed (a device with no numpy, a test host, the ESP-side
tooling) the same records are defined here, field for field. Dispatch is by
class *name*, never by identity, so a batch built from either definition
applies to either screen.

`PlaceScene` and `SetOpacity` went upstream with the renderer seam and come
from `drm_screen` when it is installed. `StartRipple` did not: a wave running
along a stroke because somebody touched the glass is this project's idea of
what a screen is for, not `drm_screen`'s, and it stays here until it has earned
its place there. The LVGL renderer dispatches by class name, so a record
defined here reaches it exactly as one defined upstream does.

A screen that cannot honour an addition should say so rather than skip it.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "CreateLayer", "DeleteLayer", "ClearLayer", "ShowLayer", "HideLayer",
    "SetPosition", "SetZ", "PlaceRawBuffer", "SetInteractive", "SetPointer",
    "PlaceScene", "SetOpacity", "SetSceneOffset", "StartRipple", "HAVE_DRM_SCREEN",
]

try:  # the real contract, when it is on the machine
    from drm_screen.commands import (  # noqa: F401
        ClearLayer, CreateLayer, DeleteLayer, HideLayer, PlaceRawBuffer, PlaceScene,
        SetInteractive, SetOpacity, SetPointer, SetPosition, SetZ, ShowLayer,
    )

    HAVE_DRM_SCREEN = True
except ImportError:  # pragma: no cover - exercised on hosts without drm_screen
    HAVE_DRM_SCREEN = False

    @dataclass
    class CreateLayer:
        name: str
        width: int
        height: int
        x: int = 0
        y: int = 0
        z: int = 0
        visible: bool = True
        opacity: float = 1.0
        interactive: bool = False
        hit_id: str | None = None

    @dataclass
    class DeleteLayer:
        name: str

    @dataclass
    class ClearLayer:
        name: str

    @dataclass
    class ShowLayer:
        name: str

    @dataclass
    class HideLayer:
        name: str

    @dataclass
    class SetPosition:
        name: str
        x: int
        y: int

    @dataclass
    class SetZ:
        name: str
        z: int

    @dataclass
    class PlaceRawBuffer:
        name: str
        width: int
        height: int
        data: bytes
        x: int = 0
        y: int = 0
        fmt: str = "RGBA8888"

    @dataclass
    class SetInteractive:
        name: str
        interactive: bool = True
        hit_id: str | None = None

    @dataclass
    class SetPointer:
        x: int
        y: int
        visible: bool = True


# -- additions ----------------------------------------------------------------

if not HAVE_DRM_SCREEN:  # pragma: no cover - mirrored from drm_screen

    @dataclass
    class SetOpacity:
        name: str
        opacity: float

    @dataclass
    class PlaceScene:
        """Give a layer a scene description instead of a bitmap."""

        name: str
        scene: bytes | str
        fmt: str = "drm_scene_ir/json"


@dataclass
class SetSceneOffset:
    """Shift one layer's own clock against the screen's.

    A wall is rendered at one time, but the units standing on it need not be
    holding the same moment: a staggered start, a sentence dealt across the
    wall, a word running through it. The offset is that difference, and it is
    the layer's, so nothing is rendered twice and nothing accumulates."""

    name: str
    offset: float


@dataclass
class StartRipple:
    """A transient local wave along a scene layer's ink. Fire and forget: a
    ripple that arrives too late is simply not shown."""

    name: str
    origin: float
    start: float = 0.0
    amplitude: float = 6.0
    wavelength: float = 120.0
    speed: float = 0.35
    life_ms: float = 1400.0
    width: float = 260.0
