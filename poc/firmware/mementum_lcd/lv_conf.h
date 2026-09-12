/**
 * LVGL configuration for the panel — the host's, minus the desktop.
 *
 * Kept deliberately close to `poc/host-player/lv_conf.h`, because the two
 * renderers being byte-identical is a property of *this file* as much as of the
 * code: a different colour depth or a different draw-unit count is a different
 * picture, and the host suite would stop meaning anything about the device.
 *
 * Three things differ, and each is a board fact rather than a preference:
 *
 *   - no DRM (that is Linux's output path; here it is an esp_lcd panel);
 *   - allocation goes through the C library so PSRAM can be given to it;
 *   - the fonts are trimmed to one, because flash is not free.
 *
 * LV_COLOR_DEPTH is the one number to revisit on the board. 32 is what the host
 * renders and what layer alpha needs; a single-scene panel over an opaque
 * background may not need alpha at all, and 16 halves both the canvas (450x250:
 * 450 KB -> 225 KB) and the PSRAM traffic per frame. Decide it against a
 * measured frame time, not in advance -- see docs/esp32-bring-up.md.
 */
#ifndef LV_CONF_H
#define LV_CONF_H

/* No <stdint.h> here, unlike the host's copy. LVGL ships an Arm assembly file
 * (src/draw/sw/blend/helium/lv_blend_helium.S) that includes lv_conf_internal.h
 * and therefore this file, and the Arduino builder assembles every .S in a
 * library whatever the target is. A C header reaching the Xtensa assembler
 * produces "unknown opcode or format name 'typedef'" a few hundred times,
 * which is how this was found. Nothing below needs a type -- these are all
 * macros -- so the include was only ever inherited from the host config. */

#define LV_COLOR_DEPTH              32          /* see the note above */
#define LV_USE_STDLIB_MALLOC        LV_STDLIB_CLIB
#define LV_USE_STDLIB_STRING        LV_STDLIB_CLIB
#define LV_USE_STDLIB_SPRINTF       LV_STDLIB_CLIB
#define LV_USE_OS                   LV_OS_NONE  /* FreeRTOS exists; LVGL need not know */

#define LV_DRAW_BUF_ALIGN           4
#define LV_USE_DRAW_SW              1
#define LV_DRAW_SW_SUPPORT_ARGB8888 1
#define LV_DRAW_SW_SUPPORT_RGB565   1
#define LV_DRAW_SW_DRAW_UNIT_CNT    1           /* one core to the picture */

/* The whole reason this project can draw a line that is half drawn. If this
 * does not build or does not fit, gate A4 in the bring-up plan has failed and
 * nothing after it is worth trying. */
#define LV_USE_FLOAT                1
#define LV_USE_MATRIX               1
#define LV_USE_VECTOR_GRAPHIC       1
#define LV_USE_THORVG_INTERNAL      1

#define LV_USE_CANVAS               1
#define LV_USE_LABEL                1

/* One font. Text on a panel comes from the composer as strokes; this is for
 * diagnostics on the glass, not for content. */
#define LV_FONT_MONTSERRAT_14       1

#define LV_USE_LOG                  1
#define LV_LOG_LEVEL                LV_LOG_LEVEL_WARN
#define LV_LOG_PRINTF               1           /* printf goes to the serial monitor */

#define LV_USE_ASSERT_NULL          1
#define LV_USE_ASSERT_MALLOC        1

/* On until the frame budget is known: both report to the panel itself, which is
 * the only place anybody can see them during bring-up. */
#define LV_USE_PERF_MONITOR         0
#define LV_USE_MEM_MONITOR          0
#define LV_BUILD_EXAMPLES           0
#define LV_USE_DEMO_WIDGETS         0

#endif /* LV_CONF_H */
