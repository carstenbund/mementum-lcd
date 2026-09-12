# The panel, on ESP-IDF

Path B of [`docs/esp32-bring-up.md`](../../../docs/esp32-bring-up.md): the
shipping firmware's build. Path A (`../mementum_lcd/`) is the Arduino sketch and
is where a wrong display driver is cheapest to find.

```bash
./setup.sh                   # link the vendored LVGL (once)
idf.py set-target esp32s3
idf.py build                 # sdkconfig.defaults already sets what matters
idf.py -p /dev/ttyACM0 flash monitor
```

## What is here

| | |
|---|---|
| `components/mementum_player/` | the player's C, **listed not copied** — the same files the host suite compiles |
| `components/lvgl` | a symlink to `third_party/lvgl`, so the device builds the exact checkout the host was measured against, patches and all |
| `main/main.c` | steps B1–B4: parse one embedded scene, draw it at fixed scene times, report what each cost |
| `sdkconfig.defaults` | PSRAM, a 3 MB app partition, C++ without exceptions — the memory arithmetic, stated once |
| `partitions.csv` | ThorVG does not fit in the default 1.2 MB factory partition |

`main.c` does no networking on purpose. `mm_net_begin()` in the Arduino sketch
is the reference for step B5, and everything it drives (`mm_schedule_*`) is
already tested on the host — so the IDF port of it is about `esp_http_client`
and `esp_http_server`, not about the protocol.

## What it should print

```
mementum panel: LVGL 9.5.0
heap  boot: internal …, psram …
scene 43: 2 objects, 3.0s, parsed in … ms
frame t=  750 ms: evaluate+render … ms, present … ms
```

Those numbers are the point of the exercise. Nothing on the host can produce
them, and every open question about this board — whether ThorVG fits, whether
30 fps holds, whether 32-bit colour is affordable — is answered by reading
them and nothing else.

## If it does not build

The likely failure is ThorVG (2.3 MB of C++ headed for Xtensa), and the plan
puts a gate before this point for that reason: build LVGL with
`LV_USE_VECTOR_GRAPHIC` and draw one `lv_draw_vector` line with no mementum
code in the project at all. If that fails, this will too, and for a reason
that has nothing to do with anything in this repository.
