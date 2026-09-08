"""The screen, borrowed from the stack rather than kept here.

This package used to hold its own `drm_screen`-shaped API with its own ctypes
binding. That work has moved upstream where it belongs:

    drm_screen         the layer model, the command records, the service
    drm_screen_lvgl    the LVGL renderer plugin -- the binding that was here
    poc/player/screen.c  the C it binds, which stays: this is its home

What is left in this package is what is genuinely this project's: the scene
layers a participant shows, the ripple that is not part of `drm_screen`'s
vocabulary, and a service that works with or without numpy on the machine.

    from mementum_node.screen import screen_service
    from mementum_node.screen.commands import CreateLayer, PlaceScene

    service = screen_service(display="drm", clock=lambda: shared_now() - display_at)
    service.submit([
        CreateLayer("writing", 1920, 1080, z=10),
        PlaceScene("writing", scene_json),
    ])
    service.start()

`screen_service()` returns `drm_screen`'s own `ScreenService` where that package
is installed, and an equivalent stdlib-only loop where it is not -- a node with
no numpy is still a node (plan §14).
"""

from __future__ import annotations

import os

# This repository is the library's home, so point the plugin at the build tree
# before it looks anywhere else. An explicit setting wins, as it should.
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("MEMENTUM_SRC", _REPO)

from drm_screen_lvgl import LvglError, LvglRenderer, LvglScreen, is_available  # noqa: E402

from mementum_node.screen.commands import (  # noqa: E402,F401
    ClearLayer, CreateLayer, DeleteLayer, HideLayer, PlaceRawBuffer, PlaceScene,
    SetInteractive, SetOpacity, SetPointer, SetPosition, SetZ, ShowLayer, StartRipple,
)
from mementum_node.screen.service import Screen, screen_service  # noqa: E402

__all__ = [
    "LvglError", "LvglRenderer", "LvglScreen", "Screen",
    "is_available", "screen_service", "commands",
]
