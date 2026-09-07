# Phase 0 host bring-up — test protocol and conclusions

A record of what was run and what it returned, followed by what follows from
it. Covers implementation plan §0.3 steps 1–3 (host LVGL/ThorVG bring-up) and
§3.7 (the C player on the host), performed before any hardware exists.

**On the standard being applied.** The numbers below are measured because
measuring is cheap and repeatable, not because this is instrumentation. What is
being built shows handwriting that appears and is gone in a few seconds. The
test that matters is whether a person watching would notice something wrong —
strokes arriving in the wrong order, an animation that never finishes, two
panels visibly out of step. Differences far below that threshold are recorded
here for completeness and should not be allowed to drive design.

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
| `poc/host-player/probe_vector.c` | the stroke-progress experiment (187 lines) |
| `poc/host-player/probe_subpath.c` | does the dash run across subpaths? (no) |
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

## C2. Put the path length in the IR, and stop worrying about flattening

Because the player computes path length itself, two players that flatten curves
differently reveal at slightly different rates. Ours differ by 0.162 px on 906 —
about 0.02 per cent, which at half-progress puts the pen tip 0.08 px apart.

Nobody will ever see that. It is not a reason to specify a flattening algorithm,
and specifying one would not work anyway: ThorVG flattens internally to
rasterise, and a rule we cannot make a third-party renderer obey is not a rule.

The simpler answer is to carry the length in the scene:

```json
{ "type": "path", "id": "signature", "d": "M ...", "length": 906.42 }
```

The composer works it out once, every player uses the same number, and the
ESP32 does not flatten a curve just to measure it. Do the interpretive work in
the composer; keep the player simple. That is worth doing because it is
*simpler*, not because the current difference is a problem.

## C3. Multiple subpaths — and the one thing the renderer will not do for us

The probe uses a single-subpath signature. For handwriting the natural reading
of `progress` is one continuous pen trajectory: the fraction of the total
ordered drawing length, strokes appearing one after another, nothing drawn
during the lift between them.

A second probe (`probe_subpath.c`) shows that a single dash pattern cannot
express that. Three separated 100 px lines drawn with one `[150, 300]` dash —
"reveal the first half" — come out like this:

```text
stroke 1  drawn in full
stroke 2  drawn in full
stroke 3  drawn in full
```

ThorVG restarts the dash at every `moveTo`, so all three strokes grow at once
instead of in sequence. That *is* visible, immediately, and it is the difference
between handwriting and a light show.

So the player has to do the sequencing itself: draw the completed subpaths
plain, dash only the one being drawn, skip the rest. Which means the scene needs
per-subpath lengths as well as the total —

```text
length 906.42
subpaths  312.1  194.8  399.5
```

— not as bookkeeping, but because without them the player cannot tell which
stroke it is currently in the middle of.

## C4. The two renderers draw the same picture

Python reference against C/LVGL/ThorVG, same scene, same instant:

| Metric | Result |
|---|---|
| Pixels differing | 1832 of 153,600 (1.19 per cent) |
| Median delta where differing | 2 of 255 |
| Max channel delta | 63 |
| Ink mass | 0.76 per cent apart |
| Ink centroid | 0.1 px apart |
| At `progress = 0` | byte-identical |

Every differing pixel is on a stroke edge. Two people looking at the two frames
would not be able to tell them apart, which is the standard that actually
applies here: this is a signature that appears and is gone in four seconds, not
a measurement instrument.

The numbers are still worth keeping, for one narrow purpose. Between *identical*
renderers an exact buffer comparison is a cheap tripwire for gross breakage — a
node showing the wrong frame, seeking to the wrong time, missing a command. That
is what the simulator's buffer assertions are for. Across *different* renderers
the same comparison means nothing, and the aggregate figures above are the
sensible way to ask "is it still the same picture?".

## C5. One rule worth writing down: finish the stroke

If the declared length is even slightly shorter than what the renderer measures
internally, a dash of `[length, length]` leaves the last fraction of the path
permanently undrawn — the signature never quite finishes, at exactly the moment
someone is watching it finish. The fix is trivial: at `progress >= 1`, drop the
dash and stroke the path plainly. The probe already does this; it should be a
rule rather than an accident.

This is the kind of thing worth being careful about — a visible failure at the
end of the animation — as distinct from the sub-pixel differences above, which
are not.

## C6. The C player belongs in CI

A full LVGL + ThorVG build takes 9 seconds with nothing but gcc. That was the
practical objection to §3.7's "one evaluator, not two", and it does not hold:
the device's C sources can be compiled and tested on every push, which turns R6
(easing diverging between C and Python) from a discipline problem into a
build-time one.

## C7. What this does not say

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

## C8. Next step

Promote the probe into the player: `scene_json.c`, `evaluator.c` and
`render_lvgl.c` as C sources shared with the future ESP-IDF build, exposed as a
shared library, with a renderer seam in `ParticipantCore` so a simulated node
can run the C player instead of the Python reference. The existing scenarios
then run unchanged with one node on each renderer, and the C4 comparison becomes
a standing check rather than a one-off measurement.
