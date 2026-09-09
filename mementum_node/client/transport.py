"""The node's side of the wire: `Transport`, over HTTP.

`ParticipantCore` asks its transport for things -- REGISTER, HEARTBEAT, a
manifest, an asset -- and does not know how they travel. In the simulator that
is an in-process queue; here it is `requests` against the control server, whose
routes are `mementum-led`'s. The core does not change, which is the whole point
of the seam (§3.2): only the clock, the transport and the sink are substituted.

One asymmetry is deliberate and is the reason a panel cannot be the server.
Everything a panel *fetches* is small except the scenes, and the scenes have to
live somewhere: `/scene/<id>`, `/manifest/<id>`, `/asset/<hash>`. A device with
two megabytes of RAM can draw a scene beautifully and cannot hold the library
that the wall is drawing from.
"""

from __future__ import annotations

from typing import Any

from mementum_node.core.protocol import (
    AssetReply, AssetRequest, Heartbeat, HeartbeatAck, ManifestReply, ManifestRequest,
    Ready, Register, RegisterAck, Schedule, TimeReply, TimeRequest, Touch,
)
from mementum_node.core.transport import TransportError

__all__ = ["HttpTransport", "schedule_from"]

DEFAULT_TIMEOUT = 3.0


def schedule_from(raw: dict | None) -> Schedule:
    """A schedule as it arrives. Missing fields are the idle schedule's, so a
    server that says less than it might still says something usable."""
    raw = raw or {}
    return Schedule(
        state=str(raw.get("state") or "idle"),
        scene_id=int(raw.get("scene_id") or 0),
        scene_hash=str(raw.get("scene_hash") or ""),
        seq=int(raw.get("seq") or 0),
        display_at=float(raw.get("display_at") or 0.0),
        duration=int(raw.get("duration") or 0),
        leader_epoch=int(raw.get("leader_epoch") or 0),
    )


class HttpTransport:
    """Implements `core.transport.Transport` against the control server."""

    def __init__(self, base_url: str, node_id: str = "", port: int = 0,
                 timeout: float = DEFAULT_TIMEOUT, session=None):
        self.base_url = base_url.rstrip("/")
        self.node_id = node_id
        self.port = port                      # where the server can push to us
        self.timeout = timeout
        self.session = session
        self.requests = 0
        self.failures = 0
        #: The id the server gave us. A panel does not name itself -- the LED
        #: firmware adopts the id in "Your ID: 1", and so does this.
        self.assigned_node_id = ""

    # -- the one method the core calls ----------------------------------

    def request(self, message: Any) -> Any:
        if isinstance(message, Register):
            return self._register(message)
        if isinstance(message, Heartbeat):
            return self._heartbeat(message)
        if isinstance(message, TimeRequest):
            body = self._get("/time")
            return TimeReply(server_now=float(body.strip()), leader_epoch=0)
        if isinstance(message, ManifestRequest):
            return self._manifest(message)
        if isinstance(message, AssetRequest):
            return self._asset(message)
        if isinstance(message, Ready):
            self._get("/ready", node=message.node_id, scene=message.scene_id,
                      hash=message.scene_hash)
            return None
        if isinstance(message, Touch):
            self._get("/touch", unit=message.node_id, x=message.x, y=message.y,
                      strength=message.strength)
            return None
        raise TransportError(f"cannot send {type(message).__name__} over HTTP")

    # -- each exchange ---------------------------------------------------

    def _register(self, message: Register) -> RegisterAck:
        descriptor = message.descriptor
        position = descriptor.position
        params = {
            "format": "json", "kind": descriptor.device,
            "version": "lcd/1", "node": descriptor.node_id,
            "width": descriptor.display.width, "height": descriptor.display.height,
            "port": self.port,
        }
        if position is not None:
            params.update({"x": position.x, "y": position.y})
        body = self._json("/register", **params)
        self.assigned_node_id = str(body.get("node_id") or "")
        return RegisterAck(
            accepted=bool(body.get("accepted", True)),
            server_now=float(body.get("server_now", 0.0)),
            leader_epoch=int(body.get("leader_epoch", 0)),
            schedule=schedule_from(body.get("schedule")),
            heartbeat_interval=int(body.get("heartbeat_interval", 5000)),
        )

    def _heartbeat(self, message: Heartbeat) -> HeartbeatAck:
        body = self._json("/heartbeat", format="json", port=self.port,
                          node=message.node_id, state=message.state,
                          seq=message.known_seq)
        return HeartbeatAck(
            server_now=float(body.get("server_now", 0.0)),
            leader_epoch=int(body.get("leader_epoch", 0)),
            schedule=schedule_from(body.get("schedule")),
            known=bool(body.get("known", True)),
        )

    def _manifest(self, message: ManifestRequest) -> ManifestReply:
        try:
            body = self._json(f"/manifest/{message.scene_id}")
        except TransportError:
            return ManifestReply(message.scene_id, "", 0, {}, (), 0, found=False)
        return ManifestReply(
            scene_id=int(body.get("scene_id", message.scene_id)),
            scene_hash=str(body.get("scene_hash", "")),
            ir_version=int(body.get("ir_version", 1)),
            requires=dict(body.get("requires") or {}),
            assets=tuple(body.get("assets") or ()),
            duration=int(body.get("duration", 0)),
            found=bool(body.get("found", True)),
        )

    def _asset(self, message: AssetRequest) -> AssetReply:
        try:
            payload = self._get(f"/asset/{message.asset_hash}", raw=True)
        except TransportError:
            return AssetReply(message.asset_hash, None, False)
        return AssetReply(message.asset_hash, payload, True)

    # -- plumbing --------------------------------------------------------

    def _session(self):
        if self.session is None:
            import requests

            self.session = requests.Session()
        return self.session

    def _get(self, route: str, raw: bool = False, **params):
        self.requests += 1
        try:
            response = self._session().get(self.base_url + route, params=params,
                                           timeout=self.timeout)
        except Exception as error:                      # a server that is not there
            self.failures += 1
            raise TransportError(str(error)) from error
        if getattr(response, "status_code", 0) != 200:
            self.failures += 1
            raise TransportError(f"{route} -> HTTP {getattr(response, 'status_code', '?')}")
        return response.content if raw else response.text

    def _json(self, route: str, **params) -> dict:
        self.requests += 1
        try:
            response = self._session().get(self.base_url + route, params=params,
                                           timeout=self.timeout)
        except Exception as error:
            self.failures += 1
            raise TransportError(str(error)) from error
        if getattr(response, "status_code", 0) != 200:
            self.failures += 1
            raise TransportError(f"{route} -> HTTP {getattr(response, 'status_code', '?')}")
        return response.json()
