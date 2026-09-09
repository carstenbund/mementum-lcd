# mementum panel — ESP32-S3 firmware

The sibling of [`mementum-led`](https://github.com/carstenbund/mementum-led)'s
`http_controller` sketch, for a panel that draws scenes instead of scrolling a
string. Same flow, same protocol, same server.

```
connect  ->  /register  ->  adopt the id the server gives us
             /time      ->  Cristian's algorithm, best of three round trips
             /heartbeat ->  every few seconds; carries the running schedule
serve        /play /ripple /clear /status   so the server can push
every frame  scene_time = serverNow() - displayAt
```

## What is shared, and why

Nothing here re-implements the player. `link.sh` symlinks the C from
`poc/player/` into the sketch folder, because the Arduino IDE compiles what it
finds there and because a copy is a second evaluator waiting to happen:

| file | what it does | tested |
|---|---|---|
| `scene_json.c` | the scene document → the model | host suite |
| `evaluator.c` | animations → object state at a time | host suite, against the Python reference to 8×10⁻⁸ |
| `geometry.c` | paths, lengths, deformations | host suite |
| `render_lvgl.c` | model → LVGL/ThorVG | host suite, byte-identical frames |
| `ripple.c` | transient local excitement | host suite |
| `schedule.c` | what this panel has been told to show | `tests/test_device_schedule.py` |

Only `net.cpp` and the sketch itself are device-only, and they are thin on
purpose: registration, heartbeat, the clock, four routes and a fetch.

## What is not verified

**This has not been compiled or run on hardware.** There is no ESP32 toolchain
in this repository and no board yet; the sketch is written against the LED
firmware's proven structure and this project's tested C, and that is a
different thing from working. Expect the first bring-up to be about the display
driver (`display_init()` is deliberately a stub with the board-specific part
marked), PSRAM, and LVGL's config.

The parts that *can* be checked without a board are checked: the schedule logic
these routes drive is `poc/player/schedule.c`, exercised from the host suite,
and the whole protocol is exercised end-to-end over real sockets in
`tests/test_client_server.py` by the Python node — which speaks exactly what
this firmware speaks.

## Build

1. `sh link.sh` — symlink the shared C (re-run after adding a source).
2. Arduino IDE, ESP32-S3 board, **PSRAM enabled** — a scene is kilobytes and
   belongs there rather than on the internal heap.
3. Libraries: **LVGL 9.5** with `LV_USE_VECTOR_GRAPHIC`, `LV_USE_THORVG_INTERNAL`,
   `LV_USE_FLOAT` and `LV_USE_MATRIX` (see `poc/host-player/lv_conf.h` for the
   set the host build uses), plus the display driver for the panel.
4. Edit `CONFIG` at the top of the sketch: SSID, server address, and **where
   this panel stands** — `x`/`y` in metres, which is what lets a touch travel
   across the wall at a speed rather than arriving everywhere at once.

## No server mode

The LED firmware can elect itself the soft-AP server. This one cannot, and that
is a decision rather than an omission: the server distributes *scenes*, and a
panel with a few megabytes cannot hold the library a show draws from. A device
that must also serve would run `mementum_node.server` on something with a disk.
