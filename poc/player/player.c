#include "player.h"

#include "easing.h"
#include "evaluator.h"
#include "render_lvgl.h"
#include "scene_json.h"

#include "lvgl.h"

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct mm_player {
    mm_scene_t scene;           /**< the loaded scene, re-evaluated per frame */
    int width, height;
    lv_display_t *display;
    lv_obj_t *canvas;
    lv_draw_buf_t *draw_buf;
    uint8_t *display_buf;
};

static char g_error[256] = "";
static bool g_initialised = false;

static void set_error(const char *fmt, ...)
{
    va_list args;
    va_start(args, fmt);
    vsnprintf(g_error, sizeof(g_error), fmt, args);
    va_end(args);
}

const char *mm_player_error(void)
{
    return g_error;
}

static void flush_cb(lv_display_t *display, const lv_area_t *area, uint8_t *px_map)
{
    LV_UNUSED(area);
    LV_UNUSED(px_map);
    lv_display_flush_ready(display);
}

int mm_player_init(void)
{
    if(g_initialised) return 0;
    lv_init();
    g_initialised = true;
    return 0;
}

mm_player_t *mm_player_load(const char *scene_json, int width, int height)
{
    if(mm_player_init() != 0) return NULL;
    if(scene_json == NULL || width <= 0 || height <= 0) {
        set_error("bad arguments to mm_player_load");
        return NULL;
    }

    mm_player_t *player = calloc(1, sizeof(*player));
    if(player == NULL) {
        set_error("out of memory");
        return NULL;
    }

    if(!mm_scene_from_json(scene_json, &player->scene, g_error, sizeof(g_error))) {
        free(player);
        return NULL;
    }

    player->width = width;
    player->height = height;

    /* A display exists only because a canvas needs a screen to live on; it is
     * never flushed anywhere. The frame the caller gets is the canvas buffer. */
    player->display_buf = calloc(1, (size_t)width * height * 4);
    player->draw_buf = lv_draw_buf_create(width, height, LV_COLOR_FORMAT_ARGB8888, 0);
    if(player->display_buf == NULL || player->draw_buf == NULL) {
        set_error("could not allocate a %dx%d frame", width, height);
        mm_player_destroy(player);
        return NULL;
    }

    player->display = lv_display_create(width, height);
    lv_display_set_flush_cb(player->display, flush_cb);
    lv_display_set_buffers(player->display, player->display_buf, NULL,
                           (size_t)width * height * 4, LV_DISPLAY_RENDER_MODE_DIRECT);

    player->canvas = lv_canvas_create(lv_display_get_screen_active(player->display));
    lv_canvas_set_draw_buf(player->canvas, player->draw_buf);
    return player;
}

void mm_player_destroy(mm_player_t *player)
{
    if(player == NULL) return;
    if(player->canvas != NULL) lv_obj_delete(player->canvas);
    if(player->display != NULL) lv_display_delete(player->display);
    if(player->draw_buf != NULL) lv_draw_buf_destroy(player->draw_buf);
    free(player->display_buf);
    free(player);
}

int mm_player_render(mm_player_t *player, double scene_time_ms, uint8_t *out, size_t out_size)
{
    if(player == NULL || out == NULL) {
        set_error("bad arguments to mm_player_render");
        return -1;
    }
    const size_t needed = (size_t)player->width * player->height * 4;
    if(out_size < needed) {
        set_error("output buffer too small: %zu < %zu", out_size, needed);
        return -1;
    }

    /* Evaluate, then draw. The evaluator is pure, so rendering the same scene
     * time twice gives the same frame and rendering out of order is harmless. */
    mm_evaluate(&player->scene, (float)scene_time_ms);

    lv_canvas_fill_bg(player->canvas, lv_color_hex(0x000000), LV_OPA_COVER);
    lv_layer_t layer;
    lv_canvas_init_layer(player->canvas, &layer);
    mm_render_scene(&layer, &player->scene, player->width, player->height);
    lv_canvas_finish_layer(player->canvas, &layer);

    /* ARGB8888 is B,G,R,A in memory on a little-endian host; the caller wants
     * RGBA. This is the one colour conversion in the whole path. */
    const uint8_t *src = player->draw_buf->data;
    for(size_t i = 0; i < needed; i += 4) {
        out[i + 0] = src[i + 2];
        out[i + 1] = src[i + 1];
        out[i + 2] = src[i + 0];
        out[i + 3] = src[i + 3];
    }
    return 0;
}

/* -- introspection --------------------------------------------------------- */

static const mm_object_t *find(const mm_player_t *player, const char *object_id)
{
    if(player == NULL || object_id == NULL) return NULL;
    for(int i = 0; i < player->scene.object_count; i++) {
        if(strcmp(player->scene.objects[i].id, object_id) == 0) {
            return &player->scene.objects[i];
        }
    }
    return NULL;
}

double mm_player_scene_duration(const mm_player_t *player)
{
    return player != NULL ? player->scene.duration_ms : 0.0;
}

int mm_player_object_count(const mm_player_t *player)
{
    return player != NULL ? player->scene.object_count : 0;
}

double mm_player_path_length(const mm_player_t *player, const char *object_id)
{
    const mm_object_t *object = find(player, object_id);
    return object != NULL ? object->length : -1.0;
}

int mm_player_subpath_count(const mm_player_t *player, const char *object_id)
{
    const mm_object_t *object = find(player, object_id);
    return object != NULL ? object->subpath_count : -1;
}

double mm_player_property_at(const mm_player_t *player, const char *object_id,
                             const char *property, double scene_time_ms)
{
    mm_player_t *mutable_player = (mm_player_t *)player;
    const mm_object_t *object = find(player, object_id);
    if(object == NULL) return -1.0;

    mm_evaluate(&mutable_player->scene, (float)scene_time_ms);
    if(strcmp(property, "opacity") == 0)  return object->opacity;
    if(strcmp(property, "progress") == 0) return object->progress;
    if(strcmp(property, "visible") == 0)  return object->visible ? 1.0 : 0.0;
    return -1.0;
}

double mm_player_ease(const char *easing, double p)
{
    return mm_ease(mm_easing_from_name(easing), (float)p);
}
