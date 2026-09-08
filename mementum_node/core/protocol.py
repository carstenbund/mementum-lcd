"""The control plane and the asset plane (proposal §18, §19; plan 4.1-4.3).

Two planes, deliberately separate: tiny pushed commands, and pulled packages.

    control:  REGISTER  PLAY  STOP  SYNC  STATUS  HEARTBEAT
    assets:   GET /scene/<id>/manifest      GET /asset/<hash>

The property everything else rests on is that **the schedule is state, not an
event** (§19). ``PLAY`` is a push, but the same :class:`Schedule` is returned
from every REGISTER and every HEARTBEAT, so a lost command degrades from a
correctness problem to a latency one -- and late join, missed command and
dropped frame all collapse into the same recovery.

These are transport-neutral message objects. Over the wire they are HTTP+JSON;
in the simulator they are passed by reference. The binding is replaceable; the
semantics here are not (§20).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

__all__ = [
    "AssetReply",
    "Position",
    "RippleCommand",
    "Touch",
    "AssetRequest",
    "Capabilities",
    "DISPLAY_LEAD_MS",
    "Display",
    "HEARTBEAT_INTERVAL_MS",
    "Heartbeat",
    "HeartbeatAck",
    "ManifestReply",
    "ManifestRequest",
    "NodeDescriptor",
    "Play",
    "Ready",
    "Register",
    "RegisterAck",
    "Schedule",
    "Status",
    "StatusReply",
    "Stop",
    "Sync",
    "TimeReply",
    "TimeRequest",
]

#: Inherited from ``mementum-led``. §20 is explicit that this must be *derived*
#: from measured concurrent fan-out to the last node, not assumed -- which is
#: what ``sim/scenarios/fanout_scale.py`` is for.
DISPLAY_LEAD_MS = 2000

#: Sets worst-case recovery latency for a missed command (§19), so it should be
#: short relative to scene duration.
HEARTBEAT_INTERVAL_MS = 1000


# -- registration ---------------------------------------------------------


@dataclass(frozen=True)
class Display:
    width: int
    height: int
    pixel_format: str = "rgb565"

    def __str__(self) -> str:
        return f"{self.width}x{self.height} {self.pixel_format}"


@dataclass(frozen=True)
class Capabilities:
    scene_ir: int = 1
    vector: bool = True
    text: bool = True
    lottie: bool = False

    def satisfies(self, required: dict[str, Any]) -> tuple[bool, str]:
        """Capability gate. ``scene_ir`` is a version gate, the rest features."""
        need_ir = int(required.get("scene_ir", 1))
        if self.scene_ir < need_ir:
            return False, f"scene_ir {need_ir} > {self.scene_ir}"
        for feature in ("vector", "text", "lottie"):
            if required.get(feature) and not getattr(self, feature):
                return False, f"missing capability: {feature}"
        return True, ""


@dataclass(frozen=True)
class Position:
    """Where a unit stands in the installation, in metres.

    Only needed for touch propagation: it is what lets a gesture cross the room
    at a chosen speed rather than appearing everywhere at once. A node without
    one still plays scenes; it simply has no neighbours.
    """

    x: float = 0.0
    y: float = 0.0

    def distance_to(self, other: "Position") -> float:
        return ((self.x - other.x) ** 2 + (self.y - other.y) ** 2) ** 0.5


@dataclass(frozen=True)
class NodeDescriptor:
    node_id: str
    device: str
    roles: tuple[str, ...]
    display: Display
    capabilities: Capabilities = Capabilities()
    position: Position | None = None


# -- the schedule, as state ----------------------------------------------


@dataclass(frozen=True)
class Schedule:
    """The current schedule. Returned on register and on every heartbeat."""

    state: str = "idle"  # "idle" | "playing"
    scene_id: int = 0
    scene_hash: str = ""
    seq: int = 0
    display_at: float = 0.0
    duration: int = 0
    leader_epoch: int = 0

    @property
    def playing(self) -> bool:
        return self.state == "playing"

    def cancelled(self, leader_epoch: int) -> "Schedule":
        return replace(self, state="idle", scene_id=0, scene_hash="", leader_epoch=leader_epoch)


IDLE = Schedule()


# -- control plane --------------------------------------------------------


@dataclass(frozen=True)
class Register:
    descriptor: NodeDescriptor


@dataclass(frozen=True)
class RegisterAck:
    accepted: bool
    server_now: float
    leader_epoch: int
    schedule: Schedule = IDLE
    heartbeat_interval: int = HEARTBEAT_INTERVAL_MS
    reason: str = ""


@dataclass(frozen=True)
class Heartbeat:
    node_id: str
    state: str = "idle"
    known_seq: int = 0
    ready_scenes: tuple[int, ...] = ()


@dataclass(frozen=True)
class HeartbeatAck:
    server_now: float
    leader_epoch: int
    schedule: Schedule = IDLE
    known: bool = True


@dataclass(frozen=True)
class Play:
    schedule: Schedule


@dataclass(frozen=True)
class Stop:
    leader_epoch: int
    seq: int = 0


@dataclass(frozen=True)
class Sync:
    leader_epoch: int


@dataclass(frozen=True)
class Status:
    node_id: str = ""


@dataclass(frozen=True)
class StatusReply:
    node_id: str
    state: str
    scene_id: int
    seq: int
    scene_time: float | None
    frame_hash: str | None
    frames_presented: int
    clock_offset: float


@dataclass(frozen=True)
class Ready:
    node_id: str
    scene_id: int
    scene_hash: str


@dataclass(frozen=True)
class Touch:
    """Somebody touched a unit. Node to sequencer, over the same unicast
    binding as everything else."""

    node_id: str
    x: float
    y: float
    at: float
    strength: float = 1.0


@dataclass(frozen=True)
class RippleCommand:
    """Sequencer to node: start this ripple at this shared time.

    Transient, so unlike the schedule it is not state: a node that misses the
    push does not ripple, and nothing needs to recover. A ripple is over long
    before the next heartbeat."""

    origin_node: str
    x: float
    y: float
    start_at: float
    amplitude: float
    strength: float = 1.0
    seq: int = 0


@dataclass(frozen=True)
class TimeRequest:
    node_id: str = ""


@dataclass(frozen=True)
class TimeReply:
    server_now: float
    leader_epoch: int


# -- asset plane ----------------------------------------------------------


@dataclass(frozen=True)
class ManifestRequest:
    scene_id: int


@dataclass(frozen=True)
class ManifestReply:
    scene_id: int
    scene_hash: str
    ir_version: int
    requires: dict[str, Any] = field(default_factory=dict)
    assets: tuple[str, ...] = ()
    duration: int = 0
    found: bool = True


@dataclass(frozen=True)
class AssetRequest:
    asset_hash: str


@dataclass(frozen=True)
class AssetReply:
    asset_hash: str
    payload: bytes | None
    found: bool = True
