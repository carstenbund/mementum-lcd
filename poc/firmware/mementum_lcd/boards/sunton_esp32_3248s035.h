/**
 * Sunton/JC ESP32-3248S035 — a 3.5", 480x320 landscape, ST7796-over-4-wire-SPI
 * panel on a **classic ESP32 (ESP32-WROOM-32, Xtensa LX6), 4 MB flash** — the
 * "Cheap Yellow Display" family. Not an ESP32-S3, and not the diymore
 * "ESP32-S3 3.5 inch" board: that one is guition_jc3248w535.h. On an S3,
 * GPIO 27 below is wired to flash/PSRAM, so these pins are for this board only.
 *
 * Open risk, like the C6: this family is generally sold without PSRAM, and
 * docs/esp32-bring-up.md puts the canvas there (480x320 ARGB8888 is ~614 KB).
 * Check the module before spending time on it. Build with
 * FQBN=esp32:esp32:esp32, and no PSRAM option unless the module has it.
 *
 * Touch is FT6336 (diymore's own listing) or GT911 (the common variant of
 * this family), depending on the batch. Not wired up here: gates A2/A3 of
 * docs/esp32-bring-up.md don't need it, and the two chips differ enough
 * (register layout, I2C address) that guessing wrong would cost more than
 * skipping it for now.
 *
 * The pins below are the ones this whole clone family is documented with
 * across several sellers (Sunton/Elecrow/Spotpear demos, a working
 * lvgl_micropython config) — **not confirmed against any specific PCB
 * revision**. Gate A2 ("a red screen, then a white one") is what confirms
 * them. If the picture is garbage, wrong colours, or mirrored, it is one of
 * these defines, not anything in mementum_lcd.ino.
 */
#ifndef MM_BOARD_SUNTON_ESP32_3248S035_H
#define MM_BOARD_SUNTON_ESP32_3248S035_H

#include <Arduino_GFX_Library.h>

#define PIN_LCD_SCK       14
#define PIN_LCD_MOSI      13
#define PIN_LCD_MISO      12
#define PIN_LCD_CS        15
#define PIN_LCD_DC         2
#define PIN_LCD_RST       17
#define PIN_LCD_BL        27
#define PIN_LCD_ROTATION   1   // 1 = landscape; try 3 if the image is mirrored

#define PANEL_WIDTH      480
#define PANEL_HEIGHT     320

static inline Arduino_GFX *board_gfx_new() {
    Arduino_DataBus *bus = new Arduino_ESP32SPI(
        PIN_LCD_DC, PIN_LCD_CS, PIN_LCD_SCK, PIN_LCD_MOSI, PIN_LCD_MISO);
    return new Arduino_ST7796(bus, PIN_LCD_RST, PIN_LCD_ROTATION, true /* IPS */);
}

static inline void board_backlight_on() {
    pinMode(PIN_LCD_BL, OUTPUT);
    digitalWrite(PIN_LCD_BL, HIGH);
}

#endif /* MM_BOARD_SUNTON_ESP32_3248S035_H */
