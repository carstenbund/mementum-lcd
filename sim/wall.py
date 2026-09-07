"""The virtual video wall (plan §3.6).

Compose every node's buffer into one mosaic: the whole installation on a single
screen. With 300 simulated participants this is the difference between a
legible swarm and a log file, and for a heterogeneous set -- 480x320 beside
1920x1080 beside a projector -- it is how the design-canvas ``fit`` policy (§6)
gets checked: by looking at it.

    python -m sim.wall --scenario basic_play --nodes 9 --out sim-out/wall.png

Skew becomes visible the same way: capture every node at one instant of virtual
time and label each tile with its own scene time.
"""

from __future__ import annotations

import argparse
import math
import os

from mementum_node.core.framebuffer import Frame
from mementum_node.core.png import write_png
from mementum_node.core.renderer import draw_text

__all__ = ["mosaic", "wall_live", "wall_at"]

_BACKDROP = (24, 24, 30, 255)
_TILE_BG = (12, 12, 16, 255)
_LABEL = (168, 178, 198)


def mosaic(
    tiles: list[tuple[str, Frame]],
    columns: int | None = None,
    tile_width: int = 240,
    gap: int = 8,
    label_height: int = 16,
) -> Frame:
    """Tile labelled frames into one image, preserving each one's aspect ratio.

    Heterogeneous displays are the point, so tiles are letterboxed into a common
    cell rather than stretched -- the same discipline the ``fit`` policy applies
    on a real node."""
    if not tiles:
        raise ValueError("the wall needs at least one node")
    columns = columns or max(1, min(len(tiles), int(math.ceil(math.sqrt(len(tiles))))))
    rows = int(math.ceil(len(tiles) / columns))

    aspect = max(frame.height / frame.width for _, frame in tiles)
    cell_w = tile_width
    cell_h = int(round(tile_width * aspect))

    width = gap + columns * (cell_w + gap)
    height = gap + rows * (cell_h + label_height + gap)
    out = Frame.filled(width, height, _BACKDROP)

    for index, (label, frame) in enumerate(tiles):
        col, row = index % columns, index // columns
        x = gap + col * (cell_w + gap)
        y = gap + row * (cell_h + label_height + gap)
        scale = min(cell_w / frame.width, cell_h / frame.height)
        w = max(1, int(frame.width * scale))
        h = max(1, int(frame.height * scale))
        out.fill_rect(x, y, cell_w, cell_h, _TILE_BG)
        out.blit(frame.scaled(w, h), x + (cell_w - w) // 2, y + (cell_h - h) // 2)
        draw_text(out, label, x + 1, y + cell_h + 3, label_height - 5, _LABEL)
    return out


def _label(node, scene_time: float | None) -> str:
    display = node.core.descriptor.display
    position = "--" if scene_time is None else f"{scene_time:7.1f}ms"
    return f"{node.node_id} {display.width}x{display.height} {position} {node.state}"


def wall_live(nodes, columns: int | None = None, tile_width: int = 240) -> Frame:
    """The wall as it is right now: each node's last presented frame, labelled
    with the scene time it was presented at. Nodes that have presented nothing
    show as empty tiles rather than being hidden."""
    tiles = []
    for node in nodes:
        frame = node.frame
        if frame is None:
            display = node.core.descriptor.display
            frame = Frame.filled(display.width, display.height, _TILE_BG)
        tiles.append((_label(node, node.core.last_scene_time), frame))
    return mosaic(tiles, columns, tile_width)


def wall_at(nodes, scene_time: float, columns: int | None = None, tile_width: int = 240) -> Frame:
    """The wall as every node *would* render one scene time. Identical tiles
    here are the buffer-identity claim, seen rather than asserted."""
    tiles = [(_label(node, scene_time), node.compose(scene_time)) for node in nodes]
    return mosaic(tiles, columns, tile_width)


def _main(argv=None) -> int:
    from . import scenarios

    parser = argparse.ArgumentParser(description="render the virtual video wall")
    parser.add_argument("--scenario", default="basic_play")
    parser.add_argument("--out", default=os.path.join("sim-out", "wall.png"))
    parser.add_argument("--tile-width", type=int, default=240)
    parser.add_argument("--columns", type=int, default=None)
    parser.add_argument(
        "--at", type=float, default=None, help="scene time in ms (default: live frames)"
    )
    args = parser.parse_args(argv)

    result = scenarios.run(args.scenario)
    nodes = [n for n in result.harness.nodes if n.sink.wants_pixels]
    frame = (
        wall_live(nodes, args.columns, args.tile_width)
        if args.at is None
        else wall_at(nodes, args.at, args.columns, args.tile_width)
    )
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    write_png(frame, args.out)
    print(f"{args.out}  {frame.width}x{frame.height}  {len(nodes)} nodes")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(_main())
