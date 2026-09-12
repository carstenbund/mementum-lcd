# 0015 — MicroPython is a binding, not a third player

* Status: proposed — the architecture is decided, the hardware is not
* Date: 2026-09-12
* Relates to: [decision 0011](0011-one-stack-two-devices.md) (one stack, two
  devices), [decision 0014](0014-panels-are-clients.md) (a panel is a client),
  `docs/pico-bring-up.md`, `docs/esp32-bring-up.md`

## Context

There are two device classes today: a Linux node running CPython over the C
player through ctypes, and an ESP32-S3 running that same C with no Python at
all. An RP2040/RP2350 board is interesting as a third, because MicroPython is a
first-party runtime on the Pico line and because a small board that can be
*scripted* is a different proposition from one that has to be reflashed.

The obvious framing is the wrong one:

    Python reference  ─┐
    MicroPython player ├── three implementations of the same semantics
    C player          ─┘

That recreates precisely the parity problem the portable C player was written to
end. Two evaluators were already one too many; the conformance suite exists
because agreement between implementations has to be *checked*, and a third would
double that work to buy nothing.

## Decision

**MicroPython is a third binding to the existing C player, not a third player.**

    MicroPython
        ├── networking, the client protocol
        ├── choreography, scene selection
        ├── sensors and interaction
        └── native module ─→ mm_player_* / mm_screen_* ─→ LVGL/ThorVG ─→ LCD

This is not a new arrangement. It is what `mementum_node/players/lvgl.py`
already is on Linux — Python as the control language over the same C — with
ctypes replaced by a MicroPython C user module (`USER_C_MODULES`, which the
`rp2` port supports). Python gains a device class; the renderer gains nothing to
disagree with.

### Three consequences that follow, and one refusal

* **`lv_micropython` is not a dependency.** LVGL stays inside our C, and what
  is exposed to Python is our own small surface — place a scene, render, ripple.
  Importing LVGL's API into MicroPython would mean a second renderer front-end
  to keep in step with the first, and would make the tier depend on how well
  that binding currently supports a given chip. Declining the dependency is
  cheaper than verifying it.

* **The device Python is not this repository's Python.** `mementum_node/client/`
  uses `threading`, `http.server`, `urllib.parse` and `argparse`, and the core
  is `dataclasses` with `from __future__ import annotations` throughout.
  MicroPython has none of that, and bending the core to suit it would cost the
  Linux code its clarity to serve the smallest target. The precedent is the C
  player again: it shares no *code* with the Python reference, it shares the
  *contract*. So a Pico client is a few hundred hand-written lines speaking the
  same HTTP protocol and loading the same scene documents, and the conformance
  suite is what holds it honest.

* **Python's job on a panel is what Python is good at.** Network, local
  choreography, sensors, which scene to show. Not parsing, not evaluating, not
  geometry, and certainly not pixels — those are measured, shared, and already
  identical on two architectures.

* **The refusal:** no scene semantics may be implemented in MicroPython. If a
  behaviour needs the renderer to do something new, it goes into the C and into
  both players, as every deformation has.

## What decided the memory question

The Pico-class case was hopeless until this week for a reason that had nothing
to do with Python: `mm_path_t` held fixed arrays for the worst case, so a path
cost 75 016 bytes whatever it contained and a six-path scene was 450 KB. A
stock Pico 2 W has 520 KB of SRAM, no PSRAM, and MicroPython wants a heap out of
the same pool.

Right-sizing (commit *"A path costs what its content needs"*) makes the
geometry a rounding error — 14.5 KB for the whole writing scene, 344 bytes for
the signature. What remains is the canvas, which is arithmetic rather than
speculation: 150 KB for 320×240 at 16 bits, 225 KB at 450×250, double either at
32 bits. That is now the whole question, and it is the same question on the
ESP32.

So this tier did not need a new argument; it needed a fix the ESP32 already
owed, and being a second caller for it is the most useful thing about it.

## Status, honestly

**Proposed, not supported.** What is decided is the shape: a binding, not a
player; our C, not `lv_micropython`; a protocol client, not a port. What is not
decided is whether an RP2350 can hold a canvas, whether LVGL and ThorVG build
for Cortex-M33 at a usable speed, and whether a board without PSRAM can be made
to work by drawing in bands — which the player cannot do today, since
`mm_render_scene` draws into one layer.

`docs/pico-bring-up.md` names the smallest experiment that would answer the
first of those without a display driver, a PSRAM board, or any Python at all.
Until that returns a number, this document is a decision about naming and
layering, and nothing is claimed about hardware.
