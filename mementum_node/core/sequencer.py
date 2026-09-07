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
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .clock import Clock
from .library import SceneLibrary
from .protocol import (
    DISPLAY_LEAD_MS,
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

__all__ = ["INCAPABLE_POLICIES", "PlayResult", "RegisteredNode", "Sequencer", "derive_display_lead"]

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
class PlayResult:
    schedule: Schedule
    pushes: list[PushResult] = field(default_factory=list)
    skipped: tuple[str, ...] = ()
    refused: str = ""

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
        self.leader_epoch = 1
        self.seq = 0
        self.play_history: list[PlayResult] = []

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
            schedule=self.schedule,
            heartbeat_interval=self.heartbeat_interval,
        )

    def _heartbeat(self, message: Heartbeat, now: float) -> HeartbeatAck:
        node = self.nodes.get(message.node_id)
        if node is None:
            return HeartbeatAck(
                server_now=now, leader_epoch=self.leader_epoch, schedule=self.schedule, known=False
            )
        node.last_seen = now
        node.state = message.state
        node.known_seq = message.known_seq
        node.ready_scenes = message.ready_scenes
        return HeartbeatAck(
            server_now=now, leader_epoch=self.leader_epoch, schedule=self.schedule
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
        result = PlayResult(self.schedule, self._push(targets, Play(self.schedule)), skipped)
        self.play_history.append(result)
        return result

    def stop(self) -> PlayResult:
        self.seq += 1
        self.schedule = Schedule(state="idle", seq=self.seq, leader_epoch=self.leader_epoch)
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
