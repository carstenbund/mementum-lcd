# 0009 — The vector renderer is an extension of drm_stack, not a departure

* Status: accepted
* Date: 2026-09-08
* Relates to: `drm_composer` screen-HTML, the `drm_stack` roadmap,
  proposal §14 (node implementations), [decision 0005](0005-symbols-are-the-payload.md)

## Context

`drm_composer` compiles screen-HTML — `<screen>`, `<layer>`, `<box>`, `<text>`,
`<img>` at absolute coordinates — into `drm_screen` command batches, and
`drm_screen` composites RGBA planes. That model is right for what it was built
for, and it has no way to express a line that draws itself: by the time content
reaches the compositor it is pixels, and a stroke is not a thing that can be
half-finished.

LVGL with ThorVG gave this project a vector model instead — paths, strokes,
transforms, deformations, and a `progress` that means "how much of this stroke
has been drawn". Everything since has been built on that.

Read carelessly, that looks like starting a second project. It is not, and the
distinction matters for where the work should end up.

## Decision

The vector renderer is an **extension of the same stack**, and the pieces built
here are meant to move back into it:

* **The authoring language stays screen-HTML.** `<symbol>`, `<writing>` and the
  timeline element `<animate target= property= from= to= start= duration=
  easing= />` are additions to that language, in its own idiom, exactly as the
  implementation plan (§0b.1) specified. There is one composer language, not
  two. `tools/compose.py` is a prototype of that parser living in the wrong
  repository; it belongs in `drm_composer/parser.py`.

* **LVGL replaces the painter, not the compositor.** `drm_screen` composites
  RGBA planes and hands a frame to a backend adapter (§14). The C player
  produces exactly such a frame. So the integration is the seam that already
  exists — the player becomes a painter whose output is a plane — and invariant
  1 holds untouched: one colour conversion, in the backend adapter, nowhere
  else.

  **But that is the compatibility floor, not the target.** Handing over an RGBA
  buffer is what works on `/dev/fb` and on any unaccelerated surface. LVGL 9.5
  ships a dozen draw units — `opengles`, `nanovg`, `vg_lite`, `nema_gfx`,
  `dma2d`, the Espressif PPA, NXP PXP — and display drivers including
  `lv_linux_drm_egl.c`. Where acceleration exists it should be used, and the
  buffer round-trip skipped:

```text
  accelerated   scene IR -> LVGL (GL / VG-Lite / PPA) -> DRM+EGL, wayland, panel
  fallback      scene IR -> LVGL (sw) -> RGBA buffer -> drm_screen -> /dev/fb
```

  This is also where `drm_resvg` fits rather than competes: resvg as the SVG
  parser and geometry source, LVGL as the renderer that puts it on whatever
  hardware is present, instead of resvg rasterising to RGBA on the way past.

* **Scene IR is the contract the stack currently lacks.** `drm_screen` takes
  command batches, which are instructions rather than a description. Scene IR
  describes what should be on screen at a time, which is what lets the same
  content run on a Pi and an ESP32 and be checked for agreement.

## What this makes stronger, concretely

* A `drm_composer` screen can move without a video pipeline: the same file that
  lays out a kiosk gains a timeline.
* One player runs on both targets. The C sources here compile for the host
  today and for ESP-IDF next; a Pi running them is the "shared runtime"
  candidate §3.7 names, which removes a whole implementation rather than adding
  one.
* Determinism arrives with it: normative easing, declared path lengths, and a
  conformance suite that already holds two independent players to the same
  output.

## Acceleration costs determinism, and the suite already knows it

A node drawing through GL does not produce the same pixels as one drawing
through the software unit. Antialiasing differs, and so will the frames.

That is not a problem, because the distinction is already built and tested:
**byte-identical within a renderer family, the same picture across families.**
Acceleration simply means each draw-unit configuration is its own family. Two
GL nodes must still agree exactly with each other; a GL node and a software
node are compared on ink mass and centroid, as the Python reference and the C
player already are.

Two consequences follow, and both should be stated before anyone relies on the
old assumption:

* The **frame hash** of §3.6 — two devices agreeing by hashing their buffers —
  is valid only within a family. Across accelerated and unaccelerated nodes it
  will always differ, and reporting that as a fault would be wrong.
* `lv_conf.h` here sets `LV_DRAW_SW_DRAW_UNIT_CNT 1`, commented "determinism
  first". On an accelerated node that choice inverts, and the reason it was
  made — reproducible golden frames — has to be met by the aggregate metric
  instead.

## The open choice

The roadmap's stage 1 adds `drm_resvg` — SVG through Rust/resvg — which is also
a vector renderer. So the stack would have two candidates:

| | strengths | costs |
|---|---|---|
| `drm_resvg` | on the roadmap, Rust, SVG-native, correct | rasterises to RGBA itself; no timeline, no stroke progress |
| LVGL/ThorVG | timeline and progress proven here, a dozen accelerated back ends, runs on the ESP32 | C, and it is a UI toolkit doing a rendering job |

They are not exclusive, and the more interesting arrangement is not either/or:
resvg reads and normalises SVG, LVGL draws it through whatever the hardware
offers. That keeps resvg's correctness on the parsing side and puts acceleration
where it belongs, rather than having two renderers each rasterising to a buffer.
The decision is not taken here, but it should be taken as *how they compose*
rather than *which one wins*.

## Consequences

* The `<animate>` parser, the vector primitives and the scene IR should migrate
  to `drm_composer` and `drm_stack` rather than settling in `mementum-lcd`.
  Until they do, this repository holds a prototype of someone else's component.
* The roadmap has no animation, scene IR or ESP32 in it. If this direction is
  taken up, that document is where it should be said, so the stack has one
  future rather than two.
