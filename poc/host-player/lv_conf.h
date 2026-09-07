/**
 * LVGL configuration for the host player (implementation plan §3.7).
 *
 * Headless and deliberately minimal: no OS, no SDL, no window. The player
 * renders into a memory framebuffer that the simulator can hash and diff, which
 * is the same thing the ESP32 build does one layer lower. What matters here is
 * that vector graphics and the software renderer are on -- everything else is
 * off so that a build failure means something.
 */
#ifndef LV_CONF_H
#define LV_CONF_H

#include <stdint.h>

#define LV_COLOR_DEPTH              32          /* ARGB8888: alpha is required (§17) */
#define LV_USE_STDLIB_MALLOC        LV_STDLIB_CLIB
#define LV_USE_STDLIB_STRING        LV_STDLIB_CLIB
#define LV_USE_STDLIB_SPRINTF       LV_STDLIB_CLIB
#define LV_USE_OS                   LV_OS_NONE

#define LV_DRAW_BUF_ALIGN           4
#define LV_USE_DRAW_SW              1
#define LV_DRAW_SW_SUPPORT_ARGB8888 1
#define LV_DRAW_SW_SUPPORT_RGB565   1
#define LV_DRAW_SW_DRAW_UNIT_CNT    1           /* single-threaded: determinism first */

/* The R1 question lives here. */
#define LV_USE_FLOAT                1           /* required by lv_matrix */
#define LV_USE_MATRIX               1           /* required by lv_draw_vector */
#define LV_USE_VECTOR_GRAPHIC       1
#define LV_USE_THORVG_INTERNAL      1

#define LV_USE_CANVAS               1
#define LV_USE_LABEL                1
#define LV_USE_LOG                  1
#define LV_LOG_LEVEL                LV_LOG_LEVEL_WARN
#define LV_LOG_PRINTF               1

#define LV_USE_ASSERT_NULL          1
#define LV_USE_ASSERT_MALLOC        1

#define LV_USE_PERF_MONITOR         0
#define LV_USE_MEM_MONITOR          0
#define LV_BUILD_EXAMPLES           0
#define LV_USE_DEMO_WIDGETS         0

#endif /* LV_CONF_H */
