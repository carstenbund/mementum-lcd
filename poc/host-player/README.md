# Host player — LVGL/ThorVG on Linux

Implementation plan §3.7 and Phase 0 task 0.3 steps 1–3, done on the desktop
while hardware is on order. Nothing here needs a board, a panel, cmake, SDL or
a window: the player renders into a memory framebuffer, which is the same thing
the ESP32 build does one layer lower and exactly what the simulator can hash and
diff.

## Building

```bash
./fetch-lvgl.sh                 # pinned LVGL v9.5.0; ThorVG ships inside it
./fetch-cjson.sh                # pinned cJSON, the parser ESP-IDF also ships
make -j4                        # ~530 objects, about 10 seconds
```

`make lib` builds `libmementum_player.so` — the player itself; `make probe` and
`make subpath` build the two experiments.

The only tools required are `gcc`, `g++` and `make`. LVGL is configured by
[`lv_conf.h`](lv_conf.h): 32-bit colour, software renderer, one draw unit
(determinism before throughput), vector graphics and ThorVG on, everything else
off so a build failure means something.

## The probe

```bash
../../.venv/bin/python probe_report.py sim-out/probe
```

`probe_vector.c` renders the `poc-signature` path at five progress values and
dumps raw RGBA; `probe_report.py` turns those into PNGs and compares them
against the Python reference renderer.

It exists to answer two questions with numbers:

* **R1 — runtime stroke progress.** The reveal is a dash pattern of
  `[length·p, length]` over a path whose arc length we precompute ourselves,
  because neither LVGL nor ThorVG exposes a path-length query. Result: lit
  pixels track progress to within 1% of the expected fraction, so `progress`
  can stay a runtime property in the IR rather than becoming a compile-time
  slice. See [`../../docs/decisions/0004-stroke-progress.md`](../../docs/decisions/0004-stroke-progress.md).
* **Open question 7 — cross-renderer agreement.** 1.19% of pixels differ
  between this and the Python reference, all of them at stroke edges, while ink
  mass agrees to 0.76% and the ink centroid to 0.1 px. Same geometry, different
  antialiasing — which is what a perceptual tolerance is for, and why golden
  frames may only be compared exactly between *identical* renderers.

## What this is not, yet

The probe is a hand-transcribed path, not the player. Still to come: the JSON
loader, the evaluator and the renderer as C sources shared with the ESP-IDF
build, exposed as a shared library so a simulated node can run this instead of
the Python reference renderer — the point being that the simulator stays around
it, unchanged.

## What the host build needs

gcc, and **libdrm's headers** (`libdrm-dev` on Debian and Ubuntu). `lv_conf.h`
enables `LV_USE_LINUX_DRM`, so `lvgl.h` pulls in the DRM driver's header and
anything that includes it needs `xf86drmMode.h` -- not only the `drm_player`
target. cJSON and LVGL are fetched by the scripts here.
