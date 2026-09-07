# Phase 0 host bring-up — test protocol and conclusions

A record of what was run and what it returned, followed by what follows from
it. Covers implementation plan §0.3 steps 1–3 (host LVGL/ThorVG bring-up) and
§3.7 (the C player on the host), performed before any hardware exists.

The full Phase 0 measurement report (`phase0-report.md`, plan §0.6) still awaits
a board: **nothing here is a frame-rate, memory or sync measurement**, and no
Phase 0 gate is satisfied by it.

| | |
|---|---|
| Date | 2026-09-07 11:40 UTC |
| Scope | plan §0.3 steps 1–3; §3.7; risks R1 and R6; proposal open question 7 |
| Revision | `dffffaa` plus the working tree at the time of the run |
| LVGL | v9.5.0, commit `85aa60d1`, with ThorVG vendored at `src/libs/thorvg` |
| Compiler | gcc / g++ 13.3.0 (Ubuntu 13.3.0-6ubuntu2~24.04.1) |
| Platform | Linux 6.8.0-139-generic aarch64, 4 cores |
| Hardware under test | none — no ESP32, no panel, no display of any kind |

---

# Part 1 — Protocol

## 1. Build

No cmake, no SDL, no window: a hand-written Makefile over the LVGL sources with
a headless `lv_conf.h`, rendering into a memory framebuffer.

```bash
poc/host-player/fetch-lvgl.sh          # pins v9.5.0
make -C poc/host-player -j4 probe
```

| Quantity | Value |
|---|---|
| Objects compiled | 531 (463 LVGL `.c`, 67 `.cpp` of which 47 ThorVG, 1 probe) |
| Clean build, `-j4` | **9 s** |
| Binary size | 10,170,168 bytes (unstripped, `-O2 -g`) |
| Warnings from our own sources | 0 |
| Build failures encountered | 2, both missing config: `LV_USE_MATRIX`, then `LV_USE_FLOAT` |

Configuration switches that mattered: `LV_COLOR_DEPTH 32`,
`LV_USE_DRAW_SW 1`, `LV_DRAW_SW_DRAW_UNIT_CNT 1` (single-threaded, for
determinism), `LV_USE_FLOAT 1`, `LV_USE_MATRIX 1`, `LV_USE_VECTOR_GRAPHIC 1`,
`LV_USE_THORVG_INTERNAL 1`.

## 2. Step 2 — does the vector API render a path?

`poc/host-player/probe_vector.c` builds the `poc-signature` path as 12 cubic
segments through `lv_vector_path_cubic_to`, strokes it via
`lv_draw_vector_dsc_*` into an ARGB8888 canvas, and dumps the raw buffer.

```text
probe: LVGL 9.5.0, path length 906.530 px over 12 cubic segments
probe: progress 0.00 -> probe_p000.raw
probe: progress 0.25 -> probe_p025.raw
probe: progress 0.50 -> probe_p050.raw
probe: progress 0.75 -> probe_p075.raw
probe: progress 1.00 -> probe_p100.raw
probe: done
```

Result: **renders.** Five 480×320 frames, 5 ms wall clock for the whole run
including `lv_init` (aarch64 desktop; this is *not* a frame-rate measurement and
implies nothing about an ESP32-S3).

Reference arc length: Python `geometry.polyline_length` gives 906.368 px, the C
probe 906.530 px — 0.02 per cent apart, from different flattening step counts.

## 3. Step 3 — the R1 question: runtime stroke progress

Mechanism under test: `lv_draw_vector_dsc_set_stroke_dash(dsc, {len·p, len}, 2)`,
public API in LVGL 9.5.0, backed by ThorVG's `tvg_shape_set_stroke_dash`.
Neither library exposes a path-length query, so the length is precomputed by the
probe.

```bash
.venv/bin/python poc/host-player/probe_report.py <out-dir>
```

```text
R1 — does the dash reveal scale with arc length?
  progress   lit px   of full  expected
      0.00        0     0.000      0.00
      0.25      858     0.259      0.25
      0.50     1666     0.502      0.50
      0.75     2475     0.746      0.75
      1.00     3317     1.000      1.00

Open question 7 — python reference vs C/LVGL/ThorVG at progress 0.50
  pixels differing   1832 (1.19%)
  max channel delta  63
  ink mass           python 289.2k vs player 287.0k (0.76% apart)
  ink centroid       python (126.60, 192.98) vs player (126.51, 192.96)

  Geometry agreeing while edges differ means the disagreement is
  antialiasing, which is what a perceptual tolerance is for.
```

Visual confirmation: the revealed portion is a **leading prefix** of the path,
not a dashed line along its whole length.

## 4. Regression — the Phase 0c suite

```bash
.venv/bin/python -m pytest -q
```

```text
84 passed in 15.07s
```

One change was required to keep this true: `pytest.ini` now scopes collection to
`tests/`. The vendored LVGL checkout ships its own test scripts, one of which
calls `sys.exit()` at import time and aborted the whole run.

## 5. Artefacts

| File | Purpose |
|---|---|
| `poc/host-player/lv_conf.h` | headless LVGL configuration |
| `poc/host-player/probe_vector.c` | the experiment (187 lines) |
| `poc/host-player/Makefile` | gcc-only build, no cmake |
| `poc/host-player/fetch-lvgl.sh` | pins LVGL v9.5.0 (risk R12) |
| `poc/host-player/probe_report.py` | runs the probe, converts, compares, reports |
| `docs/decisions/0004-stroke-progress.md` | the R1 decision |

---

# Part 2 — Conclusions

## C1. R1 is closed, and the IR is unaffected

`progress` remains a **runtime property**. Lit pixels track the requested
fraction to within one per cent at every sample, and the reveal is a leading
prefix by arc length — the semantics `mementum_node/core/geometry.py` already
defines.

The R1 fallback — compile-time path splitting, with `progress` demoted to a
compile-time slice — is **not needed**. That fallback would have changed
`drm_scene_ir` before it was written, so this was the single unknown most likely
to force a redesign, and it did not. Recorded as decision 0004.

## C2. A new normative requirement: the flattening rule

Because the player computes path length itself, two players that flatten curves
differently reveal at *different rates from the same `progress`*. Our two
implementations already differ by 0.02 per cent in measured length, from nothing
more than a different subdivision count.

The plan says easing must be normative (§14). This adds a second item: **curve
flattening must be normative too.** It is the same class of bug — a divergence
that presents as a sync fault while the clocks are perfect — and it was not on
the list before this experiment.

## C3. `progress` over multiple subpaths is undefined

The probe uses a single-subpath signature. Concatenated arc length or
per-subpath progress are both defensible and produce visibly different
animations. Phase 1 must pick one; today nothing does.

## C4. Cross-renderer comparison needs aggregate metrics, not pixels

Two renderers drawing the same geometry:

| Metric | Result |
|---|---|
| Pixels differing | 1832 of 153,600 (1.19 per cent) |
| Max channel delta | 63 |
| Median delta where differing | 2 |
| Ink mass | 0.76 per cent apart |
| Ink centroid | 0.1 px apart |
| At `progress = 0` | byte-identical |

Every differing pixel lies on a stroke edge. Geometry agreement (centroid, ink
mass) is therefore the right conformance metric across renderers, with per-pixel
comparison reserved for *identical* renderers — which is exactly the split
proposal open question 7 asks about, now with numbers behind it. The
byte-identical empty frame also confirms pixel format and buffer layout agree,
so any future difference is drawing, not plumbing.

## C5. The C player belongs in CI

A full LVGL + ThorVG build takes 9 seconds with nothing but gcc. That was the
practical objection to §3.7's "one evaluator, not two", and it does not hold:
the device's C sources can be compiled and tested on every push, which turns R6
(easing diverging between C and Python) from a discipline problem into a
build-time one.

## C6. What this does not say

* **No frame-rate claim.** This is an aarch64 desktop with a software renderer.
  Whether an ESP32-S3 sustains 30 fps with vector plus text is Phase 0's gate
  and is untouched (R2, R3).
* **No memory claim.** PSRAM bandwidth, draw-buffer sizing and flush cost are
  unmeasured.
* **LVGL on the device is unverified.** These config switches were exercised on
  a host, not under ESP-IDF.
* **Text is not in the probe.** The scene's caption was excluded to keep the
  comparison to one variable; glyph rendering through LVGL — the part §0.3
  step 4 warns may be expensive — remains untested.

## C7. Next step

Promote the probe into the player: `scene_json.c`, `evaluator.c` and
`render_lvgl.c` as C sources shared with the future ESP-IDF build, exposed as a
shared library, with a renderer seam in `ParticipantCore` so a simulated node
can run the C player instead of the Python reference. The existing scenarios
then run unchanged with one node on each renderer, and the C4 comparison becomes
a standing check rather than a one-off measurement.
