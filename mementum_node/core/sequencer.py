"""The sequencer -- registry, schedule and fan-out (proposal §18, §19, §20).

Server-side, and just as real as the participant core: the simulator drives this
class, not a stand-in for it.

Three things it must get right:

* **The schedule is state.** ``PLAY`` is pushed, but the same schedule is
  returned from every REGISTER and HEARTBEAT. Everything about recovery follows
  from that one property (§19).
* **Fan-out is concurrent.** The single hard requirement the ~300-node design
  bound places on the server (§20). Sequential fan-out to a few hundred nodes
  is seconds -- already past ``DISPLAY_LEAD_MS``.
* **Playability is decided before scheduling.** Registration carries
  capabilities so an unplayable scene is caught here rather than discovered at
  ``displayAt`` (§18).

It also runs the **show**. A :class:`~mementum_node.core.guide.Guide` is a
running order with timecodes; the sequencer holds one, keeps an epoch in shared
time, and pushes each cue ``lead_ms`` before its moment so that the moment
itself is a ``displayAt`` every node already knows what to do with. Scene cues
become the schedule -- so a node joining halfway through a show is the ordinary
late-join case, not a new mechanism -- and effect cues are transient, exactly
like a touch. No new wire message was needed for any of it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .clock import Clock
from .guide import Cue, Guide, format_timecode, parse_timecode
from .library import SceneLibrary
from .protocol import (
    DISPLAY_LEAD_MS,
    RippleCommand,
    Touch,
    HEARTBEAT_INTERVAL_MS,
    AssetReply,
    AssetRequest,
    Heartbeat,
    HeartbeatAck,
    ManifestReply,
    ManifestRequest,
    NodeDescriptor,
    Play,
    Ready,
    Register,
    RegisterAck,
    Schedule,
    Stop,
    Sync,
    TimeReply,
    TimeRequest,
)
from .transport import PushResult

__all__ = [
    "INCAPABLE_POLICIES",
    "PlayResult",
    "RegisteredNode",
    "Sequencer",
    "ShowTick",
    "TOUCH_SPEED_M_S",
    "TouchResult",
    "derive_display_lead",
]

#: How fast a touch crosses the installation, in metres per second. An artistic
#: number, not a network one — slow enough to watch a gesture travel. It must
#: stay slower than fan-out, or a unit would be asked to ripple before it has
#: been told to; `Sequencer.touch` enforces that by never scheduling sooner
#: than the display lead.
TOUCH_SPEED_M_S = 2.4

#: What to do when a registered node cannot render a scene (proposal open
#: question). Named rather than implied, so the choice is visible.
INCAPABLE_POLICIES = ("schedule", "refuse", "skip")


@dataclass
class RegisteredNode:
    descriptor: NodeDescriptor
    registered_at: float
    last_seen: float
    state: str = "idle"
    known_seq: int = 0
    ready_scenes: tuple[int, ...] = ()

    @property
    def node_id(self) -> str:
        return self.descriptor.node_id


@dataclass
class ShowTick:
    """What one tick of the show did.

    Empty is the ordinary case -- a show is mostly waiting -- so this is a
    record of the moments, not a running commentary.
    """

    show_time: float = 0.0
    fired: list[Cue] = field(default_factory=list)
    plays: list["PlayResult"] = field(default_factory=list)
    touches: list["TouchResult"] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.fired or self.refused)

    def __str__(self) -> str:
        # A cue is logged at the timecode the running order gives it, not at
        # the moment it was pushed -- which is a display lead earlier, and is
        # the server's business rather than the show caller's.
        if not self:
            return f"{format_timecode(self.show_time)}  --"
        lines = [f"{format_timecode(cue.at)}  {cue.action:<9} {cue.name}" for cue in self.fired]
        lines += [f"{format_timecode(self.show_time)}  refused  {why}" for why in self.refused]
        return "\n".join(lines)


@dataclass
class TouchResult:
    """What one touch turned into: a ripple per unit, timed by distance."""

    origin: str
    seq: int
    scheduled: dict[str, float] = field(default_factory=dict)
    pushes: list[PushResult] = field(default_factory=list)

    @property
    def reached(self) -> int:
        return sum(1 for p in self.pushes if p.delivered)

    @property
    def spread_ms(self) -> float:
        """How long the gesture takes to cross the whole installation."""
        if not self.scheduled:
            return 0.0
        return max(self.scheduled.values()) - min(self.scheduled.values())


@dataclass
class PlayResult:
    schedule: Schedule
    pushes: list[PushResult] = field(default_factory=list)
    skipped: tuple[str, ...] = ()
    refused: str = ""
    #: What each unit was actually told. Equal to `schedule` for every unit in
    #: the ordinary case; different when the wall is not one picture -- a
    #: staggered start, a sentence dealt across units, a word running through.
    schedules: dict[str, Schedule] = field(default_factory=dict)

    @property
    def scheduled(self) -> bool:
        return not self.refused

    @property
    def delivered(self) -> int:
        return sum(1 for p in self.pushes if p.delivered)

    @property
    def fanout_ms(self) -> float:
        """Time to the *last* node. This is the number ``DISPLAY_LEAD_MS`` is
        derived from (§20), not a constant someone chose."""
        return max((p.elapsed_ms for p in self.pushes), default=0.0)


def derive_display_lead(fanout_ms: float, safety: float = 2.0, floor_ms: float = 250.0) -> float:
    """``DISPLAY_LEAD_MS`` from measured fan-out, with headroom.

    A simulated number here is a *design* property; the same measurement on a
    real AP is a physical one, and the divergence between them is itself a
    deliverable (risk R9).
    """
    return max(floor_ms, fanout_ms * safety)


class Sequencer:
    def __init__(
        self,
        clock: Clock,
        library: SceneLibrary | None = None,
        fanout: Any = None,
        lead_ms: float = DISPLAY_LEAD_MS,
        heartbeat_interval: int = HEARTBEAT_INTERVAL_MS,
        incapable_policy: str = "schedule",
    ):
        if incapable_policy not in INCAPABLE_POLICIES:
            raise ValueError(f"unknown incapable policy: {incapable_policy!r}")
        self.clock = clock
        self.library = library if library is not None else SceneLibrary()
        self.fanout = fanout
        self.lead_ms = lead_ms
        self.heartbeat_interval = heartbeat_interval
        self.incapable_policy = incapable_policy

        self.nodes: dict[str, RegisteredNode] = {}
        self.schedule = Schedule()
        #: Per unit, because a unit is what has a schedule. The wall-wide
        #: schedule above is the common case where every entry is the same one;
        #: a staggered or dealt cue simply stops that being true, and nothing
        #: else has to change -- each node still recovers its own schedule from
        #: the ordinary registration reply (§19).
        self.schedules: dict[str, Schedule] = {}
        self.leader_epoch = 1

        # -- the show. A guide is loaded, then started; until it is started
        # there is no epoch and nothing is due, because a timecode means
        # nothing without one.
        self.guide: Guide | None = None
        self.show_epoch: float | None = None
        self.text_compiler: Any = None       # str -> scene document, composer-side
        self._fired_through: float = 0.0
        self._compiled_text: dict[str, int] = {}
        self.show_history: list[ShowTick] = []
        self.seq = 0
        self.play_history: list[PlayResult] = []
        self.touch_seq = 0
        self.touch_speed = TOUCH_SPEED_M_S
        self.touch_history: list[TouchResult] = []

    # -- request handling (the node -> server direction) -----------------

    def handle(self, message: Any) -> Any:
        now = self.clock.shared_now()
        if isinstance(message, Register):
            return self._register(message.descriptor, now)
        if isinstance(message, Heartbeat):
            return self._heartbeat(message, now)
        if isinstance(message, TimeRequest):
            return TimeReply(server_now=now, leader_epoch=self.leader_epoch)
        if isinstance(message, ManifestRequest):
            return self._manifest(message.scene_id)
        if isinstance(message, AssetRequest):
            payload = self.library.asset(message.asset_hash)
            return AssetReply(message.asset_hash, payload, payload is not None)
        if isinstance(message, Touch):
            return self.touch(message)
        if isinstance(message, Ready):
            node = self.nodes.get(message.node_id)
            if node is not None and message.scene_id not in node.ready_scenes:
                node.ready_scenes = node.ready_scenes + (message.scene_id,)
            return None
        raise ValueError(f"unhandled request: {type(message).__name__}")

    def _register(self, descriptor: NodeDescriptor, now: float) -> RegisterAck:
        self.nodes[descriptor.node_id] = RegisteredNode(
            descriptor=descriptor, registered_at=now, last_seen=now
        )
        # The running schedule goes back in the acknowledgement: late join is
        # not a separate mechanism, it is the ordinary registration reply.
        return RegisterAck(
            accepted=True,
            server_now=now,
            leader_epoch=self.leader_epoch,
            schedule=self.schedules.get(descriptor.node_id, self.schedule),
            heartbeat_interval=self.heartbeat_interval,
        )

    def _heartbeat(self, message: Heartbeat, now: float) -> HeartbeatAck:
        node = self.nodes.get(message.node_id)
        if node is None:
            return HeartbeatAck(
                server_now=now, leader_epoch=self.leader_epoch,
                schedule=self.schedules.get(message.node_id, self.schedule), known=False
            )
        node.last_seen = now
        node.state = message.state
        node.known_seq = message.known_seq
        node.ready_scenes = message.ready_scenes
        return HeartbeatAck(
            server_now=now, leader_epoch=self.leader_epoch,
            schedule=self.schedules.get(message.node_id, self.schedule),
        )

    def _manifest(self, scene_id: int) -> ManifestReply:
        package = self.library.get(scene_id)
        if package is None:
            return ManifestReply(scene_id, "", 0, {}, (), 0, found=False)
        return ManifestReply(
            scene_id=package.scene_id,
            scene_hash=package.digest,
            ir_version=package.ir_version,
            requires=dict(package.requires),
            assets=(package.digest,),
            duration=package.duration,
        )

    # -- scheduling (the server -> node direction) -----------------------

    def playability(self, scene_id: int) -> dict[str, str]:
        """Node ids that cannot render this scene, with the reason. Empty is
        the good case, and it is known *before* anything is scheduled."""
        package = self.library.get(scene_id)
        if package is None:
            return {node_id: "unknown scene" for node_id in self.nodes}
        out = {}
        for node_id, node in self.nodes.items():
            ok, why = node.descriptor.capabilities.satisfies(package.requires)
            if not ok:
                out[node_id] = why
        return out

    def play(self, scene_id: int, at: float | None = None) -> PlayResult:
        package = self.library.get(scene_id)
        if package is None:
            return PlayResult(self.schedule, refused=f"unknown scene {scene_id}")

        incapable = self.playability(scene_id)
        skipped: tuple[str, ...] = ()
        if incapable:
            if self.incapable_policy == "refuse":
                return PlayResult(
                    self.schedule,
                    refused=f"{len(incapable)} node(s) cannot render scene {scene_id}",
                )
            if self.incapable_policy == "skip":
                skipped = tuple(sorted(incapable))
            # "schedule": the incapable nodes fail visibly (§18). They are not
            # hidden -- they are in ``skipped`` either way for reporting.
            else:
                skipped = tuple(sorted(incapable))

        self.seq += 1
        display_at = self.clock.shared_now() + self.lead_ms if at is None else at
        self.schedule = Schedule(
            state="playing",
            scene_id=package.scene_id,
            scene_hash=package.digest,
            seq=self.seq,
            display_at=display_at,
            duration=package.duration,
            leader_epoch=self.leader_epoch,
        )
        targets = self._targets(skipped if self.incapable_policy == "skip" else ())
        self.schedules = {node_id: self.schedule for node_id in targets}
        result = PlayResult(self.schedule, self._push(targets, Play(self.schedule)), skipped,
                            schedules=dict(self.schedules))
        self.play_history.append(result)
        return result

    def units_in_order(self, order: Iterable[str] = (), reverse: bool = False) -> list[str]:
        """The units as the room reads them: along a row, then down.

        "the first unit" has to mean something physical for a sentence to be
        dealt across the wall, and where a unit stands is the only thing that
        knows. Units with no position keep their registration order, after the
        ones that have one.

        An explicit ``order`` overrides all of that, because the positions were
        typed in by a person and the wall was hung by one too -- `/identify` is
        how you find out which is which.
        """
        explicit = [node_id for node_id in order if node_id in self.nodes]
        if explicit:
            return list(reversed(explicit)) if reverse else explicit

        placed, unplaced = [], []
        for node_id, node in self.nodes.items():
            position = node.descriptor.position
            (placed if position is not None else unplaced).append(node_id)
        placed.sort(key=lambda node_id: (
            self.nodes[node_id].descriptor.position.y,
            self.nodes[node_id].descriptor.position.x,
        ))
        units = placed + unplaced
        return list(reversed(units)) if reverse else units

    def assign(self, assignments: "list[tuple[str, int, float]]") -> PlayResult:
        """Give units different things to show, or the same thing at different
        moments. One sequence number for the whole gesture, because it is one.

        This is what a staggered start, a dealt sentence and a word running
        through the wall all are underneath: a schedule per unit. Every other
        property survives it -- each unit still evaluates
        ``sharedNow() - displayAt``, still recovers its own schedule from the
        ordinary registration reply, and still knows nothing about the others.
        """
        if not assignments:
            return PlayResult(self.schedule, refused="nothing to assign")

        self.seq += 1
        pushes: list[PushResult] = []
        schedules: dict[str, Schedule] = {}
        refused: list[str] = []

        for node_id, scene_id, display_at in assignments:
            package = self.library.get(scene_id)
            if package is None:
                refused.append(f"unknown scene {scene_id}")
                continue
            if node_id not in self.nodes:
                refused.append(f"no unit {node_id!r}")
                continue
            schedule = Schedule(
                state="playing",
                scene_id=package.scene_id,
                scene_hash=package.digest,
                seq=self.seq,
                display_at=display_at,
                duration=package.duration,
                leader_epoch=self.leader_epoch,
            )
            schedules[node_id] = schedule
            pushes.extend(self._push([node_id], Play(schedule)))

        if not schedules:
            self.seq -= 1
            return PlayResult(self.schedule, refused="; ".join(refused) or "nothing to assign")

        self.schedules.update(schedules)
        # The wall-wide schedule is the earliest one: it is what a unit that
        # was not addressed, or that registers later, should fall in with.
        self.schedule = min(schedules.values(), key=lambda s: s.display_at)
        result = PlayResult(self.schedule, pushes, refused="; ".join(refused),
                            schedules=schedules)
        self.play_history.append(result)
        return result


    # -- the show (guide.py) ---------------------------------------------

    def load_guide(self, guide: Guide, text_compiler: Any = None) -> list[str]:
        """Take a running order. Returns what is wrong with it, if anything.

        Checked here rather than at the moment a cue fires, for the same reason
        playability is checked before scheduling: the good case is that a
        problem is known while somebody can still do something about it.
        """
        self.guide = guide
        if text_compiler is not None:
            self.text_compiler = text_compiler
        self.show_epoch = None
        self._fired_through = 0.0

        problems: list[str] = []
        for cue in guide:
            if cue.live and self.text_compiler is None:
                problems.append(f"{format_timecode(cue.at)}: no text compiler for {cue.text!r}")
            elif cue.is_scene and cue.scene_id and self.library.get(cue.scene_id) is None:
                problems.append(f"{format_timecode(cue.at)}: unknown scene {cue.scene_id}")
            elif cue.is_effect and cue.unit and cue.unit not in self.nodes:
                problems.append(f"{format_timecode(cue.at)}: no unit {cue.unit!r}")
        return problems

    @property
    def show_running(self) -> bool:
        return self.guide is not None and self.show_epoch is not None

    def show_time(self, now: float | None = None) -> float | None:
        """Where the show is, in its own time. None when nothing is running."""
        if not self.show_running:
            return None
        now = self.clock.shared_now() if now is None else now
        return now - float(self.show_epoch)

    def start_show(self, at: float | None = None) -> ShowTick:
        """Set the epoch and call whatever is already due.

        The epoch is one display lead ahead, so the cue at 00:00:00 is pushed
        before its moment rather than after it -- the whole point of the lead.
        """
        if self.guide is None:
            raise RuntimeError("no guide loaded")
        now = self.clock.shared_now()
        self.show_epoch = (now + self.lead_ms) if at is None else at
        self._fired_through = -1.0        # so a cue at exactly 0 is still due
        self._compiled_text.clear()
        return self.tick(now)

    def stop_show(self) -> ShowTick:
        """End the show and idle the wall. The guide stays loaded."""
        tick = ShowTick(show_time=self.show_time() or 0.0)
        self.show_epoch = None
        self.stop()
        return tick

    def seek(self, timecode: Any) -> ShowTick:
        """Move the show to a point and put the right thing on the wall.

        Seeking is not a special path either: the epoch moves, the governing
        scene cue is played with its own (now past) displayAt, and every node
        evaluates into the middle of it exactly as a late joiner does.
        """
        from .guide import parse_timecode

        if self.guide is None:
            raise RuntimeError("no guide loaded")
        target = parse_timecode(timecode)
        now = self.clock.shared_now()
        self.show_epoch = now + self.lead_ms - target
        self._fired_through = target

        tick = ShowTick(show_time=target)
        governing = self.guide.scene_at(target)
        if governing is not None:
            self._fire(governing, tick)
        self.show_history.append(tick)
        return tick

    def tick(self, now: float | None = None) -> ShowTick:
        """Push everything whose moment falls inside the next display lead.

        Called as often as the host likes: the window is half-open, so a cue
        fires exactly once however fine the ticking is, and a tick that arrives
        late fires everything it missed rather than dropping it.
        """
        if not self.show_running:
            return ShowTick()
        now = self.clock.shared_now() if now is None else now
        show_time = now - float(self.show_epoch)
        horizon = show_time + self.lead_ms

        tick = ShowTick(show_time=show_time)
        for cue in self.guide.due(self._fired_through, horizon):
            self._fire(cue, tick)
        self._fired_through = max(self._fired_through, horizon)
        if tick:
            self.show_history.append(tick)
        return tick

    # -- firing one cue --------------------------------------------------

    def _fire(self, cue: Cue, tick: ShowTick) -> None:
        moment = float(self.show_epoch) + cue.at
        if cue.is_scene:
            result = self._fire_scene(cue, moment, tick)
            if result is None:
                return
            tick.plays.append(result)
            if result.refused:
                tick.refused.append(f"{cue.name}: {result.refused}")
                return
        else:
            self._fire_effect(cue, moment, tick)
        tick.fired.append(cue)

    def _fire_scene(self, cue: Cue, moment: float, tick: ShowTick) -> "PlayResult | None":
        """One cue, however it reaches the units.

        Two independent questions, which `mementum-led` was right to keep
        apart: *what* each unit shows (`spread`) and *when* it starts
        (`stagger`). The ordinary answer to both is "the same thing, at the same
        moment", and then the wall is one picture. Any other answer is a
        schedule per unit, which is the only mechanism underneath all of them.
        """
        scene_ids: list[int]
        if cue.spread == "deal":
            scene_ids = list(cue.scene_ids)
            if not scene_ids:
                for word in cue.words:
                    scene_id = self._compile_text(cue, tick, word)
                    if scene_id is None:
                        return None
                    scene_ids.append(scene_id)
            if not scene_ids:
                return PlayResult(self.schedule, refused="nothing to deal")
        else:
            scene_id = cue.scene_id
            if cue.live:
                scene_id = self._compile_text(cue, tick, cue.text)
                if scene_id is None:
                    return None
            scene_ids = [scene_id]

        return self.sweep(scene_ids, at=moment, stagger=cue.stagger, factor=cue.factor,
                          reverse=cue.reverse, order=cue.order)

    def sweep(self, scenes: "int | list[int]", at: float, stagger: Any = "",
              factor: float = 1.0, reverse: bool = False,
              order: Iterable[str] = ()) -> PlayResult:
        """One or more scenes across the units, with a delay between neighbours.

        The whole of `spread` and `stagger` lands here, and so does `/effect` on
        the control server -- they are the same gesture asked for in two places,
        and it would be a poor sort of show controller that had two of it.
        """
        scene_ids = [scenes] if isinstance(scenes, int) else list(scenes)
        if not scene_ids:
            return PlayResult(self.schedule, refused="nothing to play")

        units = self.units_in_order(order=order, reverse=reverse)
        step = self.stagger_ms(stagger, scene_ids[0], factor=factor)
        if not step and len(scene_ids) == 1:
            return self.play(scene_ids[0], at=at)

        # Fewer scenes than units and the sentence repeats along the wall,
        # rather than leaving the rest of it holding something stale -- a wall
        # of words, which is the thing worth looking at.
        return self.assign([
            (node_id, scene_ids[index % len(scene_ids)], at + index * step)
            for index, node_id in enumerate(units)
        ])

    def stagger_ms(self, stagger: Any, scene_id: int = 0, factor: float = 1.0) -> float:
        """How far apart neighbouring units start.

        The three modes are `mementum-led`'s, and mean the same thing here:

        * ``auto`` -- one full go of the content per unit, so it hops from one
          to the next as a whole;
        * ``tile`` -- one panel width of travel, so the content tiles into a
          single long marquee: what leaves one unit enters the next. A
          travelling scene crosses two panel widths over its duration, so a
          panel is half of it;
        * a time -- exactly that.

        ``factor`` tunes the first two: below 1 they overlap into a glide, above
        1 they leave a gap, or compensate for the bezel between real panels.
        """
        if stagger in ("", None):
            return 0.0
        package = self.library.get(scene_id)
        duration = float(package.duration) if package else 0.0
        if stagger == "auto":
            return (duration or 1000.0) * factor
        if stagger == "tile":
            return ((duration / 2.0) if duration else 1000.0) * factor
        return parse_timecode(stagger)

    def _compile_text(self, cue: Cue, tick: ShowTick, text: str) -> int | None:
        """Words into a scene, at the moment the cue fires.

        The escape hatch: a line decided during the show rather than before it.
        It is still the composer that compiles -- the callable is handed in
        from outside the core -- and it is still a scene that reaches the
        device, which holds no font and learns nothing new."""
        if text in self._compiled_text:
            return self._compiled_text[text]
        if self.text_compiler is None:
            tick.refused.append(f"{cue.name}: no text compiler configured")
            return None
        try:
            package = self.library.add(self.text_compiler(text))
        except Exception as error:                      # a bad line is not a crash
            tick.refused.append(f"{cue.name}: {error}")
            return None
        self._compiled_text[text] = package.scene_id
        return package.scene_id

    def _fire_effect(self, cue: Cue, moment: float, tick: ShowTick) -> None:
        """An effect is a moment, not a state: it is pushed and forgotten.

        Named on a unit, it travels from there at TOUCH_SPEED_M_S like a touch,
        because that is what it is -- the crowd being excited from one place.
        Unnamed, every unit is excited at once, which is a different gesture
        and should look like one.
        """
        amplitude = float(cue.params.get("amplitude", 0.0))
        strength = float(cue.params.get("strength", 1.0))
        x = float(cue.params.get("x", 0.5))
        y = float(cue.params.get("y", 0.5))

        if cue.unit:
            if cue.unit not in self.nodes:
                tick.refused.append(f"{cue.name}: no unit {cue.unit!r}")
                return
            tick.touches.append(self.touch(
                Touch(node_id=cue.unit, x=x, y=y, at=moment, strength=strength),
                amplitude=amplitude,
            ))
            return

        self.touch_seq += 1
        command = RippleCommand(
            origin_node="", x=x, y=y, start_at=moment,
            amplitude=amplitude, strength=strength, seq=self.touch_seq,
        )
        self._push(self._targets(()), command)

    def touch(self, message: Touch, amplitude: float = 0.0) -> TouchResult:
        """Turn one unit's touch into a ripple on all of them.

        The unit that was touched answers on its own, immediately; everyone else
        is told when to start, at a time derived from how far away they stand.
        The gesture then crosses the room at :data:`TOUCH_SPEED_M_S` instead of
        appearing everywhere at once — which is the difference between a
        network artefact and something that looks like it is travelling.
        """
        self.touch_seq += 1
        origin = self.nodes.get(message.node_id)
        origin_position = origin.descriptor.position if origin is not None else None

        scheduled: dict[str, float] = {}
        commands: dict[str, RippleCommand] = {}
        for node_id, node in self.nodes.items():
            if node_id == message.node_id:
                continue  # the touched unit does not wait for the network
            position = node.descriptor.position
            if origin_position is None or position is None:
                delay = self.lead_ms
            else:
                travel = origin_position.distance_to(position) / self.touch_speed * 1000.0
                # Never sooner than the lead: a unit cannot ripple before it has
                # been told to, and fan-out is what sets that floor (§20).
                delay = max(self.lead_ms, travel)
            scheduled[node_id] = delay
            commands[node_id] = RippleCommand(
                origin_node=message.node_id,
                x=message.x,
                y=message.y,
                start_at=message.at + delay,
                amplitude=amplitude,
                strength=message.strength,
                seq=self.touch_seq,
            )

        pushes: list[PushResult] = []
        if self.fanout is not None:
            for node_id, command in commands.items():
                pushes.extend(self.fanout.push([node_id], command))

        result = TouchResult(message.node_id, self.touch_seq, scheduled, pushes)
        self.touch_history.append(result)
        return result

    def stop(self) -> PlayResult:  # noqa: D401
        self.seq += 1
        self.schedule = Schedule(state="idle", seq=self.seq, leader_epoch=self.leader_epoch)
        self.schedules = {}
        return PlayResult(
            self.schedule, self._push(self._targets(()), Stop(self.leader_epoch, self.seq))
        )

    def sync_all(self) -> list[PushResult]:
        return self._push(self._targets(()), Sync(self.leader_epoch))

    def promote_leader(self) -> int:
        """Leader change, option C (§11): cancel the active scene and bump the
        clock epoch. The new leader schedules a fresh start -- an intentional
        restart rather than an unexplained jump."""
        self.leader_epoch += 1
        self.seq += 1
        self.schedule = Schedule(state="idle", seq=self.seq, leader_epoch=self.leader_epoch)
        self.schedules = {}
        self._push(self._targets(()), Stop(self.leader_epoch, self.seq))
        return self.leader_epoch

    def prune(self, timeout_ms: float) -> tuple[str, ...]:
        now = self.clock.shared_now()
        gone = tuple(
            node_id for node_id, node in self.nodes.items() if now - node.last_seen > timeout_ms
        )
        for node_id in gone:
            del self.nodes[node_id]
        return gone

    def _targets(self, skipped: Iterable[str]) -> list[str]:
        excluded = set(skipped)
        return [node_id for node_id in self.nodes if node_id not in excluded]

    def _push(self, node_ids: list[str], message: Any) -> list[PushResult]:
        if self.fanout is None or not node_ids:
            return []
        return list(self.fanout.push(node_ids, message))
