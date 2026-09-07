"""The harness: one sequencer, N nodes, one process, time under our control.

Scenarios are written against this. It advances virtual time in fixed steps,
delivers whatever the transport says has arrived, runs each node's heartbeat
when due and gives each node's pacer the chance to present a frame. Nothing
here is real-time: a four-second scene runs in well under four seconds and
produces the same result on every machine, which is what makes these tests
belong in CI (§3.3).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from mementum_node.core.clock import FixedClock
from mementum_node.core.library import SceneLibrary
from mementum_node.core.protocol import (
    DISPLAY_LEAD_MS,
    HEARTBEAT_INTERVAL_MS,
    Capabilities,
    Display,
)
from mementum_node.core.sequencer import PlayResult, Sequencer

from .clock import SimulationClock
from .node import SimNode
from .transport import DeliveryModel, InProcessTransport

__all__ = ["DEFAULT_SCENE", "Harness"]

DEFAULT_SCENE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "poc",
    "scenes",
    "poc-signature.json",
)


@dataclass
class TickStats:
    steps: int = 0
    frames: int = 0
    deliveries: int = 0
    heartbeats: int = 0


class Harness:
    def __init__(
        self,
        scene_path: str = DEFAULT_SCENE,
        model: DeliveryModel | None = None,
        lead_ms: float = DISPLAY_LEAD_MS,
        heartbeat_ms: int = HEARTBEAT_INTERVAL_MS,
        fps: float = 30.0,
        seed: int = 1,
        step_ms: float = 2.0,
        incapable_policy: str = "schedule",
    ):
        self.master = SimulationClock()
        self.bus = InProcessTransport(self.master, model, seed=seed)
        self.library = SceneLibrary()
        self.sequencer = Sequencer(
            clock=FixedClock(self.master),
            library=self.library,
            fanout=self.bus,
            lead_ms=lead_ms,
            heartbeat_interval=heartbeat_ms,
            incapable_policy=incapable_policy,
        )
        self.bus.sequencer = self.sequencer

        self.nodes: list[SimNode] = []
        self.fps = fps
        self.step_ms = step_ms
        self.heartbeat_ms = heartbeat_ms
        self.seed = seed
        self.stats = TickStats()
        self.scene_path = scene_path
        if scene_path:
            self.add_scene(scene_path)

    # -- setup ----------------------------------------------------------

    def add_scene(self, path: str, scene_id: int | None = None):
        return self.library.add_file(path, scene_id)

    def add_node(self, node_id: str | None = None, register: bool = True, **kwargs) -> SimNode:
        node_id = node_id if node_id is not None else f"node-{len(self.nodes):03d}"
        kwargs.setdefault("fps", self.fps)
        kwargs.setdefault("seed", self.seed * 1000 + len(self.nodes))
        node = SimNode(node_id, self.master, self.bus, **kwargs)
        self.nodes.append(node)
        if register:
            node.register()
            # Stagger heartbeats deterministically: a few hundred nodes all
            # heartbeating on the same millisecond is an artefact of the
            # simulator, not a property of the system.
            phase = (len(self.nodes) - 1) * self.heartbeat_ms / max(1, len(self.nodes) or 1)
            node.next_heartbeat_at = self.master.now + self.heartbeat_ms + phase % self.heartbeat_ms
        return node

    def add_nodes(self, count: int, prefix: str = "node", **kwargs) -> list[SimNode]:
        base = len(self.nodes)
        made = [self.add_node(f"{prefix}-{base + i:03d}", **kwargs) for i in range(count)]
        # Re-phase heartbeats across the whole population once it is known.
        registered = [n for n in self.nodes if n.next_heartbeat_at is not None]
        for i, node in enumerate(registered):
            node.next_heartbeat_at = self.master.now + self.heartbeat_ms * (
                (i + 1) / max(1, len(registered))
            )
        return made

    def node(self, node_id: str) -> SimNode:
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        raise KeyError(node_id)

    # -- driving --------------------------------------------------------

    def play(self, scene_id: int = 42, at: float | None = None) -> PlayResult:
        return self.sequencer.play(scene_id, at)

    def stop(self) -> PlayResult:
        return self.sequencer.stop()

    def promote_leader(self) -> int:
        return self.sequencer.promote_leader()

    def advance(self, ms: float, step_ms: float | None = None) -> TickStats:
        """Advance virtual time, delivering, heartbeating and rendering as it
        passes. Requests advance the clock too, so the loop is written against
        an absolute deadline rather than a step count.

        ``step_ms`` coarsens the step for stretches where nothing is being
        rendered -- a half-hour drift soak does not need 2 ms resolution."""
        step = self.step_ms if step_ms is None else step_ms
        deadline = self.master.now + ms
        while self.master.now < deadline:
            self.master.advance(min(step, deadline - self.master.now))
            self.stats.steps += 1
            self.stats.deliveries += self.bus.deliver_due()
            now = self.master.now
            for node in self.nodes:
                due = node.next_heartbeat_at
                if due is not None and now >= due:
                    node.heartbeat()
                    node.next_heartbeat_at = max(now, due) + self.heartbeat_ms
                    self.stats.heartbeats += 1
                if node.tick():
                    self.stats.frames += 1
        return self.stats

    def advance_to_scene_time(self, scene_time: float, node: SimNode | None = None) -> float:
        """Advance until a node's scene time reaches ``scene_time``."""
        reference = node if node is not None else self.nodes[0]
        guard = 0
        while True:
            current = reference.scene_time
            if current is not None and current >= scene_time:
                return current
            guard += 1
            if guard > 100000:  # pragma: no cover - scenario bug guard
                raise RuntimeError("scene time never reached; is anything playing?")
            self.advance(self.step_ms)

    def set_heartbeats(self, enabled: bool, nodes=None) -> None:
        """Turn periodic heartbeats on or off. Off is how a drift soak without
        re-sync is scripted -- and turning them back on is how the recovery
        from it is measured rather than asserted."""
        for node in nodes if nodes is not None else self.nodes:
            node.next_heartbeat_at = (self.master.now + self.heartbeat_ms) if enabled else None

    # -- reporting ------------------------------------------------------

    def summary(self) -> dict:
        return {
            "virtual_ms": round(self.master.now, 3),
            "nodes": len(self.nodes),
            "playing": sum(1 for n in self.nodes if n.state == "playing"),
            "frames": sum(n.core.frames_presented for n in self.nodes),
            "requests": self.bus.requests,
            "pushes_sent": self.bus.pushes_sent,
            "pushes_dropped": self.bus.pushes_dropped,
            "heartbeat_recoveries": sum(n.core.recovered_by_heartbeat for n in self.nodes),
            "pulls": sum(n.core.pulls for n in self.nodes),
        }

    def dump(self) -> str:
        return json.dumps(self.summary(), indent=2, sort_keys=True)
