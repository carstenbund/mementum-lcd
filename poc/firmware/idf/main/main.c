/**
 * The panel, on ESP-IDF — steps B1 to B4 of the bring-up plan.
 *
 * No networking: this is the build-and-draw smoke test, and it exists so that
 * "does LVGL with ThorVG fit, build and run on this board" is answered before
 * anything about Wi-Fi, schedules or shows is in the picture. It draws one
 * embedded scene at a fixed set of scene times and reports what each cost.
 *
 * What it prints is what the bring-up plan asks for and what nothing on the
 * host can tell us:
 *
 *     scene  parsed in N ms, M bytes of PSRAM
 *     frame  evaluate + render in N ms at scene time T
 *     heap   internal / PSRAM free
 *
 * The display driver is the one board-specific thing and is marked as such.
 */

#include <stdio.h>
#include <string.h>

#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "lvgl.h"

#include "evaluator.h"
#include "render_lvgl.h"
#include "scene_json.h"
#include "scene_model.h"

static const char *TAG = "mementum";

/* poc/scenes/three-strokes.json, embedded by main/CMakeLists.txt. Small on
 * purpose: one path object, so a failure here is never about memory. */
extern const char scene_json_start[] asm("_binary_three_strokes_json_start");

#define PANEL_WIDTH  240
#define PANEL_HEIGHT 120

static mm_scene_t scene;                 /* ~19 KB: static, never on the stack */
static lv_obj_t *canvas;

static uint32_t tick_ms(void)
{
    return (uint32_t)(esp_timer_get_time() / 1000);
}

static void report_heap(const char *when)
{
    ESP_LOGI(TAG, "heap  %s: internal %u, psram %u", when,
             (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
             (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
}

/** Board-specific, and the only part of this file that is.
 *
 *  Bring it up with the board's own esp_lcd driver first (gate A2/B4), then
 *  bind it to LVGL here. Until that exists, a memory display renders exactly
 *  the same pixels into PSRAM and answers the questions that matter -- whether
 *  it builds, whether it fits, and how long a frame takes -- without a panel.
 */
static lv_display_t *display_create(void)
{
    const size_t pixels = (size_t)PANEL_WIDTH * PANEL_HEIGHT;
    void *buffer = heap_caps_malloc(pixels * 4, MALLOC_CAP_SPIRAM);
    if(buffer == NULL) {
        ESP_LOGE(TAG, "no PSRAM for a %dx%d buffer -- is CONFIG_SPIRAM on?",
                 PANEL_WIDTH, PANEL_HEIGHT);
        return NULL;
    }
    lv_display_t *display = lv_display_create(PANEL_WIDTH, PANEL_HEIGHT);
    lv_display_set_buffers(display, buffer, NULL, pixels * 4,
                           LV_DISPLAY_RENDER_MODE_DIRECT);
    return display;
}

void app_main(void)
{
    ESP_LOGI(TAG, "mementum panel: LVGL %d.%d.%d", lv_version_major(),
             lv_version_minor(), lv_version_patch());
    report_heap("boot");

    lv_init();
    lv_tick_set_cb(tick_ms);

    lv_display_t *display = display_create();
    if(display == NULL) return;

    lv_draw_buf_t *draw_buf =
        lv_draw_buf_create(PANEL_WIDTH, PANEL_HEIGHT, LV_COLOR_FORMAT_ARGB8888, 0);
    canvas = lv_canvas_create(lv_display_get_screen_active(display));
    lv_canvas_set_draw_buf(canvas, draw_buf);
    report_heap("after lvgl");

    /* Parsed once, on arrival -- never per frame (that mistake presented as
     * heap corruption on the host and would be worse here). */
    const int64_t parse_started = esp_timer_get_time();
    char error[128] = "";
    if(!mm_scene_from_json(scene_json_start, &scene, error, sizeof(error))) {
        ESP_LOGE(TAG, "scene refused: %s", error);
        return;
    }
    ESP_LOGI(TAG, "scene %d: %d objects, %.1fs, parsed in %lld ms", scene.id,
             scene.object_count, scene.duration_ms / 1000.0,
             (esp_timer_get_time() - parse_started) / 1000);
    report_heap("after scene");

    /* A fixed sweep rather than a loop on the clock: every frame is a pure
     * function of the scene time, so the same times give the same pictures and
     * the same costs -- which is what makes these numbers comparable with the
     * host's. */
    const float times[] = {0.0f, 750.0f, 1500.0f, 2250.0f, 3000.0f};
    for(;;) {
        for(size_t i = 0; i < sizeof(times) / sizeof(times[0]); i++) {
            const int64_t started = esp_timer_get_time();
            mm_evaluate(&scene, times[i]);
            lv_canvas_fill_bg(canvas, lv_color_hex(0x000000), LV_OPA_COVER);
            lv_layer_t layer;
            lv_canvas_init_layer(canvas, &layer);
            mm_render_scene(&layer, &scene, PANEL_WIDTH, PANEL_HEIGHT, NULL, 0, times[i]);
            lv_canvas_finish_layer(canvas, &layer);
            const int64_t drawn = esp_timer_get_time();

            lv_obj_invalidate(canvas);
            lv_refr_now(display);

            ESP_LOGI(TAG, "frame t=%6.0f ms: evaluate+render %lld ms, present %lld ms",
                     times[i], (drawn - started) / 1000,
                     (esp_timer_get_time() - drawn) / 1000);
            vTaskDelay(pdMS_TO_TICKS(500));
        }
        report_heap("steady");
    }
}
