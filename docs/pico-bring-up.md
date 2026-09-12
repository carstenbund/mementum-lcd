# Pico bring-up — a scripted panel

The third device class from [decision 0015](decisions/0015-scripted-microcontroller.md):
an RP2040/RP2350 board running **MicroPython as the control language** over the
same C player, with no second renderer and no second evaluator. Python does
network, choreography and sensors; C parses, evaluates and draws.

This document is the ESP32 one's sibling and follows its discipline: the
arithmetic first, then the smallest experiment that a compiler or a board can
settle, then what would disqualify the idea. Nothing here has met hardware.

## Why it is worth an experiment

* A board that can be **scripted** is a different instrument from one that has
  to be reflashed. An installation's behaviour — which scene, on what cue, in
  response to what sensor — is exactly the kind of thing worth editing in place.
* It proves the Python/C boundary can live **inside** a microcontroller rather
  than only across the network between an authoring host and a mute client.
* It costs the renderer nothing: the same `mm_player_*` and `mm_screen_*` that
  Linux and the S3 already call.

## Memory, in advance

Measured with `mm_path_bytes` on this repository's scenes, on the host, so the
arithmetic is real even though the board is not:

| | bytes |
|---|---|
| `mm_scene_t` | 19 480 |
| parsed geometry, `three-strokes` | 192 |
| parsed geometry, `poc-signature` | 344 |
| parsed geometry, `du-kannst` (six handwritten words) | 14 512 |
| `mm_path_scratch_t`, transient at load | 75 792 |
| canvas 320×240 RGB565 | 153 600 |
| canvas 320×240 ARGB8888 | 307 200 |
| canvas 450×250 RGB565 | 225 000 |

Against a **stock Pico 2 / Pico 2 W: 520 KB SRAM, no PSRAM**, shared with
MicroPython's own heap and with lwIP if the board is on a network.

What that says:

* **The geometry is no longer the problem.** Before right-sizing, six paths was
  450 KB and the question was closed. At 14.5 KB it is not worth discussing.
* **The canvas is the problem, and colour depth is the lever.** 320×240 at 16
  bits is 150 KB and leaves room for MicroPython; the same panel at 32 bits does
  not. A 450×250 panel at 16 bits is 225 KB, which is tight, and at 32 bits is
  out of the question without PSRAM.
* **The transient scratch is 75 KB and it matters here.** It is freed before
  `mm_path_create` returns, but the peak at load is one scratch plus everything
  already resident. On a 520 KB board that is worth remembering when a scene
  with several paths is loaded on a fragmented heap; it may have to shrink, or
  become a single reused buffer for the whole load, before this works.
* **A board with PSRAM changes the exercise.** RP2350 boards exist with 8 MB of
  external PSRAM (Pico Plus 2 and similar), which would put this class in the
  same position as an S3 — *unverified*, and the first thing to check on an
  actual board rather than a datasheet.

## The experiment, in the order that answers most per hour

### 1. Does the renderer fit? (no display, no Python needed)

Build MicroPython for `rp2` with the player as a `USER_C_MODULES` user module,
no display driver at all, and from the REPL:

```python
import mementum, gc
gc.collect(); before = gc.mem_free()
p = mementum.load(open("du-kannst.json", "rb").read(), 320, 240)
gc.collect(); print("scene:", before - gc.mem_free())
p.render(8000)                      # into a memory buffer, nothing displayed
gc.collect(); print("after a frame:", before - gc.mem_free())
print("frame ms:", p.last_render_ms)
```

That settles the only question that can kill the idea outright, and it needs no
display driver, no PSRAM, and none of `lvgl_micropython`. It also produces the
first real frame time for Cortex-M33, which no compiler can give.

### 2. Does LVGL/ThorVG build for Cortex-M33 at all, and at what size?

ThorVG is 565 KB of `.text` on Xtensa. Pico 2 has 4 MB of flash, so size is
probably not the obstacle; single-precision FPU behaviour and any double-math in
ThorVG are the things to watch, exactly as the Xtensa build turned up a header
reaching the assembler and a missing `<string.h>`. Expect the toolchain to find
something the other two did not — that has happened every time.

### 3. A display, then a client

Only once 1 and 2 return numbers. The client is a few hundred hand-written lines
of MicroPython speaking the HTTP protocol the control server already serves
(`docs/decisions/0013`, `0014`) — not a port of `mementum_node/client/`, which
needs `threading`, `http.server`, `urllib.parse` and `dataclasses`, none of
which MicroPython has.

## What would disqualify it

* A frame time so long that a scene cannot animate — the renderer is software
  rasterisation of vector paths, and RP2350 is not fast.
* A canvas that will not fit alongside MicroPython on a no-PSRAM board, with no
  acceptable panel size or colour depth. Banded rendering would be the answer,
  and the player cannot do it today: `mm_render_scene` draws into one layer.
* ThorVG needing more working memory at runtime than the board has, which is
  not visible in a `sizeof` and only shows up on hardware.

Any of those is a fine outcome. It would make the tier "RP2350 with PSRAM" or
"not this chip", which is still worth knowing, and the fix that made the
question askable — packing paths to their content — was owed to the ESP32
regardless.

## Status

| | |
|---|---|
| decided | the layering: a binding, our C, a protocol client |
| measured | the geometry budget, on the host |
| unproven | everything about the board, the canvas, and the frame time |
| not started | the user module, the display driver, the MicroPython client |
