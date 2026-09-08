"""The participant core (proposal §14, §19; plan 4.4).

One core, shared by every node implementation. It registers, keeps a clock,
caches and loads scenes, evaluates them, and hands frames to a sink. What
differs between a display node, a stream node, a record node and a *simulated*
node is the clock, the transport and the sink -- nothing in this file.

That is not a convenience: it is the claim the simulator tests. If a simulated
node cannot be assembled out of this class by swapping those three adapters,
the boundaries are wrong (plan §3.1-§3.2).

The recovery model is the whole of §19 and it fits in one line:

    state = evaluate(scene, sharedNow() - displayAt)

A dropped frame, a missed PLAY and a late join differ only in how long the node
takes to notice and how much it must load first. There is no retry path, no
replay and no catch-up animation, because the correct picture is a function of
the shared clock and nothing else.
"""

from __future__ import annotations

import json
from typing import Any

from .cache import AssetCache, asset_hash
from .clock import CristianClock
from .framebuffer import Frame
from .geometry import nearest_arc_position
from .pacer import DisplayPacer
from .protocol import (
    AssetRequest,
    RippleCommand,
    Touch,
    Heartbeat,
    ManifestRequest,
    NodeDescriptor,
    Play,
    Ready,
    Register,
    Schedule,
    Status,
    StatusReply,
    Stop,
    Sync,
)
from .render_backend import ReferenceRenderer, Renderer
from .ripple import RIPPLE_DEFAULTS, Ripple
from .scene import Scene, parse_scene
from .sink import Sink
from .transport import TransportError

__all__ = ["ParticipantCore", "IDLE_POLICIES"]

#: What is displayed between scenes (proposal open question 5). Undefined in
#: the current firmware; named here so the answer is a setting, not an accident.
IDLE_POLICIES = ("blank", "hold")


class ParticipantCore:
    """A participant. Real code: the simulator adds nothing to it."""

    def __init__(
        self,
        descriptor: NodeDescriptor,
        transport,
        clock: CristianClock,
        sink: Sink,
        cache: AssetCache | None = None,
        pacer=None,
        idle_policy: str = "blank",
        renderer: Renderer | None = None,
    ):
        if idle_policy not in IDLE_POLICIES:
            raise ValueError(f"unknown idle policy: {idle_policy!r}")
        self.descriptor = descriptor
        self.transport = transport
        self.clock = clock
        self.sink = sink
        self.cache = cache if cache is not None else AssetCache()
        self.pacer = pacer if pacer is not None else DisplayPacer(30.0)
        self.idle_policy = idle_policy
        # The picture comes from *a* renderer, not *the* renderer: the Python
        # reference and the C/LVGL player are peers here (§3.7).
        self.renderer = renderer if renderer is not None else ReferenceRenderer()

        self.state = "idle"
        self.schedule: Schedule = Schedule()
        self.scene: Scene | None = None
        self.registered = False
        self.leader_epoch = 0
        self.fail_reason = ""

        # Instrumentation. Cheap, always on, and the basis of every assertion
        # the harness makes about recovery (plan §0.4).
        self.frames_presented = 0
        self.adoptions = 0
        self.recovered_by_heartbeat = 0
        self.pulls = 0
        self.pushes_received = 0
        self.touches = 0
        self.ripples_received = 0
        self.ripples_unsupported = 0
        self.last_scene_time: float | None = None
        self.last_frame: Frame | None = None

    # -- identity -------------------------------------------------------

    @property
    def node_id(self) -> str:
        return self.descriptor.node_id

    def __repr__(self) -> str:
        return f"<ParticipantCore {self.node_id} {self.state} seq={self.schedule.seq}>"

    # -- registration and heartbeat -------------------------------------

    def register(self) -> bool:
        """REGISTER, then adopt whatever schedule is already running.

        A node that joins mid-scene learns the schedule here, in its very first
        exchange -- that is late join, and it costs no extra mechanism."""
        self.clock.sync()
        try:
            ack = self.transport.request(Register(self.descriptor))
        except TransportError:
            self.registered = False
            return False
        self.registered = bool(ack.accepted)
        if not self.registered:
            self._fail_visibly(ack.reason or "registration refused")
            return False
        self._adopt(ack.schedule, ack.leader_epoch, via="register")
        return True

    def heartbeat(self) -> bool:
        """Periodic exchange. Re-syncs the clock and re-reads the schedule.

        This is the recovery path: whatever a node missed, it learns here,
        which is why the heartbeat interval *is* the worst-case recovery
        latency for a missed command (§19)."""
        if not self.registered:
            return self.register()
        self.clock.sync()
        try:
            ack = self.transport.request(
                Heartbeat(
                    node_id=self.node_id,
                    state=self.state,
                    known_seq=self.schedule.seq,
                    ready_scenes=self._ready_scenes(),
                )
            )
        except TransportError:
            return False
        if not ack.known:
            self.registered = False
            return self.register()
        self._adopt(ack.schedule, ack.leader_epoch, via="heartbeat")
        return True

    def _ready_scenes(self) -> tuple[int, ...]:
        return (self.schedule.scene_id,) if self.scene is not None else ()

    # -- pushed commands ------------------------------------------------

    def receive(self, message: Any) -> Any:
        """Handle a pushed control-plane message. Losing one of these is a
        latency problem, not a correctness one."""
        self.pushes_received += 1
        if isinstance(message, Play):
            self._adopt(message.schedule, message.schedule.leader_epoch, via="play")
            return None
        if isinstance(message, Stop):
            self._stop(message.leader_epoch)
            return None
        if isinstance(message, Sync):
            self.clock.sync()
            return None
        if isinstance(message, RippleCommand):
            self._ripple(message)
            return None
        if isinstance(message, Status):
            return self.status()
        raise ValueError(f"unhandled control message: {type(message).__name__}")

    # -- touch ----------------------------------------------------------

    def touch(self, x: float, y: float, strength: float = 1.0) -> bool:
        """Somebody touched this unit.

        It answers immediately — waiting for a round trip would make a touch
        feel broken — and reports the touch so the sequencer can spread it to
        the neighbours. The local response and the propagated one are the same
        ripple; only their start times differ.
        """
        now = self.clock.shared_now()
        self._start_ripple(x, y, now, strength)
        self.touches += 1
        try:
            self.transport.request(Touch(self.node_id, x, y, now, strength))
            return True
        except TransportError:
            return False  # the neighbours miss it; this unit still rippled

    def _ripple(self, command: RippleCommand) -> None:
        """A ripple arriving from another unit, timed by the sequencer."""
        self.ripples_received += 1
        self._start_ripple(command.x, command.y, command.start_at, command.strength)

    def _start_ripple(self, x: float, y: float, start_at: float, strength: float) -> None:
        if self.scene is None or not self.schedule.playing:
            return
        adder = getattr(self.renderer, "add_ripple", None)
        if adder is None:
            # Never silently: a node that cannot show the second layer must be
            # visible as such, not quietly inert (§18). Both real renderers can;
            # this is here so a third one cannot regress the property by
            # omission.
            self.ripples_unsupported += 1
            self.fail_reason = (
                f"renderer {type(self.renderer).__name__} cannot show touch ripples"
            )
            return
        origin = nearest_arc_position(self.scene, x, y)
        if origin is None:
            return
        adder(
            Ripple(
                origin=origin,
                # Ripples live in scene time, like everything the player draws.
                start=start_at - self.schedule.display_at,
                amplitude=RIPPLE_DEFAULTS["amplitude"] * strength,
            )
        )

    def status(self) -> StatusReply:
        return StatusReply(
            node_id=self.node_id,
            state=self.state,
            scene_id=self.schedule.scene_id,
            seq=self.schedule.seq,
            scene_time=self.scene_time(),
            frame_hash=self.last_frame.hash() if self.last_frame is not None else None,
            frames_presented=self.frames_presented,
            clock_offset=self.clock.offset,
        )

    # -- schedule reconciliation ----------------------------------------

    def _adopt(self, schedule: Schedule, leader_epoch: int, via: str) -> None:
        """Reconcile against the schedule *as state*.

        Three cases, in order of precedence: a new leader (the clock domain
        changed), a newer sequence number, or nothing to do."""
        if leader_epoch > self.leader_epoch:
            # Option C (§11): a leader change cancels the active scene and the
            # new leader schedules a fresh start. An intentional restart rather
            # than an unexplained jump.
            self.leader_epoch = leader_epoch
            self._stop(leader_epoch, reason="leader change")
            self.clock.sync()

        if schedule.seq <= self.schedule.seq and self.state != "idle":
            return
        if not schedule.playing:
            if schedule.seq > self.schedule.seq:
                self.schedule = schedule
                self._stop(leader_epoch)
            return
        if schedule.seq == self.schedule.seq and self.scene is not None:
            return

        if via == "heartbeat":
            self.recovered_by_heartbeat += 1
        self.schedule = schedule
        self.adoptions += 1
        self._load(schedule)

    def _load(self, schedule: Schedule) -> None:
        """Cached -> seek immediately. Uncached -> pull, then seek to the
        current time. Nobody else is delayed either way (§19)."""
        self.state = "loading"
        if self.cache.holds_scene(schedule.scene_id, schedule.scene_hash):
            payload = self.cache.get(schedule.scene_hash)
            if not self._bind(payload):
                return
            self.state = "playing"
            return
        try:
            manifest = self.transport.request(ManifestRequest(schedule.scene_id))
        except TransportError:
            self.state = "idle"
            self.scene = None
            return
        if not manifest.found:
            self._fail_visibly(f"no manifest for scene {schedule.scene_id}")
            return

        ok, why = self.descriptor.capabilities.satisfies(
            dict(manifest.requires, scene_ir=manifest.ir_version)
        )
        if not ok:
            # Fail visibly, never silently drift out of the shared timeline
            # (§18). The sequencer already knew this could happen -- it checks
            # playability before scheduling -- so reaching here is an error to
            # be seen, not smoothed over.
            self._fail_visibly(f"cannot render scene {schedule.scene_id}: {why}")
            return

        for digest in manifest.assets:
            if self.cache.has(digest):
                continue
            try:
                reply = self.transport.request(AssetRequest(digest))
            except TransportError:
                self.state = "idle"
                self.scene = None
                return
            if not reply.found or reply.payload is None:
                self._fail_visibly(f"asset {digest} unavailable")
                return
            self.cache.put(reply.payload, digest)
            self.pulls += 1

        payload = self.cache.get(schedule.scene_hash)
        if payload is None or asset_hash(payload) != schedule.scene_hash:
            self._fail_visibly(f"scene {schedule.scene_id} hash mismatch after pull")
            return
        self.cache.bind_scene(schedule.scene_id, schedule.scene_hash)
        if not self._bind(payload):
            return
        self.state = "playing"
        try:
            self.transport.request(
                Ready(self.node_id, schedule.scene_id, schedule.scene_hash)
            )
        except TransportError:
            pass  # READY is an optimisation for scheduling, not a requirement

    def _bind(self, payload: bytes) -> bool:
        """Parse the package and hand it to the renderer.

        A renderer that refuses the scene is a node that cannot show it, which
        must fail visibly rather than sit dark and in sync with nothing (§18).
        """
        scene = parse_scene(json.loads(payload.decode("utf-8")))
        try:
            self.renderer.bind(
                payload,
                scene,
                self.descriptor.display.width,
                self.descriptor.display.height,
            )
        except Exception as exc:
            self._fail_visibly(f"renderer refused the scene: {exc}")
            return False
        self.scene = scene
        return True

    def _stop(self, leader_epoch: int, reason: str = "") -> None:
        self.leader_epoch = max(self.leader_epoch, leader_epoch)
        self.state = "idle"
        self.fail_reason = reason
        if self.idle_policy == "blank":
            self.last_frame = None
            self.last_scene_time = None

    def _fail_visibly(self, reason: str) -> None:
        self.state = "incapable"
        self.fail_reason = reason
        self.scene = None
        self.last_frame = None

    # -- playback -------------------------------------------------------

    def scene_time(self) -> float | None:
        """``sharedNow() - displayAt``. The only source of playback position."""
        if self.state != "playing" or not self.schedule.playing:
            return None
        return self.clock.shared_now() - self.schedule.display_at

    def tick(self, now: float | None = None) -> bool:
        """One pacer step. Returns True if a frame was presented."""
        if self.state != "playing" or self.scene is None:
            return False
        now = self.clock.shared_now() if now is None else now
        scene_time = now - self.schedule.display_at
        if scene_time < 0.0:
            return False  # pre-roll: scheduled, not started
        duration = self.schedule.duration or self.scene.duration
        if duration and scene_time > duration:
            self._stop(self.leader_epoch, reason="scene ended")
            return False
        return self.pacer.step(now, lambda: self._present(scene_time))

    def _present(self, scene_time: float) -> None:
        frame = self.compose(scene_time) if self.sink.wants_pixels else None
        if frame is not None:
            self.last_frame = frame
        self.last_scene_time = scene_time
        self.frames_presented += 1
        self.sink.present(frame, scene_time)

    def compose(self, scene_time: float) -> Frame:
        """The picture at an arbitrary scene time. Pure with respect to the
        node: calling it does not disturb playback, which is what makes capture
        and cross-node buffer comparison safe to do at any moment."""
        if self.scene is None:
            raise RuntimeError(f"node {self.node_id} holds no scene")
        return self.renderer.render(scene_time)
