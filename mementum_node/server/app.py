"""The control server: a port of `mementum-led`'s, for panels that draw.

That server is a faithful port of the ESP32's own AP-mode server, so a panel
can be pointed at either. This one keeps the same route table for the same
reason, and adds only what an LCD panel needs that an LED matrix does not: a
scene to fetch, and a show to run.

    node plane      /register  /heartbeat  /time  /ready
                    /scene/<id>  /manifest/<id>  /asset/<hash>
    show plane      /guide  /start  /seek  /stop  /show  /text  /effect
    operator        /  /clients  /logstream  /identify  /clear

The sequencer underneath is the one the simulator drives: this module owns no
show logic at all, only the bindings. What is pushed to a panel is decided in
`broadcast.py`, and *that* is where one wall can hold both kinds of panel --
an LED matrix scrolling the string a cue was written from while an LCD beside
it draws the same words as pen strokes.

    python -m mementum_node.server --show poc/shows/opening.json --port 8080
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

from flask import Flask, Response, jsonify, request, send_from_directory

from mementum_node.core.clock import FixedClock, SystemTimeSource
from mementum_node.core.guide import Guide, format_timecode, parse_timecode
from mementum_node.core.library import SceneLibrary
from mementum_node.core.protocol import Heartbeat, Ready, Register, Schedule, Touch
from mementum_node.core.sequencer import Sequencer, derive_display_lead
from mementum_node.server.broadcast import HttpFanout
from mementum_node.server.log import ServerLog
from mementum_node.server.registry import HEARTBEAT_TIMEOUT, Registry

__all__ = ["build", "ControlServer"]

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

#: How often the show is asked what is due. The window is half-open and the
#: horizon is a whole display lead, so this is a comfort rather than a
#: requirement -- a tick that arrives late fires what it missed.
TICK_INTERVAL = 0.05
CLEANUP_INTERVAL = 30.0
IDENTIFY_LEAD_MS = 500.0


class ControlServer:
    """Everything the routes talk to, in one place that is easy to test."""

    def __init__(self, lead_ms: float | None = None, log: ServerLog | None = None,
                 session=None):
        self.log = log or ServerLog()
        self.clock = FixedClock(SystemTimeSource())
        self.library = SceneLibrary()
        self.registry = Registry(self.log)
        self.fanout = HttpFanout(self.registry, self.library, self.log, session=session)
        self.sequencer = Sequencer(
            self.clock, library=self.library, fanout=self.fanout,
            lead_ms=lead_ms if lead_ms is not None else derive_display_lead(fanout_ms=20.0),
        )
        self.sequencer.text_compiler = _text_compiler(self.log)
        self.guide_document: dict[str, Any] = {}
        #: An effect is sweeping the wall: hold the show off so it cannot be
        #: overwritten mid-sweep. `mementum-led` learned this one first.
        self.effect_until = 0.0
        self._lock = threading.RLock()

    # -- content --------------------------------------------------------

    def load_show(self, document: dict) -> list[str]:
        """A show package: the guide, and every scene it refers to."""
        for entry in document.get("scenes", ()):
            self.library.add(entry["scene"], scene_id=entry["id"])
        guide = Guide.from_document(document)
        problems = self.sequencer.load_guide(guide)
        self.guide_document = document
        self.log.emit(f"GUIDE     {guide.name!r}: {len(guide)} cues, "
                      f"{format_timecode(guide.duration)}, {len(self.library)} scenes")
        for problem in problems:
            self.log.emit(f"  ! {problem}", level="warning")
        return problems

    def compile_text(self, text: str, travel: bool = False) -> int:
        """Words to a scene, now. The escape hatch, reachable over HTTP."""
        document = _text_compiler(self.log)(text, travel=travel)
        return self.library.add(document).scene_id

    # -- the show -------------------------------------------------------

    def tick(self) -> None:
        if time.monotonic() < self.effect_until:
            return
        result = self.sequencer.tick()
        if result:
            for line in str(result).splitlines():
                self.log.emit(f"CUE       {line}")

    def status(self) -> dict:
        sequencer = self.sequencer
        guide = sequencer.guide
        show_time = sequencer.show_time()
        current = guide.scene_at(show_time) if (guide and show_time is not None) else None
        following = guide.next_after(show_time) if (guide and show_time is not None) else None
        return {
            "now": self.clock.shared_now(),
            "guide": guide.name if guide else "",
            "cues": len(guide) if guide else 0,
            "duration": format_timecode(guide.duration) if guide else "",
            "running": sequencer.show_running,
            "show_time": format_timecode(show_time) if show_time is not None else "",
            "current": str(current) if current else "",
            "next": str(following) if following else "",
            "state": sequencer.schedule.state,
            "scene_id": sequencer.schedule.scene_id,
            "lead_ms": sequencer.lead_ms,
            "units": len(self.registry.active()),
            "effect_for": max(0.0, round(self.effect_until - time.monotonic(), 1)),
        }

    # -- workers --------------------------------------------------------

    def start_workers(self) -> None:
        threading.Thread(target=self._tick_loop, daemon=True).start()
        threading.Thread(target=self._cleanup_loop, daemon=True).start()

    def _tick_loop(self) -> None:
        while True:
            try:
                self.tick()
            except Exception as error:                  # a show must not die of one cue
                self.log.emit(f"TICK      failed: {error}", level="error")
            time.sleep(TICK_INTERVAL)

    def _cleanup_loop(self) -> None:
        while True:
            disappeared, purged = self.registry.sweep()
            for client in disappeared:
                self.log.emit(f"DISAPPEAR ID={client.id} IP={client.ip} "
                              f"(no heartbeat for {int(HEARTBEAT_TIMEOUT)}s)")
            for client in purged:
                self.log.emit(f"PURGE     ID={client.id} IP={client.ip} (gone, dropped)")
            time.sleep(CLEANUP_INTERVAL)


def _text_compiler(log):
    """The composer, borrowed. It lives in `tools/` and stays there: the core
    is stdlib-only, and compiling handwriting is composer work (decision 0004).
    """
    def compile_text(text: str, travel: bool = False) -> dict:
        import sys

        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        tools = os.path.join(root, "tools")
        if tools not in sys.path:
            sys.path.insert(0, tools)
        from handwriting import build_scene

        return build_scene(text, width=450, height=250, travel=travel)

    return compile_text


def _int_arg(name: str, default: int, lo: int | None = None, hi: int | None = None) -> int:
    raw = request.args.get(name, "")
    value = int(raw) if raw.lstrip("-").isdigit() else default
    if lo is not None:
        value = max(lo, value)
    if hi is not None:
        value = min(hi, value)
    return value


def _float_arg(name: str, default: float, lo: float | None = None,
               hi: float | None = None) -> float:
    try:
        value = float(request.args.get(name, ""))
    except ValueError:
        value = default
    if lo is not None:
        value = max(lo, value)
    if hi is not None:
        value = min(hi, value)
    return value


def build(server: ControlServer | None = None, **kwargs) -> Flask:
    """The route table. Names and shapes are `mementum-led`'s wherever they
    mean the same thing, so a panel or an operator that knows that server knows
    this one."""
    server = server or ControlServer(**kwargs)
    app = Flask(__name__, static_folder=None)
    app.server = server                          # type: ignore[attr-defined]
    log = server.log

    # -- node plane ------------------------------------------------------

    @app.route("/register")
    def register():
        ip = request.remote_addr or "0.0.0.0"
        kind = (request.args.get("kind") or "lcd").strip().lower()
        client, new = server.registry.register(
            ip, kind=kind,
            version=request.args.get("version", "?"),
            width=_int_arg("width", 0), height=_int_arg("height", 0),
            port=_int_arg("port", 80),
            x=_float_arg("x", None) if request.args.get("x") else None,
            y=_float_arg("y", None) if request.args.get("y") else None,
        )
        server.sequencer.handle(Register(client.descriptor))
        log.emit(f"REGISTER  {'new  ' if new else 'again'} ID={client.id} IP={ip} "
                 f"kind={client.kind} version={client.version}")
        if request.args.get("format") == "json":
            # A panel that speaks the whole protocol gets the running schedule
            # back here, which is late join: it costs no extra mechanism (§19).
            return jsonify({
                "accepted": True,
                "id": client.id, "node_id": client.node_id, "kind": client.kind,
                "server_now": server.clock.shared_now(),
                "leader_epoch": server.sequencer.leader_epoch,
                "lead_ms": server.sequencer.lead_ms,
                "heartbeat_interval": server.sequencer.heartbeat_interval,
                "schedule": _schedule_json(
                    server.sequencer.schedules.get(client.node_id, server.sequencer.schedule)),
            })
        # The LED firmware parses this sentence. Do not reword it.
        return ("Registered successfully. Your ID: %d" % client.id if new
                else "Already registered. Your ID: %d" % client.id)

    @app.route("/heartbeat")
    def heartbeat():
        client = server.registry.heartbeat(request.remote_addr or "0.0.0.0",
                                           port=_int_arg("port", 80))
        if client is None:
            return "Unknown client. Please re-register.", 400
        log.emit(f"HEARTBEAT ack    ID={client.id}", level="debug", journal=False)
        if request.args.get("format") != "json":
            return "Heartbeat acknowledged.", 200      # what the LED firmware expects

        # The recovery path: whatever a panel missed -- a PLAY it never got, a
        # STOP, a whole show -- it learns here, from the schedule as state.
        ack = server.sequencer.handle(Heartbeat(
            node_id=client.node_id,
            state=request.args.get("state", "idle"),
            known_seq=_int_arg("seq", 0),
        ))
        return jsonify({"server_now": ack.server_now, "leader_epoch": ack.leader_epoch,
                        "known": ack.known, "schedule": _schedule_json(ack.schedule)})

    @app.route("/ready")
    def ready():
        """A panel saying it holds a scene. An optimisation for scheduling, not
        a requirement -- the show does not wait for it."""
        node_id = request.args.get("node") or ""
        server.sequencer.handle(Ready(node_id, _int_arg("scene", 0),
                                      request.args.get("hash", "")))
        return jsonify({"status": "ok"})

    @app.route("/time")
    def time_route():
        # Cristian's source, exactly as the LED server offers it: a bare number.
        return str(int(server.clock.shared_now()))

    @app.route("/scene/<int:scene_id>")
    def scene(scene_id: int):
        package = server.library.get(scene_id)
        if package is None:
            return jsonify({"status": "error", "message": "unknown scene"}), 404
        return Response(package.payload, mimetype="application/json")

    @app.route("/asset/<digest>")
    def asset(digest: str):
        """The asset plane. This is why a panel cannot be the server: a string
        fits in a query parameter, a scene and its assets do not, and something
        has to hold them."""
        payload = server.library.asset(digest)
        if payload is None:
            return jsonify({"status": "error", "message": "unknown asset"}), 404
        return Response(payload, mimetype="application/json")

    @app.route("/manifest/<int:scene_id>")
    def manifest(scene_id: int):
        package = server.library.get(scene_id)
        if package is None:
            return jsonify({"status": "error", "message": "unknown scene"}), 404
        return jsonify({"scene_id": package.scene_id, "scene_hash": package.digest,
                        "ir_version": package.ir_version, "duration": package.duration,
                        "requires": package.requires, "name": package.name,
                        "assets": [package.digest], "found": True})

    # -- the show --------------------------------------------------------

    @app.route("/guide", methods=["GET", "POST"])
    def guide_route():
        if request.method == "GET":
            return jsonify(server.guide_document or {"cues": []})
        document = request.get_json(force=True, silent=True) or {}
        problems = server.load_show(document)
        return jsonify({"status": "ok" if not problems else "warning",
                        "problems": problems, **server.status()})

    @app.route("/start")
    def start():
        if server.sequencer.guide is None:
            return jsonify({"status": "error", "message": "no guide loaded"}), 400
        at = parse_timecode(request.args["at"]) if request.args.get("at") else None
        tick = server.sequencer.start_show()
        log.emit(f"SHOW      start {server.sequencer.guide.name!r}")
        if at:
            server.sequencer.seek(at)
        for line in str(tick).splitlines():
            log.emit(f"CUE       {line}")
        return jsonify(server.status())

    @app.route("/seek")
    def seek():
        if server.sequencer.guide is None:
            return jsonify({"status": "error", "message": "no guide loaded"}), 400
        target = request.args.get("at", "0")
        tick = server.sequencer.seek(target)
        log.emit(f"SHOW      seek {format_timecode(parse_timecode(target))}")
        for line in str(tick).splitlines():
            log.emit(f"CUE       {line}")
        return jsonify(server.status())

    @app.route("/stop")
    def stop():
        server.sequencer.stop_show()
        log.emit("SHOW      stop")
        return jsonify(server.status())

    @app.route("/show")
    def show():
        return jsonify(server.status())

    @app.route("/play")
    def play():
        """With no arguments this is the *client* route, and a server has no
        panel: it acknowledges, exactly as the LED server does, so a panel can
        be pointed here without harm. With a scene or words, it plays them."""
        scene_id = _int_arg("scene", 0)
        text = request.args.get("text") or request.args.get("data")
        if not scene_id and not text:
            return "OK", 200
        if text and not scene_id:
            scene_id = server.compile_text(text)
        at = server.clock.shared_now() + server.sequencer.lead_ms
        result = server.sequencer.play(scene_id, at=at)
        log.emit(f"PLAY      scene={scene_id} at={int(at)} "
                 f"targets={len(result.pushes)} text={text!r}")
        if result.refused:
            return jsonify({"status": "error", "message": result.refused}), 400
        return jsonify({"status": "ok", "scene": scene_id, "at": at,
                        "delivered": result.delivered})

    @app.route("/text")
    def text_route():
        """A line decided now. Compiled here and played like anything else --
        the panel holds no font and learns nothing new."""
        words = (request.args.get("data") or request.args.get("text") or "").strip()
        if not words:
            return jsonify({"status": "error", "message": "no words"}), 400
        travel = request.args.get("stagger", "") == "tile"
        scene_id = server.compile_text(words, travel=travel)
        at = server.clock.shared_now() + server.sequencer.lead_ms
        result = server.sequencer.sweep(
            scene_id, at=at, stagger=request.args.get("stagger", ""),
            factor=_float_arg("factor", 1.0, lo=0.05, hi=5.0),
            reverse=request.args.get("reverse", "0") not in ("0", "", "false"),
            order=_order_arg(server),
        )
        log.emit(f"TEXT      {words!r} scene={scene_id} delivered={result.delivered}")
        return jsonify({"status": "ok", "scene": scene_id, "text": words,
                        "delivered": result.delivered})

    @app.route("/effect")
    def effect():
        """A staggered sweep across the wall.

        `mementum-led`'s route, with its parameters and their meanings: `data`
        or `scene` for what sweeps, `stagger` as `auto` (a full go of the
        content per unit), `tile` (one panel width, so it tiles into one long
        marquee) or a time, `factor` to tune those, plus `reverse`, `order`,
        `waves` and `gap`.
        """
        data = request.args.get("data") or request.args.get("text") or ""
        scene_id = _int_arg("scene", 0)
        stagger = (request.args.get("stagger") or "auto").strip().lower()
        factor = _float_arg("factor", 1.0, lo=0.05, hi=5.0)
        waves = _int_arg("waves", 1, lo=1, hi=20)
        lead = _float_arg("lead", server.sequencer.lead_ms, lo=0.0, hi=10_000.0)
        reverse = request.args.get("reverse", "0") not in ("0", "", "false")
        order = _order_arg(server)

        if not scene_id:
            if not data:
                return jsonify({"status": "error", "message": "no data and no scene"}), 400
            scene_id = server.compile_text(data, travel=(stagger == "tile"))

        units = server.sequencer.units_in_order(order=order, reverse=reverse)
        if not units:
            return jsonify({"status": "error", "message": "No active clients."}), 400

        step = server.sequencer.stagger_ms(stagger, scene_id, factor=factor)
        package = server.library.get(scene_id)
        duration = package.duration if package else 0
        span = (len(units) - 1) * step
        wave_len = span + duration
        gap = _float_arg("gap", step, lo=0.0, hi=10_000.0)
        total = waves * (lead + wave_len + gap)

        # Hold the show off for the whole sweep so a cue cannot overwrite it.
        server.effect_until = time.monotonic() + total / 1000.0
        log.emit(f"EFFECT    start data={data!r} scene={scene_id} units={len(units)} "
                 f"stagger={int(step)}ms({stagger}) waves={waves} (~{total / 1000:.1f}s)")

        def run():
            for wave in range(waves):
                at = server.clock.shared_now() + lead
                result = server.sequencer.sweep(scene_id, at=at, stagger=stagger,
                                                factor=factor, reverse=reverse, order=order)
                log.emit(f"EFFECT    wave {wave + 1}/{waves} units={len(units)} "
                         f"delivered={result.delivered}")
                time.sleep((lead + wave_len + gap) / 1000.0)

        threading.Thread(target=run, daemon=True).start()
        return jsonify({"status": "ok", "units": [u for u in units], "scene": scene_id,
                        "stagger_ms": step, "stagger_mode": stagger, "factor": factor,
                        "waves": waves, "duration_ms": total})

    @app.route("/touch")
    def touch_route():
        """A hand on a panel, relayed. The unit that was touched answers at
        once; everybody else is told when, by how far away they stand."""
        node_id = request.args.get("unit") or ""
        if node_id not in server.registry.by_node_id():
            return jsonify({"status": "error", "message": f"no unit {node_id!r}"}), 400
        result = server.sequencer.touch(
            Touch(node_id=node_id, x=_float_arg("x", 0.5), y=_float_arg("y", 0.5),
                  at=server.clock.shared_now()),
            amplitude=_float_arg("amplitude", 0.0),
        )
        log.emit(f"TOUCH     {node_id} -> {len(result.scheduled)} units, "
                 f"spread {result.spread_ms:.0f} ms")
        return jsonify({"status": "ok", "unit": node_id, "reached": result.reached,
                        "spread_ms": result.spread_ms})

    # -- operator --------------------------------------------------------

    @app.route("/clients")
    def clients():
        return jsonify({"now": time.time(), "heartbeat_timeout": HEARTBEAT_TIMEOUT,
                        "clients": server.registry.rows()})

    @app.route("/identify")
    def identify():
        """Every panel shows its own id, so the wall can be read off the wall.

        This is how `order=` gets written: the positions in a guide were typed
        in by a person, and the wall was hung by one.
        """
        seconds = _float_arg("seconds", 10.0, lo=1.0, hi=120.0)
        units = server.sequencer.units_in_order()
        if not units:
            return jsonify({"status": "error", "message": "No active clients."}), 400

        def run():
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                at = server.clock.shared_now() + IDENTIFY_LEAD_MS
                assignments = []
                for node_id in server.sequencer.units_in_order():
                    scene_id = server.compile_text(node_id.replace("unit-", ""))
                    assignments.append((node_id, scene_id, at))
                server.sequencer.assign(assignments)
                package = server.library.get(assignments[0][1])
                time.sleep((IDENTIFY_LEAD_MS + (package.duration if package else 2000)) / 1000)
            log.emit("IDENTIFY  done")

        server.effect_until = time.monotonic() + seconds
        log.emit(f"IDENTIFY  {len(units)} units for {seconds:.0f}s")
        threading.Thread(target=run, daemon=True).start()
        return jsonify({"status": "ok", "units": units, "seconds": seconds})

    @app.route("/clear")
    def clear():
        server.sequencer.stop_show()
        log.emit("CLEAR     wall idle")
        return jsonify(server.status())

    @app.route("/logstream")
    def logstream():
        def generate():
            subscriber = log.subscribe()
            try:
                yield ": connected\n\n"
                for event in log.recent(30):
                    yield "data: %s\n\n" % json.dumps(event)
                while True:
                    try:
                        event = subscriber.get(timeout=15)
                        yield "data: %s\n\n" % json.dumps(event)
                    except Exception:
                        yield ": keep-alive\n\n"
            finally:
                log.unsubscribe(subscriber)
        return Response(generate(), mimetype="text/event-stream", headers={
            "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
            "Connection": "keep-alive"})

    @app.route("/")
    def index():
        return send_from_directory(STATIC, "index.html")

    return app


def _schedule_json(schedule: Schedule) -> dict:
    """The schedule on the wire. Every field, because a panel that receives it
    must be able to act on it alone -- that is what schedule-as-state means."""
    return {"state": schedule.state, "scene_id": schedule.scene_id,
            "scene_hash": schedule.scene_hash, "seq": schedule.seq,
            "display_at": schedule.display_at, "duration": schedule.duration,
            "leader_epoch": schedule.leader_epoch}


def _order_arg(server) -> tuple[str, ...]:
    """`order=3,1,2` names units by id, the way `/identify` shows them."""
    raw = request.args.get("order") or ""
    out = []
    for piece in raw.split(","):
        piece = piece.strip()
        if not piece:
            continue
        out.append(piece if piece.startswith("unit-") else f"unit-{piece}")
    return tuple(out)
