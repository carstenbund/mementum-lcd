/**
 * The one line that picks a board. Uncomment exactly one; everything else
 * in the sketch takes PANEL_WIDTH, PANEL_HEIGHT, board_gfx_new() and
 * board_backlight_on() from whichever header this names. See
 * boards/README.md for the contract a board header meets, the table of
 * what's here, and the FQBN/OPTS each board needs from build.sh.
 *
 * boards/template.h is a documented skeleton for adding one that isn't.
 */
#ifndef MM_BOARD_CONFIG_H
#define MM_BOARD_CONFIG_H

#include "boards/guition_jc3248w535.h"         // diymore ESP32-S3 3.5" capacitive touch LCD (check back: JC3248W535)
// #include "boards/waveshare_esp32s3_lcd_147.h"  // diymore/Waveshare ESP32-S3 1.47" LCD (rev B)
// #include "boards/waveshare_esp32c6_lcd_13.h"   // diymore/Waveshare 1.3" LCD (RISC-V, no PSRAM)
// #include "boards/sunton_esp32_3248s035.h"      // Sunton 3.5" "Cheap Yellow Display" (classic ESP32, not S3)

#endif /* MM_BOARD_CONFIG_H */
