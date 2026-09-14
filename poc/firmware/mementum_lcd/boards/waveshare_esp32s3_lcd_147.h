/**
 * Waveshare ESP32-S3-LCD-1.47 — a 1.47", 172x320, ST7789-over-4-wire-SPI
 * panel on an ESP32-S3 with 8 MB PSRAM built in. Sold rebranded by diymore
 * among others; this file's name is the reference design.
 *
 * Pins are Waveshare's own published table
 * (https://www.waveshare.com/wiki/ESP32-S3-LCD-1.47) rather than a
 * community guess — the highest-confidence board header in this folder,
 * for that reason. Xtensa + PSRAM, same as sunton_esp32_3248s035.h, so the
 * two open questions that board carries (ThorVG on this toolchain, does
 * the canvas fit) are already answered by docs/esp32-bring-up.md.
 *
 * Revision B: the diymore board in hand is silkscreened ESP32-S3-LCD-1.47B,
 * which adds a QMI8658 IMU and Li-ion charging (CHG LED, BAT/VBAT pins).
 * Its flash (25Q128JV, 16 MB) and chip (ESP32-S3R8, 8 MB PSRAM in package)
 * match the settings below. The LCD pins here are the non-B table; community
 * sources say B keeps them, but Waveshare's B page was not reachable to
 * confirm, so gate A2 is what settles it for B.
 *
 * The panel is 172 columns of a 240-column ST7789, centred: (240-172)/2 = 34
 * columns of offset, which Arduino_GFX has to be told or the picture lands
 * 34 px to the left and loses its right edge.
 *
 * Still unconfirmed by gate A2 on *this specific* board: the panel is
 * write-only SPI (no MISO wired), and this board's TF-card slot and RGB
 * LED (GPIO38) are not used here.
 *
 * Build with:
 *   FQBN=esp32:esp32:esp32s3
 *   OPTS=PSRAM=opi,PartitionScheme=huge_app,FlashSize=16M,CPUFreq=240,USBMode=hwcdc
 */
#ifndef MM_BOARD_WAVESHARE_ESP32S3_LCD_147_H
#define MM_BOARD_WAVESHARE_ESP32S3_LCD_147_H

#include <Arduino_GFX_Library.h>

#define PIN_LCD_SCK       40
#define PIN_LCD_MOSI      45
#define PIN_LCD_CS        42
#define PIN_LCD_DC        41
#define PIN_LCD_RST       39
#define PIN_LCD_BL        48
#define PIN_LCD_ROTATION   0   // 0 = native portrait, matching the module's mounting

#define PANEL_WIDTH      172
#define PANEL_HEIGHT     320

static inline Arduino_GFX *board_gfx_new() {
    Arduino_DataBus *bus = new Arduino_ESP32SPI(
        PIN_LCD_DC, PIN_LCD_CS, PIN_LCD_SCK, PIN_LCD_MOSI,
        GFX_NOT_DEFINED /* no MISO: write-only panel */);
    return new Arduino_ST7789(bus, PIN_LCD_RST, PIN_LCD_ROTATION, true /* IPS */,
                              PANEL_WIDTH, PANEL_HEIGHT,
                              34, 0,   /* col/row offset, rotations 0 and 1 */
                              34, 0);  /* col/row offset, rotations 2 and 3 */
}

static inline void board_backlight_on() {
    pinMode(PIN_LCD_BL, OUTPUT);
    digitalWrite(PIN_LCD_BL, HIGH);
}

#endif /* MM_BOARD_WAVESHARE_ESP32S3_LCD_147_H */
