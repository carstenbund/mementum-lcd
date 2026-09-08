"""Record a scene to video — the record pacer, end to end (plan 0b.2, 0b.3).

    python -m sim.record poc/scenes/loop-wave.json --out sim-out/loop-wave.mp4

A recording node is not bound to wall clock at all: it walks scene time in a
loop and renders as fast as it can (proposal §22). That makes it the cheapest
test of determinism in the whole system — rendering the same scene twice must
produce the same frames — so this prints a digest of the run, and two runs of
the same scene at the same frame rate must print the same digest.

Either renderer can drive it, which makes the video a way of *watching* the
cross-renderer comparison rather than only measuring it.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import time

from mementum_node.core.pacer import RecordPacer
from mementum_node.core.render_backend import ReferenceRenderer
from mementum_node.core.scene import load_scene
from mementum_node.sinks.record import FFmpegRecordSink, PngSequenceSink, ffmpeg_available

__all__ = ["record_scene"]


def _renderer(name: str):
    if name == "python":
        return ReferenceRenderer()
    if name == "lvgl":
        from mementum_node.players.lvgl import LvglPlayer

        return LvglPlayer()
    raise ValueError(f"unknown renderer: {name!r}")


def record_scene(
    scene_path: str,
    out_path: str,
    fps: float = 30.0,
    width: int | None = None,
    height: int | None = None,
    renderer_name: str = "python",
    duration_ms: float | None = None,
    keep_frames: bool = False,
) -> dict:
    """Walk the scene's timeline and hand every frame to a record sink."""
    scene = load_scene(scene_path)
    with open(scene_path, "rb") as fh:
        payload = fh.read()

    width = width or scene.width
    height = height or scene.height
    duration = duration_ms if duration_ms is not None else scene.duration

    renderer = _renderer(renderer_name)
    renderer.bind(payload, scene, width, height)

    pacer = RecordPacer(fps)
    times = list(pacer.times(duration))

    if ffmpeg_available():
        sink = FFmpegRecordSink(out_path, width, height, fps).open()
        frames_dir = None
    else:
        frames_dir = os.path.splitext(out_path)[0] + "-frames"
        sink = PngSequenceSink(frames_dir, "frame", fps)

    digest = hashlib.sha256()
    started = time.monotonic()
    for scene_time in times:
        frame = renderer.render(scene_time)
        digest.update(frame.data)
        sink.present(frame, scene_time)
    sink.close()
    elapsed = time.monotonic() - started

    result = {
        "scene": scene_path,
        "renderer": renderer_name,
        "frames": len(times),
        "fps": fps,
        "size": f"{width}x{height}",
        "duration_ms": duration,
        "render_seconds": round(elapsed, 2),
        "ms_per_frame": round(elapsed * 1000 / max(1, len(times)), 1),
        # Two runs of the same scene at the same rate must agree. That is the
        # determinism claim, checkable without looking at anything.
        "digest": digest.hexdigest()[:16],
        "output": out_path if ffmpeg_available() else frames_dir,
    }
    if frames_dir is not None:
        result["merge_with"] = " ".join(sink.merge_command(out_path))
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="record a scene to video")
    parser.add_argument("scene", help="path to a scene package")
    parser.add_argument("--out", default=None, help="output video (default: sim-out/<name>.mp4)")
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument("--size", default=None, help="WxH (default: the design canvas)")
    parser.add_argument("--renderer", default="python", choices=("python", "lvgl"))
    parser.add_argument("--duration", type=float, default=None, help="override, in ms")
    args = parser.parse_args(argv)

    width = height = None
    if args.size:
        width, height = (int(v) for v in args.size.lower().split("x"))

    name = os.path.splitext(os.path.basename(args.scene))[0]
    out = args.out or os.path.join("sim-out", f"{name}-{args.renderer}.mp4")

    result = record_scene(
        args.scene, out, args.fps, width, height, args.renderer, args.duration
    )
    for key, value in result.items():
        print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())
