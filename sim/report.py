"""Results packages — the artefact a playbook run leaves behind.

A scenario that only prints PASS is hard to argue with and impossible to look
at. This writes what a run actually produced: the frames each client rendered,
side-by-side strips, difference images where they disagree, and a metrics file
holding the numbers rather than prose.

    python -m sim.report linewave --out sim-out/linewave

The comparison rules are the ones the project already uses: within a renderer
family frames must be identical, across families they must be the same picture
(`sim/assert_sync.py`). Text is a known exception and is noted rather than
hidden.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from datetime import datetime, timezone

from mementum_node.core.framebuffer import Frame
from mementum_node.core.png import write_png
from mementum_node.core.renderer import draw_text

from .assert_sync import diff_frames, diff_image, ink, looks_the_same, skew_report
from .wall import mosaic

__all__ = ["write_package"]


def _label_strip(frames: list[tuple[str, Frame]], scene_time: float, tile_width: int) -> Frame:
    return mosaic(
        [(f"{name}  t={scene_time:.0f}ms", frame) for name, frame in frames],
        columns=len(frames),
        tile_width=tile_width,
    )


def write_package(
    result,
    out_dir: str,
    sample_times: tuple[float, ...],
    tile_width: int = 320,
) -> str:
    """Write frames, strips, diffs, metrics and a manifest for a scenario run."""
    harness = result.harness
    nodes = [n for n in harness.nodes if n.sink.wants_pixels and n.core.scene is not None]
    if not nodes:
        raise RuntimeError("no node in this run holds a scene to capture")

    for sub in ("frames", "strips", "diffs", "logs"):
        os.makedirs(os.path.join(out_dir, sub), exist_ok=True)

    metrics: list[dict] = []
    for scene_time in sample_times:
        rendered = [(node.node_id, node.compose(scene_time)) for node in nodes]
        for node_id, frame in rendered:
            write_png(
                frame,
                os.path.join(out_dir, "frames", f"{node_id}_{int(scene_time):05d}.png"),
            )
        write_png(
            _label_strip(rendered, scene_time, tile_width),
            os.path.join(out_dir, "strips", f"t{int(scene_time):05d}.png"),
        )

        # Compare every node against the first, which is the reference by
        # construction: the run puts the Python renderer first.
        base_id, base_frame = rendered[0]
        base_ink = ink(base_frame)
        for node_id, frame in rendered[1:]:
            if (frame.width, frame.height) != (base_frame.width, base_frame.height):
                # A different display is not a disagreement. The canvas is
                # mapped onto it by the fit policy, and comparing the two
                # buffers would be comparing letterboxing, not rendering.
                metrics.append({
                    "scene_time_ms": scene_time,
                    "pair": f"{base_id} vs {node_id}",
                    "comparable": False,
                    "note": f"different display: {base_frame.width}x{base_frame.height} "
                            f"vs {frame.width}x{frame.height}",
                })
                continue
            difference = diff_frames(base_frame, frame)
            other_ink = ink(frame)
            same, detail = looks_the_same(base_frame, frame)
            row = {
                "scene_time_ms": scene_time,
                "pair": f"{base_id} vs {node_id}",
                "comparable": True,
                "same_family": _family(harness, base_id) == _family(harness, node_id),
                "identical": difference.identical,
                "differing_pixels": difference.differing_pixels,
                "differing_fraction": round(difference.fraction, 6),
                "max_channel_delta": difference.max_channel_delta,
                "ink_mass": [round(base_ink.mass, 1), round(other_ink.mass, 1)],
                "ink_centroid_delta_px": round(
                    max(
                        abs(base_ink.centroid_x - other_ink.centroid_x),
                        abs(base_ink.centroid_y - other_ink.centroid_y),
                    ),
                    3,
                ),
                "same_picture": same,
                "detail": detail,
            }
            metrics.append(row)
            if not difference.identical:
                write_png(
                    diff_image(base_frame, frame),
                    os.path.join(
                        out_dir, "diffs", f"{base_id}-{node_id}_{int(scene_time):05d}.png"
                    ),
                )

    manifest = {
        "scenario": result.name,
        "written_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scene": {
            "id": harness.sequencer.schedule.scene_id,
            "hash": harness.sequencer.schedule.scene_hash,
            "path": harness.scene_path,
            "duration_ms": harness.sequencer.schedule.duration,
        },
        "clients": [
            {
                "node_id": node.node_id,
                "renderer": node.renderer_name,
                "display": str(node.core.descriptor.display),
                "device": node.core.descriptor.device,
                "frames_presented": node.core.frames_presented,
                "clock_offset_ms": round(node.clock.offset, 3),
                "heartbeat_recoveries": node.core.recovered_by_heartbeat,
                "asset_pulls": node.core.pulls,
                "joined_at_ms": node.joined_at,
            }
            for node in harness.nodes
        ],
        "sample_times_ms": list(sample_times),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "harness": harness.summary(),
        "checks": [
            {"check": description, "passed": passed, "detail": detail}
            for description, passed, detail in result.checks
        ],
        "scenario_metrics": {k: str(v) for k, v in result.metrics.items()},
        "passed": result.passed,
    }

    _write_json(os.path.join(out_dir, "manifest.json"), manifest)
    _write_json(os.path.join(out_dir, "metrics.json"), metrics)
    _write_json(
        os.path.join(out_dir, "logs", "timing.json"),
        {
            "virtual_ms": harness.master.now,
            "skew": str(skew_report(harness.nodes)),
            "display_lead_ms": harness.sequencer.lead_ms,
            "heartbeat_interval_ms": harness.heartbeat_ms,
            "play_history": [
                {
                    "seq": play.schedule.seq,
                    "scene_id": play.schedule.scene_id,
                    "display_at_ms": round(play.schedule.display_at, 3),
                    "delivered": play.delivered,
                    "fanout_ms": round(play.fanout_ms, 3),
                }
                for play in harness.sequencer.play_history
            ],
        },
    )
    _write_summary(os.path.join(out_dir, "summary.md"), result, manifest, metrics)
    return out_dir


def _family(harness, node_id: str) -> str:
    return harness.node(node_id).renderer_name


def _write_json(path: str, payload) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=False)
        fh.write("\n")


def _write_summary(path: str, result, manifest: dict, metrics: list[dict]) -> None:
    passed = sum(1 for c in manifest["checks"] if c["passed"])
    comparable = [row for row in metrics if row.get("comparable")]

    lines = [
        f"# {result.name} — run summary",
        "",
        f"* written: {manifest['written_at']}",
        f"* scene: {manifest['scene']['path']} "
        f"(id {manifest['scene']['id']}, {manifest['scene']['duration_ms']:.0f} ms)",
        f"* clients: " + ", ".join(
            f"{c['node_id']} ({c['renderer']}, {c['display']})" for c in manifest["clients"]
        ),
        f"* checks: {passed}/{len(manifest['checks'])} passed",
        "",
        "## Comparisons",
        "",
        "| scene time | pair | same family | differing px | ink centroid | verdict |",
        "|---:|---|---|---:|---:|---|",
    ]
    for row in comparable:
        verdict = "identical" if row["identical"] else (
            "same picture" if row["same_picture"] else "DIFFERENT"
        )
        lines.append(
            f"| {row['scene_time_ms']:.0f} | {row['pair']} | "
            f"{'yes' if row['same_family'] else 'no'} | "
            f"{row['differing_pixels']} | {row['ink_centroid_delta_px']:.2f} px | {verdict} |"
        )
    skipped = [row for row in metrics if not row.get("comparable")]
    if skipped:
        lines += ["", f"{len(skipped)} comparison(s) skipped: "
                      + skipped[0]["note"] + " — a different display is not a disagreement."]
    lines += ["", "## Checks", ""]
    for check in manifest["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        detail = f" — {check['detail']}" if check["detail"] else ""
        lines.append(f"* **{mark}** {check['check']}{detail}")
    lines.append("")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def main(argv=None) -> int:
    from . import scenarios

    parser = argparse.ArgumentParser(description="run a scenario and write a results package")
    parser.add_argument("scenario", choices=scenarios.NAMES)
    parser.add_argument("--out", default=None)
    parser.add_argument(
        "--times",
        default="600,1200,2200,3200,4200,5200,6800,8400,9500",
        help="scene times in ms to capture",
    )
    parser.add_argument("--tile-width", type=int, default=320)
    args = parser.parse_args(argv)

    result = scenarios.run(args.scenario)
    out_dir = args.out or os.path.join("sim-out", args.scenario)
    times = tuple(float(t) for t in args.times.split(",") if t.strip())
    write_package(result, out_dir, times, args.tile_width)

    print(f"{out_dir}  {'PASSED' if result.passed else 'FAILED'}")
    for name in ("manifest.json", "metrics.json", "summary.md"):
        print(f"  {os.path.join(out_dir, name)}")
    return 0 if result.passed else 1


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())
