"""The C/LVGL/ThorVG player, bound with ctypes (implementation plan §3.7).

This is the *device* player, compiled for the host. The C sources under
`poc/player/` are the ones the ESP-IDF build will compile: scene model, JSON
loader, easing, evaluator and the LVGL renderer. Nothing here reimplements any
of it -- this module loads a shared library and passes bytes across.

Three things that buys, in the plan's words: one evaluator rather than two, a
player that can be run under gdb and ASan, and an early answer to whether a
Linux node can share the ESP32's runtime instead of having its own.

The library is optional. If it has not been built, :func:`is_available` says so
and the tests that need it skip -- the Phase 0c suite must keep running on a
machine with no C toolchain.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import c_char_p, c_double, c_int, c_size_t, c_void_p

from mementum_node.core.framebuffer import Frame
from mementum_node.core.scene import Scene

__all__ = ["LvglPlayer", "LvglPlayerError", "PlayerLibrary", "is_available", "library_path"]

_DEFAULT_LIBRARY = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "poc",
    "host-player",
    "build",
    "libmementum_player.so",
)


class LvglPlayerError(RuntimeError):
    """The C player refused something. Carries its own message."""


def library_path() -> str:
    return os.environ.get("MEMENTUM_PLAYER_LIB", _DEFAULT_LIBRARY)


def is_available() -> bool:
    return os.path.exists(library_path())


class PlayerLibrary:
    """One process-wide handle on the shared library.

    LVGL keeps global state and is initialised once, so this is a singleton by
    necessity rather than by preference.
    """

    _instance: "PlayerLibrary | None" = None

    def __init__(self, path: str | None = None):
        path = path or library_path()
        if not os.path.exists(path):
            raise LvglPlayerError(
                f"player library not built: {path}\n"
                "build it with: make -C poc/host-player -j4 lib"
            )
        self._lib = ctypes.CDLL(path)
        self._declare()
        if self._lib.mm_player_init() != 0:
            raise LvglPlayerError(self.error())

    @classmethod
    def instance(cls) -> "PlayerLibrary":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _declare(self) -> None:
        lib = self._lib
        lib.mm_player_init.restype = c_int
        lib.mm_player_load.argtypes = [c_char_p, c_int, c_int]
        lib.mm_player_load.restype = c_void_p
        lib.mm_player_destroy.argtypes = [c_void_p]
        lib.mm_player_render.argtypes = [c_void_p, c_double, ctypes.POINTER(ctypes.c_uint8), c_size_t]
        lib.mm_player_render.restype = c_int
        lib.mm_player_error.restype = c_char_p
        lib.mm_player_scene_duration.argtypes = [c_void_p]
        lib.mm_player_scene_duration.restype = c_double
        lib.mm_player_object_count.argtypes = [c_void_p]
        lib.mm_player_object_count.restype = c_int
        lib.mm_player_path_length.argtypes = [c_void_p, c_char_p]
        lib.mm_player_path_length.restype = c_double
        lib.mm_player_subpath_count.argtypes = [c_void_p, c_char_p]
        lib.mm_player_subpath_count.restype = c_int
        lib.mm_player_property_at.argtypes = [c_void_p, c_char_p, c_char_p, c_double]
        lib.mm_player_property_at.restype = c_double
        lib.mm_player_ease.argtypes = [c_char_p, c_double]
        lib.mm_player_ease.restype = c_double

    def error(self) -> str:
        message = self._lib.mm_player_error()
        return message.decode("utf-8", "replace") if message else "unknown error"

    def ease(self, name: str, p: float) -> float:
        """The device's easing curves, directly. The fixed-vector test compares
        this against `core.easing` -- the contract, checked rather than trusted."""
        return float(self._lib.mm_player_ease(name.encode("utf-8"), float(p)))

    @property
    def raw(self):
        return self._lib


class LvglPlayer:
    """A :class:`~mementum_node.core.render_backend.Renderer` backed by C."""

    name = "lvgl"

    def __init__(self, library: PlayerLibrary | None = None):
        self._library = library or PlayerLibrary.instance()
        self._handle: int | None = None
        self._width = 0
        self._height = 0
        self._buffer = None

    # -- Renderer protocol ----------------------------------------------

    def bind(self, payload: bytes, scene: Scene, width: int, height: int) -> None:
        self._release()
        lib = self._library.raw
        handle = lib.mm_player_load(payload, int(width), int(height))
        if not handle:
            raise LvglPlayerError(self._library.error())
        self._handle = handle
        self._width, self._height = int(width), int(height)
        self._buffer = (ctypes.c_uint8 * (self._width * self._height * 4))()

    def render(self, scene_time: float) -> Frame:
        if self._handle is None:
            raise LvglPlayerError("player holds no scene")
        rc = self._library.raw.mm_player_render(
            self._handle, float(scene_time), self._buffer, len(self._buffer)
        )
        if rc != 0:
            raise LvglPlayerError(self._library.error())
        return Frame(self._width, self._height, bytearray(self._buffer))

    # -- introspection, for conformance tests ---------------------------

    def path_length(self, object_id: str) -> float:
        return float(
            self._library.raw.mm_player_path_length(self._handle, object_id.encode("utf-8"))
        )

    def subpath_count(self, object_id: str) -> int:
        return int(
            self._library.raw.mm_player_subpath_count(self._handle, object_id.encode("utf-8"))
        )

    def property_at(self, object_id: str, prop: str, scene_time: float) -> float:
        return float(
            self._library.raw.mm_player_property_at(
                self._handle, object_id.encode("utf-8"), prop.encode("utf-8"), float(scene_time)
            )
        )

    def scene_duration(self) -> float:
        return float(self._library.raw.mm_player_scene_duration(self._handle))

    # -- lifetime -------------------------------------------------------

    def _release(self) -> None:
        if self._handle is not None:
            self._library.raw.mm_player_destroy(self._handle)
            self._handle = None

    def __del__(self):  # pragma: no cover - interpreter teardown
        try:
            self._release()
        except Exception:
            pass

    def __repr__(self) -> str:
        return f"<LvglPlayer {self._width}x{self._height}>"
