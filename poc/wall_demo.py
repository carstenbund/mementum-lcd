"""The wall, on the actual screen.

`sim/wall.py` renders a mosaic of simulated nodes to PNG so a diff can be
looked at. This is the same wall with the pictures left in: every unit is a
layer on one panel, every layer holds the *same* scene, and they are all
evaluated against one clock -- which is the whole claim the project rests on.
A wall that is in sync looks like one image repeated; a wall that is not looks
like a mess, immediately and without measuring anything.

The touches are what make it worth watching. A finger on one unit becomes a
ripple on all of them, timed by how far each stands from the one that was
touched -- the real `Sequencer.touch`, at the real `TOUCH_SPEED_M_S`, not a
number invented for a demo. The gesture crosses the wall rather than appearing
everywhere at once.

Input is real where there is any. `drm_touch` reads the mouse (or a touch
panel -- the app never learns which), the pointer overlay follows it on the
reader's own thread, and a click is a touch on whichever unit is under it:
`hit_test` says which, the sequencer says when everybody else joins in. With no
pointer available it falls back to a scripted set of touches, so the wall does
something either way.

    poc/wall_demo.py                                   4x4 on the panel
    poc/wall_demo.py poc/scenes/du-kannst.json 60 5x3
    MM_MODE=1920x1080 poc/wall_demo.py … … … memory    headless, for a capture
    MM_NO_INPUT=1 poc/wall_demo.py                     scripted touches only

It takes DRM master, so it owns the screen while it runs. Reading the mouse
needs membership of the `input` group.
"""

import os
import queue

import sys
import time

sys.path.insert(0, __file__.rsplit("/poc/", 1)[0])

from mementum_node.core.clock import FixedClock, SystemTimeSource         # noqa: E402
from mementum_node.core.protocol import (                                 # noqa: E402
    Capabilities, Display, NodeDescriptor, Position, Register, Touch,
)
from mementum_node.core.sequencer import Sequencer, derive_display_lead    # noqa: E402
from mementum_node.screen import screen_service                           # noqa: E402
from mementum_node.screen.commands import (                               # noqa: E402
    CreateLayer, PlaceScene, StartRipple,
)

#: How far apart the units stand, in metres -- a room, not a monitor. At
#: 2.4 m/s a gesture then takes a couple of seconds to cross a 4x3 wall, which
#: is the point: long enough to see it travelling.
SPACING_M = 2.0

#: The floor under every ripple: a unit cannot be asked to ripple before it has
#: been told to, and fan-out is what sets that (§20). Here fan-out is a function
#: call, so the derivation lands on its floor rather than on DISPLAY_LEAD_MS,
#: which is sized for a radio.
LEAD_MS = derive_display_lead(fanout_ms=1.0)

#: How long one unit ignores a second touch. A person does not touch the same
#: panel twice in a third of a second, but hardware says they did: two devices
#: reporting one button, contact bounce, a held click. Debouncing is the app's
#: job -- the source reports what happened, and what counts as a gesture is
#: decided here.
TOUCH_DEBOUNCE_MS = 400.0

#: Which units get touched, and when (seconds into the run) -- used only when
#: there is no pointer to touch them with.
TOUCHES = ((3.0, 0), (9.0, -1), (15.0, None), (21.0, 0), (27.0, -1))


def grid(screen_w, screen_h, cols, rows, gap=8):
    """Panel rectangles, filling the screen with a gap between units."""
    panel_w = (screen_w - gap * (cols + 1)) // cols
    panel_h = (screen_h - gap * (rows + 1)) // rows
    for row in range(rows):
        for col in range(cols):
            yield (col, row,
                   gap + col * (panel_w + gap),
                   gap + row * (panel_h + gap),
                   panel_w, panel_h)


def start_pointer(service, events, screen):
    """A real pointer, where the machine has one.

    `drm_touch` owns this: it reads the device, maps to screen pixels, and
    fans out -- the cursor overlay on its own thread so it stays smooth however
    busy this loop is, and the event on a queue for whatever the app makes of
    it. A finger and a mouse arrive as the same record.
    """
    if os.environ.get("MM_NO_INPUT"):
        return None
    try:
        from drm_touch import DummyTouch, TouchReader, fan_out, find_pointer_source
    except ImportError:
        print("  input: drm_touch not installed -- scripted touches")
        return None

    source = find_pointer_source(screen.width, screen.height)
    if isinstance(source, DummyTouch):
        print("  input: no pointer found (need the `input` group?) -- scripted touches")
        return None

    reader = TouchReader(source, fan_out(service.submit, events))
    reader.start()
    print(f"  input: {type(source).__name__} -- click a unit to touch it")
    return reader


def touched_unit(service, events, last_touch, now_ms):
    """The unit under the last click, if there was one and it counts.

    Moves are the cursor's business and were handled before this loop saw them;
    what matters here is a contact, and which unit it landed on -- which is
    `hit_test`, the same question a panel with a real touch controller asks.

    `last_touch` is when each unit was last excited, so a bouncing button or a
    held click does not turn one gesture into twenty ripples.
    """
    hit = None
    while True:
        try:
            event = events.get_nowait()
        except queue.Empty:
            break
        if event.phase == "down":
            hit = service.hit_test(event.x, event.y) or hit

    if hit is None or now_ms - last_touch.get(hit, -1e9) < TOUCH_DEBOUNCE_MS:
        return None
    last_touch[hit] = now_ms
    return hit


def excite(service, sequencer, touched, now_ms):
    """One touch -> a ripple on every unit, timed by how far it stands."""
    result = sequencer.touch(Touch(node_id=touched, x=0.45, y=0.5, at=now_ms))

    # The touched unit answers immediately; everybody else is told when to
    # start, and the wave crosses the wall.
    ripples = [StartRipple(touched, origin=0.45, start=now_ms, amplitude=16.0)]
    ripples += [
        StartRipple(node_id, origin=0.45, start=now_ms + delay, amplitude=16.0)
        for node_id, delay in result.scheduled.items()
    ]
    service.submit(ripples)
    print(f"  t={now_ms / 1000:5.1f}s  {touched} touched "
          f"-> {len(ripples)} units, spread {result.spread_ms:.0f} ms")


def main() -> int:
    scene_path = sys.argv[1] if len(sys.argv) > 1 else "poc/scenes/du-kannst.json"
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 30.0
    cols, rows = (int(n) for n in (sys.argv[3] if len(sys.argv) > 3 else "4x4").split("x"))
    display = sys.argv[4] if len(sys.argv) > 4 else "drm"

    with open(scene_path, "rb") as fh:
        scene = fh.read()

    service = screen_service(display=display, width=1920, height=1080, fps=60)
    screen = service.renderer.screen
    print(f"wall: {cols}x{rows} units on {screen.width}x{screen.height} ({display}), "
          f"{SPACING_M} m apart, lead {LEAD_MS:.0f} ms")

    # One sequencer, holding the real units. It is given no fan-out: this
    # process *is* the installation, so a ripple command becomes a call rather
    # than a packet -- the timing it computes is the same either way.
    sequencer = Sequencer(FixedClock(SystemTimeSource()), lead_ms=LEAD_MS)
    panels = {}
    batch = []
    for col, row, x, y, w, h in grid(screen.width, screen.height, cols, rows):
        node_id = f"unit-{row}{col}"
        panels[node_id] = (col, row)
        sequencer.handle(Register(NodeDescriptor(
            node_id=node_id,
            device="linux",
            roles=("display",),
            display=Display(w, h, "rgba8888"),
            capabilities=Capabilities(scene_ir=1, vector=True, text=True, lottie=False),
            position=Position(x=col * SPACING_M, y=row * SPACING_M),
        )))
        batch += [
            # Interactive, because a unit is a thing you can touch: hit_test
            # turns a point on the wall back into the unit standing there.
            CreateLayer(node_id, w, h, x=x, y=y, z=10,
                        interactive=True, hit_id=node_id),
            PlaceScene(node_id, scene),
        ]
    service.submit(batch)

    order = list(panels)
    events = queue.Queue()
    last_touch: dict[str, float] = {}
    reader = start_pointer(service, events, screen) if display != "memory" else None
    pending = [] if reader is not None else list(TOUCHES)
    started = time.monotonic()
    frames = 0

    while True:
        elapsed = (time.monotonic() - started) * 1000.0
        if elapsed > seconds * 1000.0:
            break

        # Every unit is drawn at the same scene time. Nothing accumulates: the
        # picture is a function of the clock, so a dropped frame costs nothing.
        service.render_once(elapsed)
        frames += 1

        touched = None
        if pending and elapsed >= pending[0][0] * 1000.0:
            _, which = pending.pop(0)
            touched = order[which if which is not None else len(order) // 2]
        elif reader is not None:
            touched = touched_unit(service, events, last_touch, elapsed)

        if touched is not None:
            excite(service, sequencer, touched, elapsed)

    if reader is not None:
        reader.stop()
    wall = time.monotonic() - started
    print(f"frames {frames} in {wall:.1f}s = {frames / wall:.1f} fps, "
          f"{service.renderer.last_render_ms:.2f} ms per render "
          f"({cols * rows} scene layers)")
    service.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
