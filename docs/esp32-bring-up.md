# ESP32-S3 bring-up — the plan

* Date: 2026-09-12
* Status: plan. **No board has been touched.** Every number below is either
  measured on the host or arithmetic; none of it is a hardware result.
* Relates to: [decision 0014](decisions/0014-panels-are-clients.md),
  implementation plan §0.2 (the device track), `poc/firmware/mementum_lcd/`

The whole project has been built so that this step is small: the evaluator, the
renderer, the scene loader and the schedule are portable C that the host suite
exercises, and the protocol is exercised end to end over real sockets by the
Python client. What is left is a toolchain, a display driver and memory — and
those are exactly the things that cannot be answered from here.

## Two paths, and why both

| | Arduino | ESP-IDF (native) |
|---|---|---|
| For | first light, fastest path to a picture on glass | the shipping firmware |
| Precedent | `mementum-led`'s `http_controller` runs this way | LVGL ships `idf_component.yml`; it *is* an IDF component |
| Build | IDE or `arduino-cli`, sources flat in the sketch folder | CMake, components, `sdkconfig` |
| Config | `lv_conf.h` in the sketch folder | `menuconfig`, or the same `lv_conf.h` |
| Networking | `WiFi.h` + `HTTPClient` + `WebServer` | `esp_wifi` + `esp_http_client` + `esp_http_server` |
| What breaks first | library versions, PSRAM flags | nothing familiar; everything explicit |

They are not alternatives in sequence — Arduino first because a wrong display
driver is cheaper to find there, IDF second because a product is not shipped
from an IDE. **The C in `poc/player/` is identical in both**, which is the point
of having kept it dependency-free: `link.sh` symlinks it for Arduino, and an
IDF `CMakeLists.txt` lists the same files.

## What has to be true before either path starts

1. **A board.** ESP32-S3 with **PSRAM** (octal preferred) and an LCD LVGL can
   drive. PSRAM is not optional — see the budget below.
2. **`tools/fetch-lvgl.sh` pinned at v9.5.0**, with `patches/` applied. The
   device build uses the same checkout the host does, so a version skew cannot
   put the two renderers on different LVGL.
3. **A scene to show.** `poc/scenes/three-strokes.json` (240×120, one path) is
   the bring-up scene: small enough to rule memory out of an early failure.

## Memory, in advance

Measured on the host with `sizeof`, so the arithmetic is real even though the
board is not:

| | bytes | note |
|---|---|---|
| `mm_scene_t` | 19 480 | fixed arrays: 32 objects, 32 animations, 8 layers |
| `mm_path_t` | **75 016** | **per path object**, `calloc`ed at load |
| `du-kannst.json` | 8 129 | the scene document itself |
| canvas 450×250 ARGB8888 | 450 000 | `LV_COLOR_DEPTH 32` |
| canvas 450×250 RGB565 | 225 000 | `LV_COLOR_DEPTH 16` |

A six-path scene is therefore **~450 KB of parsed geometry** before a pixel is
drawn, and ~900 KB with a 32-bit canvas. The S3's internal SRAM is 512 KB and
some of it is LVGL's and the network stack's, so:

* **PSRAM is mandatory**, and the scene and canvas belong there
  (`ps_malloc`, `MALLOC_CAP_SPIRAM`).
* **Right-sizing `mm_path_t` is a bring-up task, not a later tidy.** The step
  report has it as "now" for a reason: 75 KB per object is fixed arrays sized
  for a worst case (64 subpaths × 48 segments) that a real scene does not reach.
  Content that needs 11.5 KB currently costs 75 KB.
* **Colour depth is a decision to take with a measurement.** 32-bit is what the
  host renders and what layer alpha needs; a single-scene panel with an opaque
  background may not need alpha at all, and 16-bit halves both memory and
  PSRAM bandwidth. Decide it on the board, against a frame time.

## Path A — Arduino, to first light

Scaffolding: `poc/firmware/mementum_lcd/` — `build.sh` (arduino-cli with the
board flags that matter: PSRAM on, `huge_app` so ThorVG fits), `lv_conf.h`, and
`link.sh` for the shared C.

```
A1  toolchain      arduino-cli or the IDE; ESP32 core installed; board boots Blink
A2  display        the board's LCD driver alone: a red screen, then a white one
A3  lvgl           LVGL 9.5 as a library, lv_conf.h from poc/host-player/,
                   PSRAM enabled; a filled lv_obj on the panel
A4  vector         LV_USE_VECTOR_GRAPHIC + THORVG: one lv_draw_vector line,
                   no mementum code at all
A5  player         sh link.sh; parse three-strokes.json; mm_evaluate + render
                   at a fixed scene time; the picture matches the host's
A6  clock+net      mm_net_begin(): register, /time, heartbeat, /play
A7  show           run the guide from the control server; one panel
```

Each step's gate is that the step before it is not in question. A4 is the one
that can fail in a way nothing else can rescue: **ThorVG is 2.3 MB of C++**, and
if it will not build or will not fit, the vector path on this board is over and
the fallback is LVGL's own `lv_draw_arc`/line primitives with a much poorer
stroke model. Finding that out at A4, before any mementum code is involved, is
the whole reason the steps are in this order.

## Path B — ESP-IDF, the shipping firmware

Scaffolding: `poc/firmware/idf/` — `setup.sh`, a component that *lists* the
player's C rather than copying it, `sdkconfig.defaults` carrying the memory
arithmetic, a 3 MB app partition, and a `main.c` that draws one embedded scene
and reports what each frame cost. B1–B4 are `./setup.sh && idf.py build`.

```
B1  project        idf.py create-project; LVGL as a managed component
                   (idf_component.yml is already in the checkout)
B2  config         sdkconfig: PSRAM octal, flash size, LVGL via menuconfig or
                   the same lv_conf.h; CONFIG_FREERTOS_HZ for the tick
B3  component      components/mementum_player/CMakeLists.txt listing
                   poc/player/*.c -- the same files, no copy
B4  display        esp_lcd panel driver; LVGL display driver bound to it
B5  net            esp_wifi + esp_http_client (register/heartbeat/time/scene)
                   + esp_http_server (/play /ripple /clear /status)
B6  parity         the same scene at the same scene time as the host, compared
                   by frame hash
B7  two units      two boards, one server, the skew measurement
```

B5 is a rewrite of `net.cpp` against IDF APIs rather than Arduino ones — about
300 lines, and the only firmware code that is not shared. Everything it drives
(`mm_schedule_*`) is already tested on the host.

## What to measure, once it runs

The project has deferred every hardware number on purpose. These are the ones
that decide things:

| | how | decides |
|---|---|---|
| frame time, by scene | `esp_timer` around evaluate + render | whether 30 fps holds, and at which colour depth |
| free heap / PSRAM | `/status` already reports `ESP.getFreeHeap()` | how many path objects fit; whether right-sizing is enough |
| scene fetch time | `/play` arrival → `loaded` | whether `DISPLAY_LEAD_MS` is big enough on real Wi-Fi |
| clock offset and RTT | already computed in `sync_clock()` | the clock model, on a radio rather than a queue |
| **two-unit skew** | both panels, one scene, a camera at 240 fps | the gate the whole design exists to satisfy (§0.4) |
| dropped frames | frames presented vs. expected over a minute | whether "a dropped frame self-corrects" survives contact |

The first four are self-reported and can be read from `/status` and the server
log without instrumentation. The fifth needs a camera and two boards, and it is
the only one that cannot be faked.

## Risks, in the order they are likely to bite

1. **ThorVG on Xtensa.** C++, float-heavy, 2.3 MB of source. Unknown build,
   unknown footprint, unknown speed. Gate A4 exists to find out early.
2. **PSRAM bandwidth.** The canvas and the parsed geometry both live there; an
   ARGB8888 450×250 canvas is 450 KB touched per frame.
3. **`mm_path_t` at 75 KB an object.** Right-size before believing any memory
   result — six paths is 450 KB of mostly zeroes today.
4. **The display driver.** Every board is different and none of this is
   portable. It is why Path A exists.
5. **Wi-Fi timing.** `DISPLAY_LEAD_MS` is 2000 ms by design and 250 ms in the
   demos; the real number comes from measured fan-out on an AP with a dozen
   panels on it, not from a guess.

## What this plan does not cover

Touch input on the panel (the routes exist; the controller does not), OTA
update, the enclosure, power, and how a panel is told where it stands — `x`/`y`
are in the sketch's `CONFIG` today, which is fine for two boards and not for
sixteen.
