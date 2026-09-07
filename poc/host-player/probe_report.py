#!/usr/bin/env python3
"""Run the vector probe and compare it against the Python reference renderer.

The whole host-side experiment in one command:

    poc/host-player/fetch-lvgl.sh
    make -C poc/host-player -j4 probe
    .venv/bin/python poc/host-player/probe_report.py

It answers two questions with numbers rather than adjectives:

* **R1** — does a runtime stroke reveal work through LVGL/ThorVG? Lit-pixel
  count against progress says whether the dash pattern reveals proportionally
  to arc length.
* **Open question 7** — how far apart are two different renderers drawing the
  same scene? Exact equality is not available across renderers; what matters is
  whether the disagreement is antialiasing (small, at edges) or geometry
  (large, everywhere). Ink mass and centroid separate the two.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from mementum_node.core.evaluator import evaluate  # noqa: E402
from mementum_node.core.framebuffer import Frame  # noqa: E402
from mementum_node.core.png import write_png  # noqa: E402
from mementum_node.core.renderer import render_scene  # noqa: E402
from mementum_node.core.scene import load_scene  # noqa: E402
from sim.assert_sync import diff_frames, diff_image  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PROBE = os.path.join(HERE, "build", "probe_vector")
SCENE = os.path.join(ROOT, "poc", "scenes", "poc-signature.json")
BACKGROUND = 0x10

#: ease-in-out puts `progress` at exactly 0.5 at this scene time, and the
#: caption is still fully transparent, so both renderers draw the same thing.
HALFWAY_MS = 2100.0
WIDTH, HEIGHT = 480, 320


def load_raw(path: str) -> Frame:
    """LVGL's ARGB8888 is B,G,R,A in memory on a little-endian host."""
    with open(path, "rb") as fh:
        data = bytearray(fh.read())
    for i in range(0, len(data), 4):
        data[i], data[i + 2] = data[i + 2], data[i]
    return Frame(WIDTH, HEIGHT, data)


def ink(frame: Frame) -> tuple[float, float, float]:
    """Total luminance above the background, and its centroid. Geometry that
    agrees will agree here even when every edge pixel differs."""
    total = sx = sy = 0.0
    for y in range(frame.height):
        row = y * frame.width
        for x in range(frame.width):
            value = frame.data[(row + x) * 4] - BACKGROUND
            if value > 8:
                total += value
                sx += x * value
                sy += y * value
    return (total, sx / total if total else 0.0, sy / total if total else 0.0)


def main(out_dir: str | None = None) -> int:
    if not os.path.exists(PROBE):
        print(f"probe not built: {PROBE}\nrun: make -C poc/host-player -j4 probe", file=sys.stderr)
        return 2

    out_dir = out_dir or tempfile.mkdtemp(prefix="probe-")
    os.makedirs(out_dir, exist_ok=True)
    subprocess.run([PROBE, out_dir], check=True, stdout=subprocess.DEVNULL)

    print(f"output: {out_dir}\n")
    print("R1 — does the dash reveal scale with arc length?")
    lit_counts = {}
    for percent in (0, 25, 50, 75, 100):
        frame = load_raw(os.path.join(out_dir, f"probe_p{percent:03d}.raw"))
        write_png(frame, os.path.join(out_dir, f"probe_p{percent:03d}.png"))
        lit_counts[percent] = sum(1 for i in range(0, len(frame.data), 4) if frame.data[i] > 40)

    full = lit_counts[100]
    print(f"  {'progress':>8}  {'lit px':>7}  {'of full':>8}  {'expected':>8}")
    for percent, lit in lit_counts.items():
        share = lit / full if full else 0.0
        print(f"  {percent / 100:8.2f}  {lit:7d}  {share:8.3f}  {percent / 100:8.2f}")

    reference = render_scene(evaluate(load_scene(SCENE), HALFWAY_MS))
    player = load_raw(os.path.join(out_dir, "probe_p050.raw"))
    write_png(reference, os.path.join(out_dir, "python_p050.png"))
    write_png(diff_image(reference, player), os.path.join(out_dir, "diff_p050.png"))

    report = diff_frames(reference, player)
    py_ink, py_cx, py_cy = ink(reference)
    c_ink, c_cx, c_cy = ink(player)

    print("\nOpen question 7 — python reference vs C/LVGL/ThorVG at progress 0.50")
    print(f"  pixels differing   {report.differing_pixels} ({report.fraction * 100:.2f}%)")
    print(f"  max channel delta  {report.max_channel_delta}")
    print(f"  ink mass           python {py_ink / 1000:.1f}k vs player {c_ink / 1000:.1f}k "
          f"({abs(py_ink - c_ink) / py_ink * 100:.2f}% apart)")
    print(f"  ink centroid       python ({py_cx:.2f}, {py_cy:.2f}) vs player ({c_cx:.2f}, {c_cy:.2f})")
    print("\n  Geometry agreeing while edges differ means the disagreement is")
    print("  antialiasing, which is what a perceptual tolerance is for.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else None))
