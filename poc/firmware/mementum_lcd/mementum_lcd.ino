/**
 * mementum — a panel that draws, on an ESP32-S3 with an LCD.
 *
 * The sibling of `mementum-led`'s http_controller sketch, and deliberately the
 * same shape: connect, register, sync the clock, serve the push routes, and
 * render every frame as a pure function of the shared clock. What differs is
 * only what is being drawn — a scene of paths rather than a scrolling string —
 * and that is not this file's business either, because the drawing is the same
 * C the host tests run:
 *
 *     poc/player/  scene_json.c evaluator.c geometry.c render_lvgl.c
 *                  ripple.c schedule.c screen.c
 *
 * Those files are shared verbatim; `link.sh` symlinks them here, because the
 * Arduino IDE compiles what is in the sketch folder. One evaluator, not two
 * (implementation plan §3.7) — the reason the host suite is worth anything is
 * that these are the lines it exercises.
 *
 * This sketch has **no server mode**. The LED firmware can elect itself the
 * soft-AP server; a panel cannot, because the server hands out scenes and a
 * device with a few megabytes cannot hold the library a show draws from.
 *
 * Board: ESP32-S3 with PSRAM enabled, an LCD LVGL can drive.
 * Libraries: LVGL 9.5 (with LV_USE_VECTOR_GRAPHIC and the bundled ThorVG), and
 * whatever display driver the panel needs.
 */

#include <Arduino.h>
#include <lvgl.h>

#include "net.h"

extern "C" {
#include "evaluator.h"
#include "render_lvgl.h"
#include "ripple.h"
#include "scene_json.h"
#include "scene_model.h"
}

// ---- the panel ------------------------------------------------------------

static const mm_net_config CONFIG = {
    .ssid = "mementum",
    .password = "mementum",
    .server = "http://192.168.4.1:8080",
    .listen_port = 80,
    .width = 450,
    .height = 250,
    .x = 0.0f,                 // where this panel stands, in metres
    .y = 0.0f,
};

static lv_display_t *display = nullptr;
static lv_obj_t *canvas = nullptr;
static lv_draw_buf_t *draw_buf = nullptr;

static mm_scene_t scene;       // ~kilobytes: keep it static, not on the stack
static bool scene_ready = false;
static int loaded_scene_id = 0;

// ---- display --------------------------------------------------------------

static void display_init() {
    lv_init();
    // Panel-specific: create the display for the board's LCD, then a canvas
    // covering it. Everything above this line is portable; this is not.
    display = lv_display_get_default();
    if(display == nullptr) {
        Serial.println("no LVGL display — add the board's driver here");
        return;
    }
    const int32_t w = lv_display_get_horizontal_resolution(display);
    const int32_t h = lv_display_get_vertical_resolution(display);
    draw_buf = lv_draw_buf_create(w, h, LV_COLOR_FORMAT_ARGB8888, 0);
    canvas = lv_canvas_create(lv_display_get_screen_active(display));
    lv_canvas_set_draw_buf(canvas, draw_buf);
}

// ---- the loop that matters -------------------------------------------------

static void load_if_needed() {
    if(!mm_current.active || mm_current.scene_id == 0) return;
    if(loaded_scene_id == mm_current.scene_id && scene_ready) return;
    if(!mm_fetch_scene()) return;

    char error[128] = "";
    // Parsed once, on arrival. Doing this per frame is what a ~98 KB stack
    // local and a heap corruption bug taught us not to do.
    if(!mm_scene_from_json(mm_scene_json(), &scene, error, sizeof(error))) {
        Serial.printf("scene %d refused: %s\n", mm_current.scene_id, error);
        scene_ready = false;
        return;
    }
    loaded_scene_id = mm_current.scene_id;
    scene_ready = true;
    Serial.printf("scene %d ready: %d objects, %.1fs\n",
                  scene.id, scene.object_count, scene.duration_ms / 1000.0);
}

static void draw() {
    const double now = (double)mm_server_now();
    if(!scene_ready || !mm_schedule_showing(&mm_current, now)) return;

    // The whole contract with the network, in one line: what time is the scene
    // at? Nothing accumulates, so a dropped frame costs nothing and two panels
    // on one clock agree without ever talking to each other.
    const float scene_time = (float)mm_schedule_time(&mm_current, now);

    mm_evaluate(&scene, scene_time);
    lv_canvas_fill_bg(canvas, lv_color_hex(0x000000), LV_OPA_COVER);
    lv_layer_t layer;
    lv_canvas_init_layer(canvas, &layer);
    mm_render_scene(&layer, &scene, CONFIG.width, CONFIG.height, nullptr, 0, scene_time);
    lv_canvas_finish_layer(canvas, &layer);
    lv_obj_invalidate(canvas);
}

void setup() {
    Serial.begin(115200);
    delay(200);
    Serial.println("mementum panel");

    display_init();
    if(!mm_net_begin(CONFIG)) {
        Serial.println("running unregistered — will keep trying");
    }
}

void loop() {
    mm_net_loop();      // pushes, heartbeats, clock
    load_if_needed();   // fetch and parse a scene, once
    draw();             // evaluate and render at the shared clock
    lv_timer_handler();
    delay(5);
}
