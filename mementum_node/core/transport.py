"""Transport contracts (proposal §20: the binding is replaceable).

The control plane is *semantics*; how a message travels is not. The core
therefore depends on these two protocols and never on HTTP, so the simulator's
in-process binding and a real unicast-HTTP binding are peers -- and multicast
(Phase 5b) can become a third without the core noticing.

Node to server is request/response: a node asks, the server answers. Server to
node is push, and it **must be concurrent** -- that is the one hard requirement
the ~300-node design bound places on the server (§20). A sequential fan-out is
a bug at this scale, not a slow implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Protocol

__all__ = ["Fanout", "PushResult", "Transport", "TransportError"]


class TransportError(Exception):
    """The message did not get through. Never fatal: the schedule is state, so
    the next heartbeat recovers whatever this dropped (§19)."""


class Transport(Protocol):
    """Node -> server. One round trip, or :class:`TransportError`."""

    def request(self, message: Any) -> Any: ...


@dataclass(frozen=True)
class PushResult:
    node_id: str
    delivered: bool
    elapsed_ms: float
    error: str = ""


class Fanout(Protocol):
    """Server -> nodes, concurrently. Returns per-node delivery timing, which
    is what ``DISPLAY_LEAD_MS`` is derived from rather than assumed."""

    def push(self, node_ids: Iterable[str], message: Any) -> list[PushResult]: ...
