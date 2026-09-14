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

#include "board_config.h"   // PANEL_WIDTH/HEIGHT, board_gfx_new(), board_backlight_on()
#include "net.h"

extern "C" {
#include "evaluator.h"
#include "render_lvgl.h"
#include "ripple.h"
#include "scene_json.h"
#include "scene_model.h"
}

// ---- the panel ------------------------------------------------------------
//
// Which board this is is entirely board_config.h's business (see
// boards/README.md) — this file only ever sees PANEL_WIDTH, PANEL_HEIGHT
// and the Arduino_GFX* that board hands back.

// 1: draw the scene compiled into scene_embedded.h (make it with
//    embed_scene.py) -- no Wi-Fi, no server, no clock sync.
// 0: join the wall: register with the control server and draw what it sends.
#define MM_STANDALONE        1
// Standalone only: 1 replays the scene's animations, 0 plays once and holds.
#define MM_STANDALONE_LOOP   1

#if MM_STANDALONE
#include "scene_embedded.h"   // MM_EMBEDDED_SCENE
#endif

static const mm_net_config CONFIG = {
    .ssid = "mementum",
    .password = "mementum",
    .server = "http://192.168.4.1:8080",
    .listen_port = 80,
    .width = PANEL_WIDTH,
    .height = PANEL_HEIGHT,
    .x = 0.0f,                 // where this panel stands, in metres
    .y = 0.0f,
};

static Arduino_GFX *gfx = board_gfx_new();

static lv_display_t *display = nullptr;
static lv_obj_t *canvas = nullptr;
static lv_draw_buf_t *draw_buf = nullptr;

static mm_scene_t scene;       // ~kilobytes: keep it static, not on the stack
static bool scene_ready = false;
static int loaded_scene_id = 0;

// ---- display --------------------------------------------------------------

// LVGL's own render buffer for the panel, in the panel's native format
// (RGB565 — ST7796 is a 16-bit SPI panel). This is separate from the
// mementum canvas below, which stays ARGB8888 for host parity; LVGL's
// software renderer blends one into the other (LV_DRAW_SW_SUPPORT_* in
// lv_conf.h is why both formats are compiled in).
static void flush_cb(lv_display_t *disp, const lv_area_t *area, uint8_t *px_map) {
    const uint32_t w = area->x2 - area->x1 + 1;
    const uint32_t h = area->y2 - area->y1 + 1;
    gfx->draw16bitRGBBitmap(area->x1, area->y1, (uint16_t *)px_map, w, h);
    lv_display_flush_ready(disp);
}

// LVGL's clock. Without it no refresh timer ever fires, flush_cb is never
// called, and the panel stays on gfx->fillScreen() forever. A wrapper rather
// than millis itself: millis returns unsigned long, and the callback type is
// uint32_t(void), which C++ will not convert between.
static uint32_t lvgl_tick() {
    return millis();
}

static void display_init() {
    lv_init();
    lv_tick_set_cb(lvgl_tick);

    board_backlight_on();
    gfx->begin();
    gfx->fillScreen(BLACK);

    display = lv_display_create(PANEL_WIDTH, PANEL_HEIGHT);
    lv_display_set_color_format(display, LV_COLOR_FORMAT_RGB565);
    lv_display_set_flush_cb(display, flush_cb);

    // A partial buffer (40 lines) rather than a full frame: the full frame
    // lives in the mementum canvas below, already in PSRAM.
    static lv_color16_t flush_buf[PANEL_WIDTH * 40];
    lv_display_set_buffers(display, flush_buf, NULL, sizeof(flush_buf),
                            LV_DISPLAY_RENDER_MODE_PARTIAL);

    draw_buf = lv_draw_buf_create(PANEL_WIDTH, PANEL_HEIGHT,
                                   LV_COLOR_FORMAT_ARGB8888, 0);
    canvas = lv_canvas_create(lv_display_get_screen_active(display));
    lv_canvas_set_draw_buf(canvas, draw_buf);
}

// ---- the loop that matters -------------------------------------------------

static int drawn_scene_id = -1;
static float drawn_scene_time = -1.0f;

// A frame is a pure function of (scene, scene time), so a frame already on
// the glass never needs drawing again -- and once every animation has ended,
// no later time looks any different. Without this the whole canvas crossed
// the panel bus every loop, for a picture that had stopped changing.
static bool needs_draw(float scene_time) {
    if(drawn_scene_id != loaded_scene_id) return true;
    const float end = scene.duration_ms;
    if(scene_time >= end && drawn_scene_time >= end) return false;
    return scene_time != drawn_scene_time;
}

static void render_at(float scene_time) {
    mm_evaluate(&scene, scene_time);
    lv_canvas_fill_bg(canvas, lv_color_hex(0x000000), LV_OPA_COVER);
    lv_layer_t layer;
    lv_canvas_init_layer(canvas, &layer);
    mm_render_scene(&layer, &scene, PANEL_WIDTH, PANEL_HEIGHT, nullptr, 0, scene_time);
    lv_canvas_finish_layer(canvas, &layer);
    lv_obj_invalidate(canvas);
    drawn_scene_id = loaded_scene_id;
    drawn_scene_time = scene_time;
}

#if MM_STANDALONE

static uint32_t standalone_started_ms = 0;

static void standalone_begin() {
    char error[128] = "";
    if(!mm_scene_from_json(MM_EMBEDDED_SCENE, &scene, error, sizeof(error))) {
        Serial.printf("embedded scene refused: %s\n", error);
        return;
    }
    loaded_scene_id = 1;
    scene_ready = true;
    standalone_started_ms = millis();
    Serial.printf("embedded scene ready: %d objects, %.1fs\n",
                  scene.object_count, scene.duration_ms / 1000.0);
}

static void standalone_draw() {
    if(!scene_ready) return;
    float scene_time = (float)(millis() - standalone_started_ms);
#if MM_STANDALONE_LOOP
    if(scene.duration_ms > 0.0f) scene_time = fmod(scene_time, scene.duration_ms);
#endif
    if(needs_draw(scene_time)) render_at(scene_time);
}

#else

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
    if(needs_draw(scene_time)) render_at(scene_time);
}

#endif /* MM_STANDALONE */

void setup() {
    Serial.begin(115200);
    delay(200);
    Serial.println("mementum panel");

    display_init();
#if MM_STANDALONE
    standalone_begin();
#else
    if(!mm_net_begin(CONFIG)) {
        Serial.println("running unregistered — will keep trying");
    }
#endif
}

void loop() {
#if MM_STANDALONE
    standalone_draw();  // evaluate and render at the local clock
#else
    mm_net_loop();      // pushes, heartbeats, clock
    load_if_needed();   // fetch and parse a scene, once
    draw();             // evaluate and render at the shared clock
#endif
    lv_timer_handler();
    delay(5);
}
