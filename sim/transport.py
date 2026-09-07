"""Substitution 2 of 3: the transport (plan §3.1).

Real: unicast HTTP. Simulated: in-process calls with a delivery model. The
control plane is semantics and the binding is replaceable (§20), so the core
neither knows nor cares which one it is talking to -- and the failure modes that
are awkward to induce over real Wi-Fi become scripted here:

* **loss** -- a pushed command that never arrives, so recovery must come from
  the heartbeat instead;
* **latency and jitter** -- one-way delay, and the asymmetry that is exactly
  what Cristian's algorithm cannot see;
* **unreachable nodes** -- a node that holds a worker for its full timeout,
  which is §20's specific worry about sequential fan-out;
* **concurrency** -- fan-out must be concurrent, and this is where the shape of
  the fan-out curve at 10 / 100 / 300 nodes comes from.

What this cannot answer: real soft-AP contention, real timeout distributions,
real multicast basic rates (§3.4). The model is calibrated *from* hardware
measurements, never used in place of them (risk R9).
"""

from __future__ import annotations

import heapq
import random
from dataclasses import dataclass
from typing import Any, Iterable

from mementum_node.core.protocol import TimeRequest
from mementum_node.core.transport import PushResult, TransportError

from .clock import NodeTimeSource, SimulationClock

__all__ = ["DeliveryModel", "InProcessTransport", "NodeTransport"]


@dataclass
class DeliveryModel:
    """Parameters of the simulated network. Every one of these is a hypothesis
    about hardware until hardware says otherwise."""

    latency_ms: float = 8.0          # one-way, node <-> server
    latency_jitter_ms: float = 3.0
    asymmetry_ms: float = 0.0        # request/response imbalance; Cristian's blind spot
    loss: float = 0.0                # probability a pushed command is dropped
    push_cost_ms: float = 6.0        # server-side cost of one unicast push
    fanout_concurrency: int = 32     # concurrent workers; sequential would be 1
    timeout_ms: float = 2000.0       # what an unreachable node costs a worker


class NodeTransport:
    """The node side. Implements ``core.transport.Transport``."""

    def __init__(self, bus: "InProcessTransport", node_id: str, source: NodeTimeSource):
        self._bus = bus
        self._node_id = node_id
        self._source = source

    def request(self, message: Any) -> Any:
        return self._bus.request(self._node_id, self._source, message)

    def time_query(self) -> tuple[float, int]:
        """The ``GET /time`` round trip Cristian's algorithm runs on."""
        reply = self.request(TimeRequest(self._node_id))
        return reply.server_now, reply.leader_epoch


class InProcessTransport:
    """The bus: node requests, and concurrent server-to-node fan-out."""

    def __init__(
        self,
        master: SimulationClock,
        model: DeliveryModel | None = None,
        seed: int = 0,
    ):
        self.master = master
        self.model = model if model is not None else DeliveryModel()
        self.sequencer = None  # set by the harness once the sequencer exists
        self._nodes: dict[str, Any] = {}
        self._rng = random.Random(seed)
        self._queue: list[tuple[float, int, str, Any]] = []
        self._counter = 0

        self.unreachable: set[str] = set()
        self.drop_pushes: dict[str, int] = {}
        self.requests = 0
        self.pushes_sent = 0
        self.pushes_dropped = 0
        self.pushes_delivered = 0

    # -- wiring ---------------------------------------------------------

    def client(self, node_id: str, source: NodeTimeSource) -> NodeTransport:
        return NodeTransport(self, node_id, source)

    def attach(self, node_id: str, node: Any) -> None:
        self._nodes[node_id] = node

    # -- scripted failure ------------------------------------------------

    def drop_next_push(self, node_id: str, count: int = 1) -> None:
        """Make the next ``count`` pushed commands to this node vanish. The
        node must then recover on its own, from the schedule state."""
        self.drop_pushes[node_id] = self.drop_pushes.get(node_id, 0) + count

    def set_unreachable(self, node_id: str, unreachable: bool = True) -> None:
        if unreachable:
            self.unreachable.add(node_id)
        else:
            self.unreachable.discard(node_id)

    # -- node -> server --------------------------------------------------

    def _round_trip_ms(self) -> float:
        jitter = self.model.latency_jitter_ms
        noise = (self._rng.random() * 2.0 - 1.0) * jitter if jitter else 0.0
        return max(0.1, 2.0 * self.model.latency_ms + noise)

    def request(self, node_id: str, source: NodeTimeSource, message: Any) -> Any:
        """One round trip.

        Requests from different nodes overlap in reality, so a request costs no
        *global* virtual time here: it costs the requesting node a stall of one
        round trip, and the server timestamps the message at the instant it
        arrives, expressed in that node's stalled frame. Cristian's algorithm
        then measures a real RTT, halves it, and lands with a residual error
        equal to the modelled asymmetry -- which is exactly what it does in
        life, and exactly what it cannot correct for.

        The limitation this trades for: server-side queuing under simultaneous
        requests is not modelled, only fan-out is (see :meth:`push`). Request
        concurrency on a real Pi is a hardware measurement (§3.4).
        """
        if self.sequencer is None:  # pragma: no cover - harness wires this
            raise RuntimeError("transport has no sequencer attached")
        if node_id in self.unreachable:
            # A dead peer costs *this* node its timeout and nobody else theirs.
            source.stall_ms += self.model.timeout_ms
            raise TransportError(f"{node_id} unreachable")

        self.requests += 1
        rtt = self._round_trip_ms()
        entry = source.stall_ms
        # The node blocks for the whole round trip ...
        source.stall_ms = entry + rtt
        # ... and the server answers when the request arrives: half the round
        # trip later, plus whatever asymmetry the model injects.
        arrival = self.master.now + entry + rtt / 2.0 + self.model.asymmetry_ms
        held, self.master.now = self.master.now, arrival
        try:
            return self.sequencer.handle(message)
        finally:
            self.master.now = held

    # -- server -> nodes (concurrent fan-out) ----------------------------

    def push(self, node_ids: Iterable[str], message: Any) -> list[PushResult]:
        """Concurrent fan-out. Returns per-node delivery timing.

        Workers are taken in order; each push costs the server ``push_cost_ms``
        and an unreachable node costs a worker its whole timeout. With
        ``fanout_concurrency = 1`` this degenerates into exactly the sequential
        fan-out §20 says breaks well before the design bound -- which makes the
        comparison a measurement rather than an argument.
        """
        results: list[PushResult] = []
        workers = [0.0] * max(1, self.model.fanout_concurrency)
        now = self.master.now
        for node_id in node_ids:
            self.pushes_sent += 1
            slot = min(range(len(workers)), key=lambda i: workers[i])
            start = workers[slot]
            if node_id in self.unreachable:
                workers[slot] = start + self.model.timeout_ms
                results.append(
                    PushResult(node_id, False, workers[slot], "timeout")
                )
                self.pushes_dropped += 1
                continue

            transit = self.model.latency_ms + (
                (self._rng.random() * 2.0 - 1.0) * self.model.latency_jitter_ms
                if self.model.latency_jitter_ms
                else 0.0
            )
            workers[slot] = start + self.model.push_cost_ms
            arrival = now + start + self.model.push_cost_ms + max(0.0, transit)

            forced = self.drop_pushes.get(node_id, 0)
            lost = forced > 0 or (self.model.loss and self._rng.random() < self.model.loss)
            if forced > 0:
                self.drop_pushes[node_id] = forced - 1
            if lost:
                self.pushes_dropped += 1
                results.append(PushResult(node_id, False, arrival - now, "lost"))
                continue

            self._counter += 1
            heapq.heappush(self._queue, (arrival, self._counter, node_id, message))
            results.append(PushResult(node_id, True, arrival - now, ""))
        return results

    def deliver_due(self) -> int:
        """Hand over every push whose arrival time has come. Called by the
        harness as virtual time advances."""
        delivered = 0
        while self._queue and self._queue[0][0] <= self.master.now:
            _, _, node_id, message = heapq.heappop(self._queue)
            node = self._nodes.get(node_id)
            if node is None:
                continue
            node.receive(message)
            delivered += 1
            self.pushes_delivered += 1
        return delivered

    @property
    def pending(self) -> int:
        return len(self._queue)
