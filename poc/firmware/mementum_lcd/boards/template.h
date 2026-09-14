/**
 * Template board header — copy this file, rename it, fill in the three
 * names `mementum_lcd.ino` calls (see boards/README.md for the contract),
 * then add it to the table in ../board_config.h. Not itself a working
 * board: it will not compile until the TODOs below are resolved.
 *
 * This shape fits any Arduino_GFX-supported bus (4-wire SPI, 8-bit
 * parallel, RGB parallel) — only board_gfx_new() needs to know which.
 * See https://github.com/moononournation/Arduino_GFX/wiki for the display
 * and bus classes available.
 */
#ifndef MM_BOARD_TEMPLATE_H
#define MM_BOARD_TEMPLATE_H

#include <Arduino_GFX_Library.h>

// TODO: this board's pins.
#define PIN_LCD_SCK       -1
#define PIN_LCD_MOSI      -1
#define PIN_LCD_MISO      -1
#define PIN_LCD_CS        -1
#define PIN_LCD_DC        -1
#define PIN_LCD_RST       -1
#define PIN_LCD_BL        -1
#define PIN_LCD_ROTATION   0

// TODO: the panel's native resolution, in the rotation above.
#define PANEL_WIDTH        0
#define PANEL_HEIGHT       0

// TODO: construct this board's bus and display class. Everything else in
// the sketch only ever sees the Arduino_GFX* this returns.
static inline Arduino_GFX *board_gfx_new() {
    Arduino_DataBus *bus = new Arduino_ESP32SPI(
        PIN_LCD_DC, PIN_LCD_CS, PIN_LCD_SCK, PIN_LCD_MOSI, PIN_LCD_MISO);
    return new Arduino_ST7796(bus, PIN_LCD_RST, PIN_LCD_ROTATION, true /* IPS */);
}

// TODO: however this board's backlight actually turns on — a plain GPIO,
// active-low, PWM, or nothing if it is tied high in hardware.
static inline void board_backlight_on() {
    pinMode(PIN_LCD_BL, OUTPUT);
    digitalWrite(PIN_LCD_BL, HIGH);
}

#endif /* MM_BOARD_TEMPLATE_H */
