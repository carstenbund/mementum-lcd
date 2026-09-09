"""The show, on the wall: a guide played by the control server.

Everything here is the real thing doing its real job. The sequencer holds the
guide and the clock, decides what is due, and pushes it. The wall is sixteen
units, each a layer. Between them sits a fan-out that turns a push into screen
commands -- which is exactly what a node does on a panel, minus the radio.

    server            guide + clock -> PLAY / RippleCommand   (mementum_node.core)
    fan-out           push -> PlaceScene / StartRipple        (this file)
    screen            layers -> LVGL -> DRM/KMS               (drm_screen[_lvgl])

A cue's timecode becomes a displayAt, every unit evaluates
`sharedNow() - displayAt`, and nothing anywhere accumulates. Click a unit and
the show is interrupted by a hand, which the server treats as a touch like any
other.

    tools/guide.py poc/shows/opening.html --out poc/shows/opening.json
    MM_MODE=1920x1080 poc/show_demo.py poc/shows/opening.json 60 4x4 drm
"""

import json
import os
import queue
import sys
import time

sys.path.insert(0, __file__.rsplit("/poc/", 1)[0])
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wall_demo import SPACING_M, grid, start_pointer, touched_unit             # noqa: E402

from mementum_node.core.clock import FixedClock, SystemTimeSource              # noqa: E402
from mementum_node.core.guide import Guide, format_timecode                    # noqa: E402
from mementum_node.core.library import SceneLibrary                            # noqa: E402
from mementum_node.core.protocol import (                                      # noqa: E402
    Capabilities, Display, NodeDescriptor, Play, Position, Register, RippleCommand,
)
from mementum_node.core.sequencer import Sequencer, derive_display_lead        # noqa: E402
from mementum_node.core.transport import PushResult                            # noqa: E402
from mementum_node.screen import screen_service                                # noqa: E402
from mementum_node.screen.commands import (                                    # noqa: E402
    CreateLayer, PlaceScene, SetSceneOffset, StartRipple,
)

LEAD_MS = derive_display_lead(fanout_ms=1.0)


class WallFanout:
    """Server pushes in, screen commands out -- the node, standing in.

    A PLAY carries a schedule, and a schedule belongs to a unit: which scene,
    and the moment it starts. When the wall is one picture every unit gets the
    same one; when a cue is staggered, dealt or run through, they do not, and
    this is where that difference becomes a layer with a clock of its own.

    The screen is rendered once, at `now - origin`, where the origin is fixed
    for the whole show. A layer's offset is `displayAt - origin`, so each unit
    evaluates `now - displayAt` -- the same arithmetic it would do on a panel,
    and no unit's scene time is disturbed by a cue addressed to another.
    """

    def __init__(self, service, library, layers):
        self.service = service
        self.library = library
        self.layers = layers                 # node_id -> layer name (they match)
        self.origin: float | None = None
        self.display_at: dict[str, float] = {}

    def push(self, node_ids, message):
        node_ids = list(node_ids)
        if isinstance(message, Play):
            self._play(message.schedule, node_ids)
        elif isinstance(message, RippleCommand):
            self._ripple(message, node_ids)
        return [PushResult(node_id, True, 0.1) for node_id in node_ids]

    def _play(self, schedule, node_ids):
        package = self.library.get(schedule.scene_id)
        if package is None:
            return
        if self.origin is None:
            self.origin = schedule.display_at

        batch = []
        for node_id in node_ids:
            self.display_at[node_id] = schedule.display_at
            batch.append(PlaceScene(node_id, package.payload))
            batch.append(SetSceneOffset(node_id, schedule.display_at - self.origin))
        self.service.submit(batch)

    def _ripple(self, command, node_ids):
        """A ripple's moment is shared time; a layer's clock is its own, so the
        conversion is per unit -- which is what makes a wave cross a staggered
        wall correctly rather than arriving everywhere at the same point of the
        scene."""
        amplitude = command.amplitude or 12.0
        batch = []
        for node_id in node_ids:
            display_at = self.display_at.get(node_id)
            if display_at is None:
                continue
            batch.append(StartRipple(node_id, origin=command.x,
                                     start=command.start_at - display_at,
                                     amplitude=amplitude))
        if batch:
            self.service.submit(batch)

    def scene_time(self, now):
        return None if self.origin is None else now - self.origin


def main() -> int:
    show_path = sys.argv[1] if len(sys.argv) > 1 else "poc/shows/opening.json"
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 60.0
    cols, rows = (int(n) for n in (sys.argv[3] if len(sys.argv) > 3 else "4x4").split("x"))
    display = sys.argv[4] if len(sys.argv) > 4 else "drm"

    with open(show_path, "r", encoding="utf-8") as fh:
        show = json.load(fh)

    library = SceneLibrary()
    for entry in show.get("scenes", ()):
        library.add(entry["scene"], scene_id=entry["id"])
    guide = Guide.from_document(show)

    service = screen_service(display=display, width=1920, height=1080, fps=60)
    screen = service.renderer.screen
    clock = FixedClock(SystemTimeSource())
    sequencer = Sequencer(clock, library=library, lead_ms=LEAD_MS)

    batch, layers = [], {}
    for col, row, x, y, w, h in grid(screen.width, screen.height, cols, rows):
        node_id = f"unit-{row}{col}"
        layers[node_id] = node_id
        sequencer.handle(Register(NodeDescriptor(
            node_id=node_id, device="linux", roles=("display",),
            display=Display(w, h, "rgba8888"),
            capabilities=Capabilities(scene_ir=1, vector=True, text=True, lottie=False),
            position=Position(x=col * SPACING_M, y=row * SPACING_M),
        )))
        batch.append(CreateLayer(node_id, w, h, x=x, y=y, z=10,
                                 interactive=True, hit_id=node_id))
    service.submit(batch)

    fanout = WallFanout(service, library, layers)
    sequencer.fanout = fanout

    problems = sequencer.load_guide(guide)
    print(f"show: {guide.name!r}, {len(guide)} cues, {format_timecode(guide.duration)}, "
          f"{len(library)} scenes on {cols}x{rows} units")
    for problem in problems:
        print(f"  ! {problem}")

    events = queue.Queue()
    reader = start_pointer(service, events, screen) if display != "memory" else None
    last_touch: dict[str, float] = {}

    opening = sequencer.start_show()
    if opening:
        print(opening)
    started = time.monotonic()
    frames = 0
    while True:
        elapsed = (time.monotonic() - started) * 1000.0
        if elapsed > seconds * 1000.0:
            break

        tick = sequencer.tick()
        if tick:
            print(tick)

        # A hand in the middle of the show: the server treats it as a touch,
        # and the wave crosses the wall while the scene keeps playing.
        if reader is not None:
            from mementum_node.core.protocol import Touch

            touched = touched_unit(service, events, last_touch, elapsed)
            if touched is not None:
                result = sequencer.touch(
                    Touch(node_id=touched, x=0.45, y=0.5, at=clock.shared_now()),
                    amplitude=16.0,
                )
                print(f"  {format_timecode(sequencer.show_time() or 0)}  hand: {touched} "
                      f"-> spread {result.spread_ms:.0f} ms")

        scene_time = fanout.scene_time(clock.shared_now())
        if scene_time is not None:
            service.render_once(scene_time)
            frames += 1

    wall = time.monotonic() - started
    print(f"frames {frames} in {wall:.1f}s = {frames / max(wall, 1e-9):.1f} fps, "
          f"{service.renderer.last_render_ms:.2f} ms per render")
    if reader is not None:
        reader.stop()
    service.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
