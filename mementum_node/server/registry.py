"""Who is on the wall -- and what kind of panel it is.

Ported from `mementum-led`'s client table, with its hard-won rules kept:

* a client is identified by where the server can **reach** it -- source address
  and the port it listens on -- not by an index it reports. The LED server keys
  on IP alone, which is the same thing when every panel is its own device on
  port 80; carrying the port too is what lets a simulated wall of sixteen run
  on one host without sixteen addresses;
* ids are monotonic and never reused, so a panel that disappears and returns is
  visibly the same one and a stale id can never point at a new panel;
* a client that stops heartbeating is marked **inactive** rather than deleted,
  so the operator can still see when it was last heard from, and is purged only
  much later.

What is new here is `kind`. An LED panel scrolls a string; an LCD panel draws a
scene. Both register the same way, and the difference is a capability, which is
where this project already puts such things (§18): the sequencer refuses to
schedule a scene on a unit that cannot draw one, before the show rather than at
`displayAt`.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from mementum_node.core.protocol import Capabilities, Display, NodeDescriptor, Position

__all__ = ["Client", "Registry", "HEARTBEAT_TIMEOUT", "PURGE_INACTIVE"]

#: Seconds without a heartbeat before a client is considered gone, and before
#: its record is dropped entirely. Both are the LED server's.
HEARTBEAT_TIMEOUT = 80.0
PURGE_INACTIVE = 600.0

#: What each kind of panel can do. An LED matrix has no vector renderer and no
#: scene IR; it takes a string and scrolls it.
CAPABILITIES = {
    "lcd": Capabilities(scene_ir=1, vector=True, text=True, lottie=False),
    "led": Capabilities(scene_ir=0, vector=False, text=True, lottie=False),
}


@dataclass
class Client:
    id: int
    ip: str
    kind: str = "lcd"                 # "lcd" | "led"
    version: str = "?"
    first_seen: float = 0.0
    last_seen: float = 0.0
    active: bool = True
    descriptor: NodeDescriptor | None = None
    port: int = 80

    @property
    def node_id(self) -> str:
        """What the sequencer calls it. Stable for the life of the id."""
        return f"unit-{self.id}"

    @property
    def base_url(self) -> str:
        return f"http://{self.ip}" + ("" if self.port == 80 else f":{self.port}")

    def as_row(self, now: float) -> dict:
        return {
            "id": self.id, "ip": self.ip, "kind": self.kind, "version": self.version,
            "node_id": self.node_id, "first_seen": self.first_seen,
            "last_seen": self.last_seen, "active": self.active,
            "age": round(now - self.last_seen, 1),
        }


class Registry:
    def __init__(self, log=None):
        self.log = log
        self.clients: dict[str, Client] = {}          # by "ip:port"
        self._next_id = 1
        self._lock = threading.RLock()

    # -- registration ---------------------------------------------------

    def register(self, ip: str, kind: str = "lcd", version: str = "?",
                 width: int = 0, height: int = 0, port: int = 80,
                 x: float | None = None, y: float | None = None) -> tuple[Client, bool]:
        """Returns the client and whether it is new. Never raises on a repeat:
        re-registration is the ordinary way a panel comes back."""
        now = time.time()
        key = f"{ip}:{port}"
        with self._lock:
            client = self.clients.get(key)
            new = client is None
            if new:
                client = Client(id=self._next_id, ip=ip, first_seen=now)
                self._next_id += 1
                self.clients[key] = client
            client.kind = kind if kind in CAPABILITIES else "lcd"
            client.version = version
            client.port = port
            client.last_seen = now
            client.active = True
            position = Position(x, y) if x is not None and y is not None else None
            client.descriptor = NodeDescriptor(
                node_id=client.node_id,
                device=client.kind,
                roles=("display",),
                display=Display(width or 0, height or 0,
                                "rgb565" if client.kind == "lcd" else "rgb888"),
                capabilities=CAPABILITIES[client.kind],
                position=position or (client.descriptor.position if client.descriptor else None),
            )
            return client, new

    def heartbeat(self, ip: str, port: int = 80) -> Client | None:
        with self._lock:
            client = self.clients.get(f"{ip}:{port}")
            if client is None:
                # A panel heartbeating from a port it did not register on is
                # still that panel: fall back to the address alone.
                client = next((c for c in self.clients.values() if c.ip == ip), None)
            if client is None:
                return None
            client.last_seen = time.time()
            reappeared = not client.active
            client.active = True
            if reappeared and self.log is not None:
                self.log.emit(f"RECONNECT ID={client.id} IP={ip} (heartbeat after going stale)")
            return client

    # -- queries --------------------------------------------------------

    def active(self) -> list[Client]:
        with self._lock:
            return sorted((c for c in self.clients.values() if c.active), key=lambda c: c.id)

    def by_node_id(self) -> dict[str, Client]:
        return {client.node_id: client for client in self.active()}

    def rows(self) -> list[dict]:
        now = time.time()
        with self._lock:
            return sorted((c.as_row(now) for c in self.clients.values()), key=lambda r: r["id"])

    # -- the cleanup the LED server learned to do ------------------------

    def sweep(self) -> tuple[list[Client], list[Client]]:
        """Mark the silent inactive, drop the long gone. Returns both lists so
        the caller can log them outside the lock."""
        now = time.time()
        disappeared, purged = [], []
        with self._lock:
            for key, client in list(self.clients.items()):
                idle = now - client.last_seen
                if client.active and idle > HEARTBEAT_TIMEOUT:
                    client.active = False
                    disappeared.append(client)
                elif not client.active and idle > PURGE_INACTIVE:
                    purged.append(client)
                    del self.clients[key]
        return disappeared, purged
