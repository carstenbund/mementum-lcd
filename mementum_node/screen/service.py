"""A screen service, from whichever half of the stack is on the machine.

`drm_screen` owns this loop: a command queue, a dirty flag, one display thread,
`submit()` that returns immediately. Where it is installed, that is what runs --
this module adds nothing to it but a scene clock and a frame type.

Where it is not, the loop is reproduced here in the stdlib alone. That is not
duplication for its own sake: `drm_screen` needs numpy and `drm_display`, and a
node is allowed to be a Pi Zero, an ESP32's host-side test, or a machine with
neither (plan §14, invariant: the core is stdlib-only). The renderer is the
same object in both cases, so the picture is the same either way.

    screen_service(display="drm")        on a panel
    screen_service(display="memory", width=450, height=250)   headless
"""

from __future__ import annotations

import queue
import threading
import time

from drm_screen_lvgl import LvglRenderer, LvglScreen

from mementum_node.core.framebuffer import Frame

__all__ = ["Screen", "screen_service", "SimpleScreenService", "HAVE_DRM_SCREEN"]

try:
    from drm_screen import ScreenService as _DrmScreenService

    HAVE_DRM_SCREEN = True
except ImportError:  # pragma: no cover - exercised on hosts without drm_screen
    HAVE_DRM_SCREEN = False


class Screen(LvglScreen):
    """The plugin's screen, speaking this project's buffer type.

    Everything about a screen is upstream now; the one thing that is not is
    that a frame here is a :class:`~mementum_node.core.framebuffer.Frame`, so
    the same capture, PNG and comparison tools work on it as on a rendered
    player frame.
    """

    def frame(self) -> Frame:
        return Frame(self.width, self.height, bytearray(self.snapshot()))


class SimpleScreenService:
    """`drm_screen.ScreenService`, in the stdlib, for a node without numpy.

    Same words, same order, same guarantees: `submit()` is non-blocking, the
    render thread drains the queue and applies mutations, and nothing is drawn
    unless something changed -- except that a layer holding a scene is always
    changing, because the picture is a function of the clock.
    """

    def __init__(self, renderer, fps: int = 30, clock=None):
        self.renderer = renderer
        self.screen = renderer.screen
        self.fps = fps
        self.queue: "queue.Queue[list]" = queue.Queue()
        self.dirty = True
        self.frames = 0
        self._clock = clock
        self._started_at = time.monotonic()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    # -- client-facing, non-blocking ------------------------------------

    def submit(self, commands) -> None:
        self.queue.put(list(commands))

    def hit_test(self, x: int, y: int) -> str | None:
        with self._lock:
            return self.renderer.hit_test(x, y)

    # -- the loop -------------------------------------------------------

    def scene_time_ms(self) -> float:
        """What time the picture is at. Pass the node's shared clock and the
        frame is `evaluate(sharedNow() - displayAt)` with nothing accumulated."""
        if self._clock is not None:
            return float(self._clock())
        return (time.monotonic() - self._started_at) * 1000.0

    def _drain(self) -> None:
        while True:
            try:
                batch = self.queue.get_nowait()
            except queue.Empty:
                return
            for command in batch:
                self.renderer.apply(command)
            self.dirty = True

    def render_once(self, scene_time_ms: float | None = None) -> None:
        with self._lock:
            self._drain()
            if not (self.dirty or self.renderer.animating):
                return
            self.renderer.present(
                self.scene_time_ms() if scene_time_ms is None else scene_time_ms
            )
            self.frames += 1
            self.dirty = False

    def _run(self) -> None:
        interval = 1.0 / self.fps
        while not self._stop.is_set():
            self.render_once()
            time.sleep(interval)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self.renderer.close()


def screen_service(display: str = "drm", width: int = 0, height: int = 0,
                   fps: int = 30, clock=None):
    """A running screen, on the best service this machine has.

    Returns `drm_screen.ScreenService` where that package is installed -- the
    real one, with the LVGL renderer inside it -- and :class:`SimpleScreenService`
    otherwise. Both answer `submit`, `hit_test`, `render_once`, `start`, `stop`,
    and both hold the same renderer, so nothing above them can tell which it got.
    """
    renderer = LvglRenderer(screen=Screen(width, height, display))
    if HAVE_DRM_SCREEN:
        return _DrmScreenService(renderer=renderer, fps=fps, clock=clock)
    return SimpleScreenService(renderer, fps=fps, clock=clock)
