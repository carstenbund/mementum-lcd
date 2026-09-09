"""Server to panels, concurrently -- and to two kinds of panel at once.

This is `Fanout` (core/transport.py) over HTTP, so the sequencer does not
change: it pushes `Play` and `RippleCommand` as it always has, and what those
become on the wire is decided here.

The wire form is `mementum-led`'s, because a panel that already speaks it
should not have to learn a new one:

    /play?seq=<n>&at=<sharedMs>&data=<text>          an LED matrix scrolls it
    /play?seq=<n>&at=<sharedMs>&scene=<id>&hash=<digest>&url=/scene/<id>
                                                    an LCD panel draws it

**Both can be on one wall.** A cue made of words reaches either kind: the LED
scrolls the string, the LCD draws the scene compiled from the same words -- and
because a compiled writing scene keeps its `text`, a scene cue can still be
sent to an LED panel in the form it understands. A cue whose scene has no words
(a symbol, a deformation) cannot cross, and that is said out loud rather than
dropped quietly.

Concurrency is the one hard requirement §20 places on the server: sequential
fan-out to a few hundred panels is seconds, which is already past
`DISPLAY_LEAD_MS`.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Iterable

from mementum_node.core.protocol import Play, RippleCommand, Stop, Sync
from mementum_node.core.transport import PushResult

__all__ = ["HttpFanout", "BROADCAST_TIMEOUT", "FANOUT_WORKERS"]

#: Seconds per request. The LED firmware uses 2000 ms; a panel that cannot
#: answer in that time has bigger problems than this frame.
BROADCAST_TIMEOUT = 2.0

#: Concurrent workers. Enough that a few hundred panels are one round trip.
FANOUT_WORKERS = 32


class HttpFanout:
    """Pushes to panels over HTTP. Implements `core.transport.Fanout`."""

    def __init__(self, registry, library, log=None, timeout: float = BROADCAST_TIMEOUT,
                 workers: int = FANOUT_WORKERS, session=None):
        self.registry = registry
        self.library = library
        self.log = log
        self.timeout = timeout
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="fanout")
        self.session = session          # injected in tests; requests.Session in the field
        self.sent: list[tuple[str, dict]] = []          # last requests, for the operator page

    # -- Fanout ---------------------------------------------------------

    def push(self, node_ids: Iterable[str], message: Any) -> list[PushResult]:
        clients = self.registry.by_node_id()
        targets = [clients[node_id] for node_id in node_ids if node_id in clients]
        if not targets:
            return []

        requests_out: list[tuple[Any, str, dict]] = []
        results: list[PushResult] = []
        for client in targets:
            route, params, refusal = self._request_for(client, message)
            if refusal is not None:
                results.append(PushResult(client.node_id, False, 0.0, refusal))
                if self.log is not None:
                    self.log.emit(f"  skip ID={client.id} ({client.kind}): {refusal}",
                                  level="debug")
                continue
            requests_out.append((client, route, params))

        futures = {
            self.pool.submit(self._get, client, route, params): client
            for client, route, params in requests_out
        }
        for future, client in futures.items():
            results.append(future.result())

        if self.log is not None and requests_out:
            route = requests_out[0][1]
            ok = sum(1 for r in results if r.delivered)
            self.log.emit(f"BROADCAST {route} -> {ok}/{len(requests_out)} clients OK")
        return results

    # -- what each kind of panel is told ---------------------------------

    def _request_for(self, client, message) -> tuple[str, dict, str | None]:
        if isinstance(message, Play):
            schedule = message.schedule
            params = {"seq": schedule.seq, "at": int(schedule.display_at)}
            if client.kind == "led":
                text = self._text_of(schedule.scene_id)
                if not text:
                    return "", {}, f"scene {schedule.scene_id} has no text form"
                params["data"] = text
                return "/play", params, None
            params.update({
                "scene": schedule.scene_id,
                "hash": schedule.scene_hash,
                "url": f"/scene/{schedule.scene_id}",
                "duration": schedule.duration,
            })
            return "/play", params, None

        if isinstance(message, RippleCommand):
            if client.kind != "lcd":
                return "", {}, "an LED matrix has no ink to ripple"
            return "/ripple", {
                "seq": message.seq, "at": int(message.start_at),
                "x": message.x, "y": message.y,
                "amplitude": message.amplitude, "strength": message.strength,
            }, None

        if isinstance(message, Stop):
            return "/clear", {"seq": message.seq}, None
        if isinstance(message, Sync):
            return "/time", {}, None
        return "", {}, f"nothing to send for {type(message).__name__}"

    def _text_of(self, scene_id: int) -> str:
        """The words a scene was made from, if it was made from words.

        This is what lets one cue reach both kinds of panel: `tools/handwriting`
        keeps `text` in the scene it compiles, so the same line exists as pen
        strokes for an LCD and as a string for an LED matrix.
        """
        package = self.library.get(scene_id)
        if package is None:
            return ""
        try:
            return str(json.loads(package.payload).get("text") or "")
        except (ValueError, AttributeError):
            return ""

    # -- one request ----------------------------------------------------

    def _get(self, client, route: str, params: dict) -> PushResult:
        import time as _time

        started = _time.monotonic()
        url = client.base_url + route
        self.sent.append((client.node_id, {"url": route, **params}))
        del self.sent[:-64]
        try:
            session = self.session
            if session is None:
                import requests

                session = requests
            response = session.get(url, params=params, timeout=self.timeout)
            elapsed = (_time.monotonic() - started) * 1000.0
            ok = getattr(response, "status_code", 0) == 200
            return PushResult(client.node_id, ok, elapsed,
                              "" if ok else f"HTTP {getattr(response, 'status_code', '?')}")
        except Exception as error:                      # a panel that is not there
            elapsed = (_time.monotonic() - started) * 1000.0
            return PushResult(client.node_id, False, elapsed, str(error))
