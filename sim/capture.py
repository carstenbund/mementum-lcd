"""Frame capture -- tune in to any node (plan §3.6).

A headless node still has a complete composited frame in memory; nothing about
being headless makes it invisible. Capturing that buffer is what turns the
simulation from a pass/fail suite into something you can watch.

Capture happens at the **sink boundary**, not from hardware, so the identical
tool works for a simulated node, a headless test and a real Raspberry Pi node.
On the ESP32 there is no spare full frame to ship and the two tiers are
different: a frame hash always on, a downscaled thumbnail on request only.

    python -m sim.capture --scenario basic_play --node node-000 \\
        --times 0,1000,2100,4200 --out sim-out/
"""

from __future__ import annotations

import argparse
import os

from mementum_node.core.framebuffer import Frame
from mementum_node.core.png import write_png
from mementum_node.core.renderer import draw_text

__all__ = ["annotate", "capture_live", "capture_at", "capture_sequence", "golden_path"]


def annotate(frame: Frame, label: str, size: int = 14) -> Frame:
    """Stamp a label into a copy of the frame. Never on the render path."""
    out = frame.copy()
    pad = max(2, size // 3)
    out.fill_rect(0, 0, out.width, size + 2 * pad, (0, 0, 0, 255))
    draw_text(out, label, pad, pad, size, (220, 224, 235))
    return out


def capture_live(node, path: str, label: str | None = None) -> str:
    """Write the frame the node last presented -- what it is showing now."""
    frame = node.frame
    if frame is None:
        raise RuntimeError(f"node {node.node_id} has presented no frame")
    if label is not None:
        frame = annotate(frame, label)
    return write_png(frame, path)


def capture_at(node, scene_time: float, path: str, label: str | None = None) -> str:
    """Composite the node at an arbitrary scene time and write it out. Does not
    disturb playback, so a capture never perturbs what it measures."""
    frame = node.compose(scene_time)
    if label is not None:
        frame = annotate(frame, label)
    return write_png(frame, path)


def capture_sequence(node, times, out_dir: str, prefix: str | None = None) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    prefix = prefix or node.node_id
    written = []
    for scene_time in times:
        name = f"{prefix}_t{int(round(scene_time)):06d}.png"
        written.append(capture_at(node, scene_time, os.path.join(out_dir, name)))
    return written


def golden_path(out_dir: str, scene_name: str, scene_time: float) -> str:
    """Naming for golden frames. Diffed in CI, regenerated deliberately and
    never automatically, and only meaningful with pinned library versions
    (risk R12) -- which is one reason nothing here depends on an image
    library."""
    return os.path.join(out_dir, f"{scene_name}_t{int(round(scene_time)):06d}.png")


def _main(argv=None) -> int:
    from . import scenarios

    parser = argparse.ArgumentParser(description="capture a simulated node's buffer")
    parser.add_argument("--scenario", default="basic_play", help="scenario to run first")
    parser.add_argument("--node", default=None, help="node id (default: the first node)")
    parser.add_argument("--times", default="0,1050,2100,3150,4200", help="scene times in ms")
    parser.add_argument("--out", default="sim-out", help="output directory")
    args = parser.parse_args(argv)

    result = scenarios.run(args.scenario)
    harness = result.harness
    node = harness.node(args.node) if args.node else harness.nodes[0]
    times = [float(t) for t in args.times.split(",") if t.strip()]
    for path in capture_sequence(node, times, args.out):
        print(path)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(_main())
