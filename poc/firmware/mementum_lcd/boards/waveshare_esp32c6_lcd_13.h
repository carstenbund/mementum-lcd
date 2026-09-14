/**
 * Waveshare ESP32-C6-LCD-1.3 — a 1.3", 240x240, ST7789V2-over-4-wire-SPI
 * panel on an ESP32-C6FH4. Sold rebranded by diymore among others.
 *
 * Pins below are read directly off Waveshare's own schematic
 * (ESP32C6-1.3.SchDoc, via files.waveshare.com/wiki/ESP32-C6-LCD-1.3/
 * ESP32C6-1.3.pdf) rather than a community guess or a demo sketch — as
 * confident a source as this folder has for wiring.
 *
 * What is NOT confident, and is new to this board rather than a pin
 * question:
 *
 *   - **RISC-V, not Xtensa.** The C6 is a single-core RISC-V part; every
 *     other board here is Xtensa LX7. docs/esp32-bring-up.md's CI result
 *     — "ThorVG compiles for Xtensa" — says nothing about this toolchain
 *     (riscv32-esp-elf-gcc). Whether LV_USE_THORVG_INTERNAL builds here
 *     at all is untested and could end the vector path on this board
 *     specifically, the way the plan always said it might on some board.
 *   - **No PSRAM.** Not "not populated" — the C6 silicon has no PSRAM
 *     interface. docs/esp32-bring-up.md's whole memory budget assumes the
 *     canvas lives in PSRAM ("PSRAM is not optional... for the canvas").
 *     Here the canvas, the parsed scene, LVGL and the Wi-Fi stack all
 *     compete for 320 KB of SRAM total. A 240x240 canvas is 225 KB at
 *     ARGB8888 (the project's host-parity default, and what
 *     `display_init()` in the sketch currently hardcodes) or 112 KB at
 *     RGB565 — the colour-depth choice the plan defers "until measured"
 *     is not really a choice on this board, it is close to the only
 *     option that leaves room for Wi-Fi and LVGL too.
 *
 * This header gets the panel correctly wired. Whether the rest of the
 * firmware fits on this chip is an open question it does not answer.
 *
 * Build with:
 *   FQBN=esp32:esp32:esp32c6
 *   OPTS=PartitionScheme=huge_app,FlashSize=4M,CPUFreq=160,USBMode=hwcdc
 *   (no PSRAM flag — there is nothing on this chip for it to enable)
 */
#ifndef MM_BOARD_WAVESHARE_ESP32C6_LCD_13_H
#define MM_BOARD_WAVESHARE_ESP32C6_LCD_13_H

#include <Arduino_GFX_Library.h>

#define PIN_LCD_SCK        7
#define PIN_LCD_MOSI       6
#define PIN_LCD_CS        14
#define PIN_LCD_DC        15
#define PIN_LCD_RST       21
#define PIN_LCD_BL        22
#define PIN_LCD_ROTATION   0

#define PANEL_WIDTH      240
#define PANEL_HEIGHT     240

static inline Arduino_GFX *board_gfx_new() {
    Arduino_DataBus *bus = new Arduino_ESP32SPI(
        PIN_LCD_DC, PIN_LCD_CS, PIN_LCD_SCK, PIN_LCD_MOSI,
        GFX_NOT_DEFINED /* no MISO: write-only panel */);
    // 240x240 of a 240x320 ST7789: without the size, Arduino_GFX assumes the
    // full 320 rows (fillScreen writes past the glass), and the flipped
    // rotations need the unused 80 rows skipped.
    return new Arduino_ST7789(bus, PIN_LCD_RST, PIN_LCD_ROTATION, true /* IPS */,
                              PANEL_WIDTH, PANEL_HEIGHT,
                              0, 0,    /* col/row offset, rotations 0 and 1 */
                              0, 80);  /* col/row offset, rotations 2 and 3 */
}

static inline void board_backlight_on() {
    pinMode(PIN_LCD_BL, OUTPUT);
    digitalWrite(PIN_LCD_BL, HIGH);
}

#endif /* MM_BOARD_WAVESHARE_ESP32C6_LCD_13_H */
