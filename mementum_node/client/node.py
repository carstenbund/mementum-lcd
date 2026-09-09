"""A panel on the network: the participant core, wired to a real server.

Everything here is plumbing. `ParticipantCore` does the work -- registration,
late join, the schedule as state, evaluation against the shared clock -- and
this module gives it the three things the simulator gives it differently: a
clock synced over HTTP, a transport that is HTTP, and a sink that is a screen.

    node = Node("http://pi.local:8080", display="drm")
    node.start()          # register, listen, heartbeat, render

A node is a **client**. It does not serve the wall: the server distributes
scenes, and a panel with a couple of megabytes cannot hold the library that the
show draws from. Nothing here forecloses a device also running a server one day
-- that would be another process using `mementum_node.server` -- but no part of
this file assumes it.
"""

from __future__ import annotations

import threading
import time

from mementum_node.core.cache import AssetCache
from mementum_node.core.clock import CristianClock, SystemTimeSource
from mementum_node.core.participant import ParticipantCore
from mementum_node.core.protocol import (
    Capabilities, Display, NodeDescriptor, Position, TimeRequest,
)
from mementum_node.core.sink import HeadlessSink
from mementum_node.client.listener import Listener
from mementum_node.client.transport import HttpTransport

__all__ = ["Node", "ScreenSink"]

HEARTBEAT_FALLBACK_MS = 5000.0


class ScreenSink:
    """A composited frame onto a panel, through `drm_screen_lvgl`.

    The bitmap path: the participant renders, and the result is blitted into a
    full-screen layer. A panel that holds the *scene* instead is faster and is
    what the wall demo does -- but that is the screen evaluating on the node's
    behalf, and a node that is told what to show should be the one evaluating
    it. Both exist; this is the one that keeps the core in charge.
    """

    wants_pixels = True

    def __init__(self, width: int = 0, height: int = 0, display: str = "drm"):
        from mementum_node.screen import screen_service
        from mementum_node.screen.commands import CreateLayer

        self.service = screen_service(display=display, width=width, height=height)
        self.screen = self.service.renderer.screen
        self.width, self.height = self.screen.width, self.screen.height
        self.service.submit([CreateLayer("panel", self.width, self.height)])
        self.service.render_once(0.0)
        self.frames = 0

    def present(self, frame, scene_time: float) -> None:
        from mementum_node.screen.commands import PlaceRawBuffer

        if frame is None:
            return
        self.service.submit([PlaceRawBuffer("panel", frame.width, frame.height,
                                            data=bytes(frame.data))])
        self.service.render_once(scene_time)
        self.frames += 1

    def close(self) -> None:
        self.service.stop()


class Node:
    """One panel: registers, listens, heartbeats, renders."""

    def __init__(self, server: str, node_id: str = "panel", width: int = 450,
                 height: int = 250, display: str = "none", port: int = 0,
                 position: tuple[float, float] | None = None, fps: float = 30.0,
                 session=None, sink=None, renderer=None):
        self.server = server
        self.fps = fps
        self.sink = sink if sink is not None else _make_sink(display, width, height)

        self.transport = HttpTransport(server, node_id=node_id, session=session)
        self.clock = CristianClock(SystemTimeSource(), query=self._query_time)
        descriptor = NodeDescriptor(
            node_id=node_id, device="lcd", roles=("display",),
            display=Display(width, height, "rgba8888"),
            capabilities=Capabilities(scene_ir=1, vector=True, text=True, lottie=False),
            position=Position(*position) if position else None,
        )
        self.participant = ParticipantCore(
            descriptor, self.transport, self.clock, self.sink,
            cache=AssetCache(), renderer=renderer or _default_renderer(),
        )
        self.listener = Listener(self.participant, port=port)
        self.heartbeat_interval = HEARTBEAT_FALLBACK_MS
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    # -- lifecycle -------------------------------------------------------

    def _query_time(self) -> tuple[float, int]:
        reply = self.transport.request(TimeRequest())
        return reply.server_now, reply.leader_epoch

    def register(self) -> bool:
        """Bind a port first: the server pushes to us, so it has to be told
        where before it is told we exist."""
        self.listener.start()
        self.transport.port = self.listener.port
        ok = self.participant.register()
        if ok and self.transport.assigned_node_id:
            # A panel adopts the id the server gives it, as the LED firmware
            # adopts the one in "Your ID: 1".
            from dataclasses import replace

            self.participant.descriptor = replace(
                self.participant.descriptor, node_id=self.transport.assigned_node_id)
        return ok

    def start(self) -> bool:
        ok = self.register()
        for target in (self._heartbeat_loop, self._render_loop):
            thread = threading.Thread(target=target, daemon=True)
            thread.start()
            self._threads.append(thread)
        return ok

    def stop(self) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=1.0)
        self._threads.clear()
        self.listener.stop()
        self.sink.close()

    # -- the two loops ---------------------------------------------------

    def _heartbeat_loop(self) -> None:
        """The recovery path, and the clock's. A panel that missed a push --
        because it was rebooting, or the packet was lost -- learns the schedule
        here, which is why nothing has to be re-sent."""
        while not self._stop.is_set():
            try:
                if not self.participant.registered:
                    self.register()
                else:
                    self.participant.heartbeat()
            except Exception:                              # the server will come back
                pass
            self._stop.wait(self.heartbeat_interval / 1000.0)

    def _render_loop(self) -> None:
        interval = 1.0 / self.fps
        while not self._stop.is_set():
            try:
                self.participant.tick()
            except Exception:                              # one bad frame, not the show
                pass
            time.sleep(interval)

    # -- what it thinks is going on --------------------------------------

    @property
    def node_id(self) -> str:
        return self.participant.node_id

    def status(self) -> dict:
        status = self.participant.status()
        return {"node_id": status.node_id, "state": status.state,
                "scene_id": status.scene_id, "seq": status.seq,
                "scene_time": status.scene_time, "frames": status.frames_presented,
                "clock_offset": round(status.clock_offset, 2),
                "port": self.listener.port, "pushes": self.listener.received}


def _make_sink(display: str, width: int, height: int):
    if display in ("none", "", "headless"):
        return HeadlessSink()
    return ScreenSink(width=width, height=height, display=display)


def _default_renderer():
    """The C player where it is built, the Python reference otherwise. A node
    is allowed to be either (§3.7); what it may not be is silently different."""
    try:
        from mementum_node.players.lvgl import LvglPlayer, is_available

        if is_available():
            return LvglPlayer()
    except Exception:
        pass
    return None
