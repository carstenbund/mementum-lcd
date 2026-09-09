"""The server's side of the wire, on the panel: a small HTTP listener.

The LED firmware serves routes and the server calls them; that is how a push
reaches a panel with no connection held open, and it is why registration
carries a port. This is the same, in the stdlib -- no Flask on a node, because
a node is the thing that is supposed to be small.

    /play?seq&at&scene&hash&url&duration    take this schedule
    /play?seq&at&data=<text>                the LED form, for a panel that can
                                            only be told a string
    /ripple?at&x&y&amplitude&strength       a wave through the ink, now
    /clear                                  idle
    /status                                 what this panel thinks is going on

Every route turns into a protocol message and is handed to `ParticipantCore`,
which is the same class the simulator drives. Nothing about being on a real
network gives a node a second code path.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from mementum_node.core.protocol import Play, RippleCommand, Schedule, Stop

__all__ = ["Listener"]


class Listener:
    """Runs a tiny HTTP server on its own thread and feeds the participant."""

    def __init__(self, participant, port: int = 0, host: str = "0.0.0.0", log=None):
        self.participant = participant
        self.log = log
        handler = _handler_for(self)
        self._server = ThreadingHTTPServer((host, port), handler)
        self._thread: threading.Thread | None = None
        self.received = 0

    @property
    def port(self) -> int:
        """The port actually bound -- 0 means "pick one", which is what a
        simulated wall of sixteen on one host needs."""
        return self._server.server_address[1]

    def start(self) -> "Listener":
        if self._thread is None:
            self._thread = threading.Thread(target=self._server.serve_forever,
                                            kwargs={"poll_interval": 0.1}, daemon=True)
            self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    # -- what each route means -------------------------------------------

    def handle(self, route: str, params: dict) -> tuple[int, dict]:
        def number(name, default=0.0):
            try:
                return float(params.get(name, [default])[0])
            except (TypeError, ValueError):
                return default

        def text(name, default=""):
            return params.get(name, [default])[0]

        if route == "/play":
            schedule = Schedule(
                state="playing",
                scene_id=int(number("scene")),
                scene_hash=text("hash"),
                seq=int(number("seq")),
                display_at=number("at"),
                duration=int(number("duration")),
                leader_epoch=int(number("epoch", self.participant.leader_epoch)),
            )
            if not schedule.scene_id and text("data"):
                # The LED form. A panel that draws cannot render a bare string
                # without a scene compiled from it, and compiling is the
                # composer's job -- so say so rather than show nothing.
                return 400, {"status": "error",
                             "message": "this panel takes scenes; ask the server to "
                                        "compile the words (/text)"}
            self.participant.receive(Play(schedule))
            self.received += 1
            return 200, {"status": "ok", "seq": schedule.seq}

        if route == "/ripple":
            self.participant.receive(RippleCommand(
                origin_node=text("from"), x=number("x", 0.5), y=number("y", 0.5),
                start_at=number("at"), amplitude=number("amplitude"),
                strength=number("strength", 1.0), seq=int(number("seq")),
            ))
            self.received += 1
            return 200, {"status": "ok"}

        if route == "/clear":
            self.participant.receive(Stop(leader_epoch=self.participant.leader_epoch,
                                          seq=int(number("seq"))))
            self.received += 1
            return 200, {"status": "ok"}

        if route == "/status":
            status = self.participant.status()
            return 200, {
                "node_id": status.node_id, "state": status.state,
                "scene_id": status.scene_id, "seq": status.seq,
                "scene_time": status.scene_time, "frames": status.frames_presented,
                "clock_offset": status.clock_offset,
            }

        if route in ("/", "/ping"):
            return 200, {"status": "ok", "node": self.participant.node_id}

        return 404, {"status": "error", "message": f"no route {route}"}


def _handler_for(listener: Listener):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):                                   # noqa: N802 - stdlib name
            parsed = urlparse(self.path)
            try:
                code, body = listener.handle(parsed.path, parse_qs(parsed.query))
            except Exception as error:                      # a bad push is not a crash
                code, body = 500, {"status": "error", "message": str(error)}
                if listener.log is not None:
                    listener.log.emit(f"push failed: {error}", level="error")
            payload = json.dumps(body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):                       # noqa: N802 - stdlib name
            pass                                            # the node has its own log

    return Handler
