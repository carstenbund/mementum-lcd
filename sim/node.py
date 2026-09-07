"""Substitution 3 of 3, and the assembly (plan §3.1-§3.2).

A simulated node is the **real** ``ParticipantCore`` with three adapters
swapped: a virtual clock, an in-process transport, and a headless sink. This
module is therefore assembly only -- and deliberately so. If a simulated node
ever needs logic that a real node does not have, the boundaries are wrong and
that is the finding, not a thing to work around (risk R11).

The sink substitution costs nothing conceptually: a headless node still has a
complete composited frame in memory (§3.6). It is not invisible, merely not
scanned out.
"""

from __future__ import annotations

from mementum_node.core.cache import AssetCache
from mementum_node.core.clock import CristianClock
from mementum_node.core.framebuffer import Frame
from mementum_node.core.pacer import DisplayPacer
from mementum_node.core.participant import ParticipantCore
from mementum_node.core.protocol import Capabilities, Display, NodeDescriptor
from mementum_node.core.render_backend import ReferenceRenderer, Renderer
from mementum_node.core.sink import HeadlessSink, NullSink

from .clock import NodeTimeSource, SimulationClock
from .transport import InProcessTransport

__all__ = ["SimNode"]


class SimNode:
    """One simulated participant. Owns no protocol logic of its own."""

    def __init__(
        self,
        node_id: str,
        master: SimulationClock,
        bus: InProcessTransport,
        *,
        device: str = "esp32-s3",
        roles: tuple[str, ...] = ("display",),
        display: Display | None = None,
        capabilities: Capabilities | None = None,
        fps: float = 30.0,
        compositing: bool = True,
        offset_ms: float = 0.0,
        drift_ppm: float = 0.0,
        jitter_ms: float = 0.0,
        seed: int = 0,
        idle_policy: str = "blank",
        cache: AssetCache | None = None,
        renderer: Renderer | None = None,
    ):
        self.node_id = node_id
        self.master = master
        self.bus = bus

        # -- the three substitutions ------------------------------------
        self.time_source = NodeTimeSource(master, offset_ms, drift_ppm, jitter_ms, seed)
        self.transport = bus.client(node_id, self.time_source)
        self.clock = CristianClock(self.time_source, self.transport.time_query)
        self.sink = HeadlessSink() if compositing else NullSink()

        # Not a substitution -- a choice. A node runs the Python reference or
        # the C/LVGL player exactly as a real one would, and the swarm can mix
        # them (§3.7).
        self.renderer = renderer if renderer is not None else ReferenceRenderer()

        # -- everything below this line is the real thing ---------------
        descriptor = NodeDescriptor(
            node_id=node_id,
            device=device,
            roles=roles,
            display=display if display is not None else Display(480, 320, "rgb565"),
            capabilities=capabilities if capabilities is not None else Capabilities(),
        )
        self.core = ParticipantCore(
            descriptor=descriptor,
            transport=self.transport,
            clock=self.clock,
            sink=self.sink,
            cache=cache,
            pacer=DisplayPacer(fps),
            idle_policy=idle_policy,
            renderer=self.renderer,
        )
        bus.attach(node_id, self)

        self.next_heartbeat_at: float | None = None
        self.joined_at: float | None = None

    # -- the harness drives these; each one is a straight delegation ----
    #
    # Each entry point settles the node's stall afterwards: a round trip stalls
    # the node's clock while it is in flight (so the RTT it measures is real),
    # and that stall must not leak into the next thing the node does.

    def receive(self, message):
        try:
            return self.core.receive(message)
        finally:
            self.time_source.stall_ms = 0.0

    def register(self) -> bool:
        self.joined_at = self.master.now
        try:
            return self.core.register()
        finally:
            self.time_source.stall_ms = 0.0

    def heartbeat(self) -> bool:
        try:
            return self.core.heartbeat()
        finally:
            self.time_source.stall_ms = 0.0

    def tick(self) -> bool:
        try:
            return self.core.tick()
        finally:
            self.time_source.stall_ms = 0.0

    # -- observation ----------------------------------------------------

    @property
    def state(self) -> str:
        return self.core.state

    @property
    def frame(self) -> Frame | None:
        return self.core.last_frame

    @property
    def scene_time(self) -> float | None:
        return self.core.scene_time()

    def compose(self, scene_time: float) -> Frame:
        """Composite this node's picture at a given scene time, without
        disturbing playback. The whole basis of buffer-level assertion."""
        return self.core.compose(scene_time)

    def frame_hash(self) -> str | None:
        """The device-side check, modelled (§3.6): each node hashes its
        rendered frame, and two nodes at the same sceneTime must agree."""
        frame = self.core.last_frame
        return frame.hash() if frame is not None else None

    @property
    def renderer_name(self) -> str:
        return getattr(self.renderer, "name", "unknown")

    def __repr__(self) -> str:
        return (
            f"<SimNode {self.node_id} {self.state} renderer={self.renderer_name} "
            f"frames={self.core.frames_presented}>"
        )
