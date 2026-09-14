# Board headers

One file per physical board, so the sketch itself never changes when the
panel does. Everything that is *this PCB's business* — bus type, pins,
controller chip, rotation, backlight polarity — lives here. Everything that
is *the picture's business* lives in `mementum_lcd.ino` and never needs to
know which board it is talking to.

## The contract

A board header must provide:

| what | shape |
|---|---|
| `PANEL_WIDTH`, `PANEL_HEIGHT` | `#define`, pixels, in the panel's natural (rotated) orientation |
| `board_gfx_new()` | inline function returning a ready, `begin()`-able `Arduino_GFX *` — bus and display object both constructed |
| `board_backlight_on()` | inline function that turns the backlight on (a GPIO write, PWM, or nothing, as the board needs) |

`mementum_lcd.ino` calls exactly these three names and nothing else from a
board header — no board's pin macros leak into the shared code, so two
boards can define `PIN_LCD_CS` differently without colliding, and a board
using a parallel RGB bus rather than SPI needs no changes outside its own
file.

## Switching boards

Edit `../board_config.h` — uncomment the board you want, comment out the
rest — **and** set `build.sh`'s `FQBN`/`OPTS` to match (see the table
below; they differ per chip, not just per panel).

## Adding a board

Copy `template.h`, fill in the three names above, add it to the table here
and to `../board_config.h`. Nothing else in the sketch changes.

## What is here

| file | board | chip | bus | controller | PSRAM | confidence |
|---|---|---|---|---|---|---|
| `guition_jc3248w535.h` | Guition JC3248W535 (most likely diymore "ESP32-S3 3.5 inch Capacitive Touch LCD" — check the back for "JC3248W535") | ESP32-S3, Xtensa, 16 MB flash | QSPI | AXS15231B, 320x480, touch in the same chip (I2C 0x3B, not wired up) | yes, 8 MB octal | pins from GFX Library for Arduino's own JC3248W535 example, matching F1ATB and the ESPHome config; **not confirmed on a board in hand**. Needs the 320x480 type1 init sequence passed explicitly (GFX 1.6.1+); built against GFX 1.6.7 |
| `sunton_esp32_3248s035.h` | Sunton/JC ESP32-3248S035 "Cheap Yellow Display" family | **classic ESP32 (WROOM-32), Xtensa LX6**, 4 MB flash | 4-wire SPI | ST7796, 480x320 | usually **none** — check the module | pins are this family's community-documented set. Not an S3 board: GPIO 27 is flash/PSRAM on an S3 |
| `waveshare_esp32s3_lcd_147.h` | Waveshare ESP32-S3-LCD-1.47, and rev **1.47B** (diymore "1.47 Inch LCD Screen Development Board" is the B: adds QMI8658 IMU and Li-ion charging) | ESP32-S3R8, Xtensa, 16 MB flash | 4-wire SPI | ST7789, 172x320 (34-column offset) | yes, 8 MB, in package | pins are Waveshare's published table for the non-B board; B is reported to keep them, unconfirmed |
| `waveshare_esp32c6_lcd_13.h` | Waveshare ESP32-C6-LCD-1.3 (diymore "ESP32-C6 1.3 inch OLED", which mislabels the panel — it is a colour IPS LCD) | **ESP32-C6, RISC-V** | 4-wire SPI | ST7789V2, 240x240 | **none — the chip has no PSRAM interface at all** | pins read directly off Waveshare's schematic; the chip itself carries two open risks the other two boards don't (see the header) |
| `template.h` | — | — | — | — | — | a documented skeleton, not a working board |

The C6 board is the odd one out: right pins, unproven architecture. Nothing
in this repository's CI has ever built ThorVG for RISC-V, and the chip's
320 KB of total SRAM (no PSRAM to hand the canvas to) is the tightest
memory budget any board here has been asked to fit — see the header comment
before spending time on it.

## Per-board build settings

`build.sh` reads `FQBN`/`OPTS` from the environment; nothing in
`board_config.h` sets them, so set them yourself to match whichever board
you picked:

```bash
# guition_jc3248w535.h
FQBN=esp32:esp32:esp32s3 OPTS=PSRAM=opi,PartitionScheme=huge_app,FlashSize=16M,CPUFreq=240,USBMode=hwcdc,CDCOnBoot=cdc ./build.sh /dev/ttyACM0

# waveshare_esp32s3_lcd_147.h (1.47 and 1.47B)
FQBN=esp32:esp32:esp32s3 OPTS=PSRAM=opi,PartitionScheme=huge_app,FlashSize=16M,CPUFreq=240,USBMode=hwcdc ./build.sh /dev/ttyACM0

# sunton_esp32_3248s035.h — classic ESP32; add PSRAM=enabled only if the module has it
FQBN=esp32:esp32:esp32 OPTS=PartitionScheme=huge_app,FlashSize=4M,CPUFreq=240 ./build.sh /dev/ttyUSB0

# waveshare_esp32c6_lcd_13.h — no PSRAM flag, there is nothing for it to enable
FQBN=esp32:esp32:esp32c6 OPTS=PartitionScheme=huge_app,FlashSize=4M,CPUFreq=160,USBMode=hwcdc ./build.sh /dev/ttyACM0
```
