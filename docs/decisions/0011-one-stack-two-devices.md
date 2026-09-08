# 0011 — One stack, from an ESP32 to a Pi

* Status: accepted
* Date: 2026-09-08
* Relates to: [decision 0009](0009-vector-painter-ports-back.md),
  [decision 0010](0010-drm-screen-on-lvgl.md), `drm_stack` Stage 4b,
  plan §14 (node implementations), §3.7 (the player as a library)

## Context

Decision 0010 implemented `drm_screen`'s API on LVGL, inside this repository.
That was the right place to find out whether it worked. It is the wrong place
for it to live: a second implementation of somebody else's API, in a project
that is not that API's home, is a fork with good manners.

The work has gone upstream:

| | |
|---|---|
| [`drm_screen`](https://github.com/carstenbund/drm_screen) | the renderer seam, `PlaceScene`, `SetOpacity`, `UnsupportedCommand` |
| [`drm_screen_lvgl`](https://github.com/carstenbund/drm_screen_lvgl) | the LVGL renderer plugin — the binding that used to be `mementum_node/screen/lvgl.py` |
| [`drm_composer`](https://github.com/carstenbund/drm_composer) | `<path>`, `<animate>`, and a layer that compiles to a scene document |
| [`drm_stack`](https://github.com/carstenbund/drm_stack) | Stage 4b, and the integration test where the two renderers meet |

## Decision

**This repository consumes the stack; it does not shadow it.**

`mementum_node/screen/` is now an adapter, not an implementation:

* `screen_service()` returns `drm_screen.ScreenService` where that package is
  installed, and a stdlib-only loop (`SimpleScreenService`) where it is not,
  because `drm_screen` needs numpy and `drm_display` and a node is allowed to
  be a machine with neither. The renderer is the same object in both, so the
  picture is the same either way — checked, not assumed.
* `Screen` adds one thing to the plugin's screen: a frame is a
  `core.framebuffer.Frame`, so the capture, PNG and comparison tools that work
  on a rendered player frame work on a screen.
* `commands.py` re-exports `drm_screen`'s records where they exist and mirrors
  them where they do not. `StartRipple` stays here: a wave running along a
  stroke because somebody touched the glass is this project's idea of what a
  screen is for, not `drm_screen`'s.

**The C stays.** `poc/player/` is the home of the evaluator, the renderer and
`screen.c`; the plugin binds it, and `make -C poc/host-player lib` now also
leaves `libdrm_screen_lvgl.so` beside it under the name the plugin looks for
first. It moves out when `drm_scene_ir` is versioned and has a conformance
suite of its own — not before.

## What this makes true

The same stack now reaches both ends of the hardware:

```
authoring        screen-HTML                     (a host, Python)
compile          drm_composer -> drm_scene_ir    (a host, Python)
                     |
       +-------------+-------------+
       |                           |
 Pi / Linux node             ESP32-S3 panel
 drm_screen + plugin         poc/player/, ESP-IDF
 layers as LVGL objects      the same C, no Python at all
 presented to DRM/KMS        presented to the panel
```

The command vocabulary exists at both ends in two syntaxes that mean the same
thing — `CreateLayer`/`PlaceScene` as Python records, `mm_screen_layer_create`/
`mm_screen_layer_scene` as C calls — and the C is the same C in both columns.

**The composer therefore already targets the ESP32.** It does not have to run
there: it compiles on a host and ships a document of a couple of kilobytes,
which the device player loads. `tests/test_composer_to_device.py` feeds
`drm_composer`'s emitted bytes straight to the C player and watches the stroke
draw itself. That is the whole boundary — Python above the wire, C below it,
`drm_scene_ir` across it.

A bitmap layer cannot cross that boundary at frame rate and never could. A
scene layer can, which is why `PlaceScene` was the one command worth adding.

## Consequences

* ~500 lines left this repository. What remains in `mementum_node/screen/` is
  what is genuinely this project's.
* A change to the layer model is now a change upstream, reviewed there, with
  the umbrella's integration tests as the regression net.
* `requirements-dev.txt` gains the plugin (from git, zero dependencies) and
  `drm_screen` as optional.
* Still open: the scene layer drawing straight to the display layer;
  `<symbol src="…svg">` and a converter for it; transforms and deformations in
  markup; `drm_scene_ir` as its own versioned repository with the conformance
  suite both players pass.
