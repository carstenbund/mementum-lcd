# 0004 — Stroke progress is a runtime dash reveal

* Status: accepted
* Date: 2026-09-07
* Answers: risk **R1**, the single unknown most likely to change the IR
* Measured on: LVGL v9.5.0 with vendored ThorVG, software renderer, Linux
  aarch64, headless. No hardware.

## Context

`progress` is a v1 animatable property (proposal §10): a signature that draws
itself. The plan flagged the mechanism as unknown — "confirm what ThorVG
exposes through LVGL" — with the fallback being compile-time path splitting,
which would demote `progress` from a runtime property to a compile-time slice
and change `drm_scene_ir` before Phase 1 (R1).

## Decision

`progress` stays a **runtime property**, implemented as a dash pattern:

```c
float dashes[2] = { total_length * progress, total_length };
lv_draw_vector_dsc_set_stroke_dash(dsc, dashes, 2);
```

`lv_draw_vector_dsc_set_stroke_dash` is public API in LVGL 9.5.0 and is backed
by ThorVG's `tvg_shape_set_stroke_dash`.

## Evidence

`poc/host-player/probe_vector.c`, the `poc-signature` path at five progress
values:

| progress | lit pixels | of full | expected |
|---:|---:|---:|---:|
| 0.00 | 0 | 0.000 | 0.00 |
| 0.25 | 858 | 0.259 | 0.25 |
| 0.50 | 1666 | 0.502 | 0.50 |
| 0.75 | 2475 | 0.746 | 0.75 |
| 1.00 | 3317 | 1.000 | 1.00 |

The reveal is a leading prefix by arc length, matching the semantics
`mementum_node/core/geometry.py` already defines, to within 1%.

## Consequences

* **Somebody has to measure the path.** Neither LVGL nor ThorVG exposes a
  path-length query. Two players that flatten differently measure lengths
  0.02 per cent apart, which is invisible — but the composer can just put the
  length in the scene and save the ESP32 the work. Simpler, not stricter.
* `progress` semantics in the IR are "fraction of total arc length", not
  "fraction of segments" and not "fraction of time".
* **The dash restarts at every subpath.** Measured in `probe_subpath.c`: three
  separated strokes with one dash pattern all grow together instead of in
  sequence. Handwriting needs them sequential, so the player must draw
  completed subpaths plain, dash only the one in progress, and skip the rest —
  which needs per-subpath lengths in the scene.
* **At `progress >= 1`, drop the dash.** Otherwise a declared length slightly
  short of the renderer's own leaves the signature permanently unfinished.
* **This is a host result.** The dash reveal is proven to *exist and be
  correct*; whether it is affordable at 30 fps on an ESP32-S3 is Phase 0's
  question and untouched by this decision (R2, R3).

## Rejected

* **Compile-time path splitting** — the R1 fallback. Not needed, and it would
  have made the IR carry pre-sliced geometry per frame.
