"""`drm_screen` code, LVGL underneath -- the whole point, in one file.

Nothing below is this project's vocabulary. `CreateLayer`, `PlaceRawBuffer`,
`SetPosition`, `SetZ`, `SetPointer` and `hit_test` are `drm_screen`'s, and
`PlaceScene` is now too -- it went upstream with the renderer seam. The service
is `drm_screen`'s where that package is installed, and a stdlib loop where it
is not; the renderer is `drm_screen_lvgl` either way, binding the C in
`poc/player/`. What this file demonstrates is a scene layer: a description
handed over once and drawn from paths at the panel's own resolution.

    poc/screen_demo.py poc/scenes/du-kannst.json 20 drm
    poc/screen_demo.py poc/scenes/du-kannst.json 5 memory   # headless, no panel

With MM_MODE=1920x1080 the DRM backend asks for that mode.
"""

import sys
import time

sys.path.insert(0, __file__.rsplit("/poc/", 1)[0])

from mementum_node.screen import screen_service                          # noqa: E402
from mementum_node.screen.commands import (                              # noqa: E402
    CreateLayer, PlaceRawBuffer, PlaceScene, SetPointer, SetPosition,
)


def solid(width: int, height: int, rgba) -> bytes:
    return bytes(rgba) * (width * height)


def main() -> int:
    scene_path = sys.argv[1] if len(sys.argv) > 1 else "poc/scenes/du-kannst.json"
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 10.0
    backend = sys.argv[3] if len(sys.argv) > 3 else "drm"

    with open(scene_path, "rb") as fh:
        scene = fh.read()

    service = screen_service(display=backend, width=960, height=540, fps=60)
    screen = service.renderer.screen
    print(f"screen: {screen.width}x{screen.height} on {backend} "
          f"({type(service).__module__.split('.')[0]} service)")

    # A scene layer filling the panel, and a bitmap layer over it -- the same
    # two kinds of content drm_screen has always had, except one of them never
    # becomes pixels until it reaches the panel.
    badge = 180, 44
    service.submit([
        CreateLayer("writing", screen.width, screen.height, z=10),
        PlaceScene("writing", scene),
        CreateLayer("badge", badge[0], badge[1], x=32, y=32, z=20, opacity=0.75,
                    interactive=True, hit_id="badge"),
        PlaceRawBuffer("badge", badge[0], badge[1], data=solid(*badge, (24, 40, 56, 255))),
        SetPointer(x=screen.width // 2, y=screen.height // 2),
    ])

    started = time.monotonic()
    frames = 0
    render_total = 0.0
    while True:
        elapsed = (time.monotonic() - started) * 1000.0
        if elapsed > seconds * 1000.0:
            break
        # The picture is a function of the clock, here as everywhere else.
        service.render_once(elapsed)
        render_total += screen.last_render_ms
        frames += 1

        # A moving overlay, to show that a bitmap layer above a scene layer
        # costs only its own dirty rectangle.
        if frames % 6 == 0:
            x = 32 + int(120 * abs(((elapsed / 2000.0) % 2.0) - 1.0))
            service.submit([
                SetPosition("badge", x, 32),
                SetPointer(x=x + badge[0] // 2, y=32 + badge[1] // 2),
            ])

    wall = time.monotonic() - started
    print(f"frames {frames} in {wall:.1f}s = {frames / wall:.1f} fps, "
          f"{render_total / max(frames, 1):.2f} ms per render")
    badge_layer = screen.layers["badge"]
    inside = badge_layer["x"] + 8, badge_layer["y"] + 8
    print(f"hit_test{inside} ->", service.hit_test(*inside))
    print("hit_test(8, 8) ->", service.hit_test(8, 8))
    service.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
