# 0010 — `drm_screen`, implemented on LVGL

* Status: accepted — superseded in placement by [0011](0011-one-stack-two-devices.md), which moved this code upstream
* Date: 2026-09-08
* Relates to: [decision 0009](0009-vector-painter-ports-back.md),
  `drm_screen`'s command API, `drm_display`, plan §3.7 (the player as a library)

## Context

Decision 0009 said the vector renderer is an extension of `drm_stack`, not a
departure, and that LVGL replaces the painter rather than the compositor. The
DRM run since then went further than expected: LVGL can stand where
`drm_display` stands — 1.5 ms to fill 1920×1080 from a 1.4 KB scene, straight
to a scanout plane, with no bitmap transported and no colour conversion on the
way.

That raises a question the earlier decision left open. If LVGL can composite
and present, what is left for `drm_screen` to do? The tempting answer is "less",
and it is the wrong one. `drm_screen`'s value was never in its numpy blend; it
is in the **vocabulary**: named persistent layers, z-order, visibility,
opacity, hit-testing, `submit()` a batch of records that survive a socket hop.
That vocabulary is already in use, already documented, and already what
`drm_composer` targets.

## Decision

Keep the words. Change what is under them.

`mementum_node/screen/` is `drm_screen`'s API with LVGL underneath. The command
records are `drm_screen.commands`' own classes when the package is installed,
and field-for-field copies where it is not; `apply_command` dispatches by class
name so a batch built by either applies to either. `submit`, `hit_test`,
`render_once`, `start`, `stop` and the dirty flag mean what they meant.

    drm_screen   commands -> numpy layers -> full-frame blend -> RGBA→BGRA
                          -> drm_display -> DRM/KMS
    this         commands -> LVGL objects -> LVGL's dirty-area composite
                          -> DRM/KMS

One command is an addition, and it is the reason for the exercise:

    PlaceScene(name, scene)   the layer holds a scene, not pixels

A layer given a scene is drawn from paths, at the panel's resolution, every
frame. Nothing about it is ever rasterised into a transported buffer. The other
two additions — `SetOpacity` and `StartRipple` — are small: per-layer alpha
after creation, and local excitement on a scene layer, so a finger on the glass
reaches the thing it touched.

`LvglBackend` covers the other direction: keep `drm_screen` exactly as it is
and give it LVGL as its display backend. That path still pushes whole frames
and buys nothing but portability. It exists because "no code change" has to
mean no code change.

## What is checked

* The same batch — `drm_screen`'s own records — gives a **byte-identical**
  frame from its numpy composer and from LVGL.
* A scene on a layer draws the frame the device player draws for that scene,
  byte for byte, so the primitive path is a substitution and not a second
  renderer.
* Layer geometry, z, visibility, opacity, blit clipping and hit-testing behave
  as `drm_screen` documents them.
* `drm_screen.ScreenService(LvglBackend())` runs unmodified.

`tests/test_lvgl_screen.py`, skipped where the C library is not built.

## Cost

Layering is not free. The scene layer is a full-screen ARGB8888 canvas that is
then composited onto the root, so at 1920×1080 the demo costs 3.1 ms per frame
against 1.5 ms for the player drawing straight to the display. That is the
price of the layer model, not of LVGL, and it is recoverable: a scene layer
that covers the screen and has nothing under it can draw into the display's
own layer instead of through a canvas. Not done yet, and not needed at 320 fps.

## Consequences

* A node keeps its screen code. What changes is which screen it constructs.
* Where LVGL is missing, `drm_screen` is still the screen — same commands, RGBA
  all the way down, as decision 0009 already provided for.
* `PlaceScene` is the seam through which `drm_composer` output can reach a
  panel as primitives. It belongs upstream once it settles, alongside the
  `<animate>` element.
