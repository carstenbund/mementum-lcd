/**
 * Guition JC3248W535 — a 3.5", 320x480 IPS panel on an ESP32-S3 with 16 MB
 * flash and 8 MB octal PSRAM. The display controller is an AXS15231B over
 * QSPI, and the same chip does the capacitive touch (I2C, address 0x3B).
 * Most likely the board behind diymore's "ESP32-S3 3.5 inch Capacitive Touch
 * LCD" listing: that is a cased S3 3.5" board, and this is the common one.
 * Confirm by the silkscreen on the back ("JC3248W535"). If it says something
 * else, it is probably the ST7796 + FT6336 variant, which needs other pins.
 *
 * Pins and the Arduino_GFX lines are GFX Library for Arduino's own
 * JC3248W535 definition (v1.6.7, examples/PDQgraphicstest/
 * Arduino_GFX_dev_device.h), matching F1ATB's Arduino setup and the ESPHome
 * community config. Not confirmed on a board in hand; gate A2 does that.
 *
 * Known on this board, from those sources, not measured here:
 *
 *   - The init sequence must be named. Since GFX 1.6.1 the AXS15231B default
 *     is the 180x640 panel's; this 320x480 panel needs the type1 sequence.
 *     That change is the "1.6.1 broke the AXS15231B" reports
 *     (moononournation/Arduino_GFX#803), not a regression.
 *   - GFX's own example wraps this panel in a full-frame Arduino_Canvas, and
 *     ESPHome users saw corrupted updates with LVGL's partial redraws. The
 *     sketch flushes in 40-line strips; if the picture tears or smears, try
 *     full-frame refresh before suspecting the pins.
 *   - Reset: F1ATB passes GFX_NOT_DEFINED; the ESPHome config names GPIO 16.
 *     Try 16 if the panel stays dark with the backlight on.
 *
 * Touch (SDA 4, SCL 8, INT 11, address 0x3B) is not wired up: the sketch's
 * board contract has no touch hook yet.
 *
 * Build with:
 *   FQBN=esp32:esp32:esp32s3
 *   OPTS=PSRAM=opi,PartitionScheme=huge_app,FlashSize=16M,CPUFreq=240,USBMode=hwcdc,CDCOnBoot=cdc
 */
#ifndef MM_BOARD_GUITION_JC3248W535_H
#define MM_BOARD_GUITION_JC3248W535_H

#include <Arduino_GFX_Library.h>

#define PIN_LCD_CS        45
#define PIN_LCD_SCK       47
#define PIN_LCD_D0        21
#define PIN_LCD_D1        48
#define PIN_LCD_D2        40
#define PIN_LCD_D3        39
#define PIN_LCD_RST       GFX_NOT_DEFINED
#define PIN_LCD_BL         1
#define PIN_LCD_ROTATION   0   // native portrait

#define PANEL_WIDTH      320
#define PANEL_HEIGHT     480

static inline Arduino_GFX *board_gfx_new() {
    Arduino_DataBus *bus = new Arduino_ESP32QSPI(
        PIN_LCD_CS, PIN_LCD_SCK, PIN_LCD_D0, PIN_LCD_D1, PIN_LCD_D2, PIN_LCD_D3);
    return new Arduino_AXS15231B(bus, PIN_LCD_RST, PIN_LCD_ROTATION,
                                 false /* ips inversion off */,
                                 PANEL_WIDTH, PANEL_HEIGHT,
                                 0, 0, 0, 0 /* no col/row offsets */,
                                 axs15231b_320480_type1_init_operations,
                                 sizeof(axs15231b_320480_type1_init_operations));
}

static inline void board_backlight_on() {
    pinMode(PIN_LCD_BL, OUTPUT);
    digitalWrite(PIN_LCD_BL, HIGH);
}

#endif /* MM_BOARD_GUITION_JC3248W535_H */
