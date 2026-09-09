#include "screen.h"

#include "evaluator.h"
#include "geometry.h"
#include "render_lvgl.h"
#include "ripple.h"
#include "scene_json.h"
#include "player.h"

#include "lvgl.h"

#if LV_USE_LINUX_DRM
#include "src/drivers/display/drm/lv_linux_drm.h"
#endif

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define MM_SCREEN_MAX_LAYERS 32
#define MM_NAME_LEN   64

typedef struct {
    char name[MM_NAME_LEN];
    char hit_id[MM_NAME_LEN];
    int width, height;
    int x, y, z;
    int visible;
    int interactive;
    double opacity;
    lv_obj_t *canvas;
    lv_draw_buf_t *buf;
    mm_scene_t *scene;                  /**< NULL for a bitmap layer */
    double time_offset;                 /**< this layer's own clock, vs the screen's */
    mm_ripple_t ripples[MM_MAX_RIPPLES];
    int ripple_count;
} mm_screen_layer_t;

struct mm_screen {
    int width, height;
    int is_drm;
    lv_display_t *display;
    uint8_t *display_buf;
    mm_screen_layer_t layers[MM_SCREEN_MAX_LAYERS];
    int layer_count;
    double last_render_ms;
};

static char g_error[256] = "";

static void set_error(const char *fmt, ...)
{
    va_list args;
    va_start(args, fmt);
    vsnprintf(g_error, sizeof(g_error), fmt, args);
    va_end(args);
}

const char *mm_screen_error(void) { return g_error; }

static double now_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1000.0 + ts.tv_nsec / 1e6;
}

static void flush_cb(lv_display_t *display, const lv_area_t *area, uint8_t *px_map)
{
    LV_UNUSED(area);
    LV_UNUSED(px_map);
    lv_display_flush_ready(display);
}

static mm_screen_layer_t *find_layer(const mm_screen_t *screen, const char *name)
{
    if(screen == NULL || name == NULL) return NULL;
    for(int i = 0; i < screen->layer_count; i++) {
        if(strcmp(screen->layers[i].name, name) == 0) return (mm_screen_layer_t *)&screen->layers[i];
    }
    return NULL;
}

/** LVGL draws children in tree order, so z is expressed by re-indexing. Called
 *  after anything that changes z; O(n^2) over at most MM_SCREEN_MAX_LAYERS. */
static void reorder(mm_screen_t *screen)
{
    for(int slot = 0; slot < screen->layer_count; slot++) {
        mm_screen_layer_t *lowest = NULL;
        for(int i = 0; i < screen->layer_count; i++) {
            mm_screen_layer_t *candidate = &screen->layers[i];
            if(lv_obj_get_index(candidate->canvas) < slot) continue;
            if(lowest == NULL || candidate->z < lowest->z) lowest = candidate;
        }
        if(lowest != NULL) lv_obj_move_to_index(lowest->canvas, slot);
    }
}

/* -- lifecycle ------------------------------------------------------------- */

mm_screen_t *mm_screen_create(int width, int height, const char *backend)
{
    /* One lv_init per process, whoever gets there first -- this library is
     * loaded once and may already be holding a player. */
    if(!lv_is_initialized()) lv_init();
    const int want_drm = backend != NULL && strcmp(backend, "drm") == 0;

    mm_screen_t *screen = calloc(1, sizeof(*screen));
    if(screen == NULL) {
        set_error("out of memory");
        return NULL;
    }

    if(want_drm) {
#if LV_USE_LINUX_DRM
        /* MM_MODE=1920x1080 asks the connector for that mode rather than the
         * first one it lists. Must be set before the display is created. */
        const char *mode = getenv("MM_MODE");
        if(mode != NULL) setenv("LV_DRM_MODE", mode, 1);

        screen->display = lv_linux_drm_create();
        if(screen->display == NULL) {
            set_error("no DRM display");
            free(screen);
            return NULL;
        }
        char *device = lv_linux_drm_find_device_path();
        if(lv_linux_drm_set_file(screen->display, device ? device : "/dev/dri/card0", -1)
           != LV_RESULT_OK) {
            set_error("cannot open the DRM device (video group? DRM master held?)");
            free(screen);
            return NULL;
        }
        screen->is_drm = 1;
        screen->width = lv_display_get_horizontal_resolution(screen->display);
        screen->height = lv_display_get_vertical_resolution(screen->display);
#else
        set_error("this build has no DRM backend");
        free(screen);
        return NULL;
#endif
    }
    else {
        if(width <= 0 || height <= 0) {
            set_error("the memory backend needs a size");
            free(screen);
            return NULL;
        }
        screen->width = width;
        screen->height = height;
        screen->display_buf = calloc(1, (size_t)width * height * 4);
        if(screen->display_buf == NULL) {
            set_error("could not allocate a %dx%d frame", width, height);
            free(screen);
            return NULL;
        }
        screen->display = lv_display_create(width, height);
        /* XRGB8888, like drm_display's canonical buffer: the presented frame
         * is opaque by definition -- the root screen is -- and asking LVGL to
         * carry an alpha channel through the composite only costs rounding. */
        lv_display_set_color_format(screen->display, LV_COLOR_FORMAT_XRGB8888);
        lv_display_set_flush_cb(screen->display, flush_cb);
        lv_display_set_buffers(screen->display, screen->display_buf, NULL,
                               (size_t)width * height * 4, LV_DISPLAY_RENDER_MODE_DIRECT);
    }

    lv_obj_t *root = lv_display_get_screen_active(screen->display);
    lv_obj_set_style_bg_color(root, lv_color_hex(0x000000), 0);
    lv_obj_set_style_bg_opa(root, LV_OPA_COVER, 0);
    lv_obj_remove_flag(root, LV_OBJ_FLAG_SCROLLABLE);
    return screen;
}

void mm_screen_destroy(mm_screen_t *screen)
{
    if(screen == NULL) return;
    for(int i = 0; i < screen->layer_count; i++) {
        mm_screen_layer_t *layer = &screen->layers[i];
        if(layer->scene != NULL) {
            for(int o = 0; o < layer->scene->object_count; o++) {
                mm_path_destroy(layer->scene->objects[o].path);
            }
            free(layer->scene);
        }
        if(layer->canvas != NULL) lv_obj_delete(layer->canvas);
        if(layer->buf != NULL) lv_draw_buf_destroy(layer->buf);
    }
    if(screen->display != NULL) lv_display_delete(screen->display);
    free(screen->display_buf);
    free(screen);
}

int mm_screen_width(const mm_screen_t *screen) { return screen ? screen->width : 0; }
int mm_screen_height(const mm_screen_t *screen) { return screen ? screen->height : 0; }
double mm_screen_last_render_ms(const mm_screen_t *screen)
{
    return screen ? screen->last_render_ms : 0.0;
}

/* -- the command set ------------------------------------------------------- */

int mm_screen_layer_create(mm_screen_t *screen, const char *name, int width, int height,
                           int x, int y, int z, int visible, double opacity,
                           int interactive, const char *hit_id)
{
    if(screen == NULL || name == NULL || width <= 0 || height <= 0) {
        set_error("bad arguments to layer_create");
        return -1;
    }
    if(find_layer(screen, name) != NULL) {
        set_error("layer %s already exists", name);
        return -1;
    }
    if(screen->layer_count >= MM_SCREEN_MAX_LAYERS) {
        set_error("too many layers (limit %d)", MM_SCREEN_MAX_LAYERS);
        return -1;
    }

    mm_screen_layer_t *layer = &screen->layers[screen->layer_count];
    memset(layer, 0, sizeof(*layer));
    snprintf(layer->name, sizeof(layer->name), "%s", name);
    if(hit_id != NULL) snprintf(layer->hit_id, sizeof(layer->hit_id), "%s", hit_id);
    layer->width = width;
    layer->height = height;
    layer->x = x;
    layer->y = y;
    layer->z = z;
    layer->visible = visible;
    layer->interactive = interactive;
    layer->opacity = opacity;

    layer->buf = lv_draw_buf_create(width, height, LV_COLOR_FORMAT_ARGB8888, 0);
    if(layer->buf == NULL) {
        set_error("could not allocate layer %s (%dx%d)", name, width, height);
        return -1;
    }
    lv_draw_buf_clear(layer->buf, NULL);

    layer->canvas = lv_canvas_create(lv_display_get_screen_active(screen->display));
    lv_canvas_set_draw_buf(layer->canvas, layer->buf);
    lv_obj_set_pos(layer->canvas, x, y);
    lv_obj_set_style_opa(layer->canvas, (lv_opa_t)(opacity * 255.0 + 0.5), 0);
    if(!visible) lv_obj_add_flag(layer->canvas, LV_OBJ_FLAG_HIDDEN);

    screen->layer_count++;
    reorder(screen);
    return 0;
}

int mm_screen_layer_delete(mm_screen_t *screen, const char *name)
{
    mm_screen_layer_t *layer = find_layer(screen, name);
    if(layer == NULL) return 0;                 /* deleting the absent is fine */
    if(layer->scene != NULL) {
        for(int o = 0; o < layer->scene->object_count; o++) {
            mm_path_destroy(layer->scene->objects[o].path);
        }
        free(layer->scene);
    }
    lv_obj_delete(layer->canvas);
    lv_draw_buf_destroy(layer->buf);

    const int index = (int)(layer - screen->layers);
    for(int i = index; i < screen->layer_count - 1; i++) screen->layers[i] = screen->layers[i + 1];
    screen->layer_count--;
    return 0;
}

int mm_screen_layer_clear(mm_screen_t *screen, const char *name)
{
    mm_screen_layer_t *layer = find_layer(screen, name);
    if(layer == NULL) {
        set_error("no layer %s", name ? name : "(null)");
        return -1;
    }
    lv_draw_buf_clear(layer->buf, NULL);
    lv_obj_invalidate(layer->canvas);
    return 0;
}

int mm_screen_layer_visible(mm_screen_t *screen, const char *name, int visible)
{
    mm_screen_layer_t *layer = find_layer(screen, name);
    if(layer == NULL) {
        set_error("no layer %s", name ? name : "(null)");
        return -1;
    }
    layer->visible = visible;
    if(visible) lv_obj_remove_flag(layer->canvas, LV_OBJ_FLAG_HIDDEN);
    else lv_obj_add_flag(layer->canvas, LV_OBJ_FLAG_HIDDEN);
    return 0;
}

int mm_screen_layer_position(mm_screen_t *screen, const char *name, int x, int y)
{
    mm_screen_layer_t *layer = find_layer(screen, name);
    if(layer == NULL) {
        set_error("no layer %s", name ? name : "(null)");
        return -1;
    }
    layer->x = x;
    layer->y = y;
    lv_obj_set_pos(layer->canvas, x, y);
    return 0;
}

int mm_screen_layer_z(mm_screen_t *screen, const char *name, int z)
{
    mm_screen_layer_t *layer = find_layer(screen, name);
    if(layer == NULL) {
        set_error("no layer %s", name ? name : "(null)");
        return -1;
    }
    layer->z = z;
    reorder(screen);
    return 0;
}

int mm_screen_layer_opacity(mm_screen_t *screen, const char *name, double opacity)
{
    mm_screen_layer_t *layer = find_layer(screen, name);
    if(layer == NULL) {
        set_error("no layer %s", name ? name : "(null)");
        return -1;
    }
    layer->opacity = opacity;
    lv_obj_set_style_opa(layer->canvas, (lv_opa_t)(opacity * 255.0 + 0.5), 0);
    return 0;
}

int mm_screen_layer_interactive(mm_screen_t *screen, const char *name, int interactive,
                                const char *hit_id)
{
    mm_screen_layer_t *layer = find_layer(screen, name);
    if(layer == NULL) {
        set_error("no layer %s", name ? name : "(null)");
        return -1;
    }
    layer->interactive = interactive;
    layer->hit_id[0] = '\0';
    if(hit_id != NULL) snprintf(layer->hit_id, sizeof(layer->hit_id), "%s", hit_id);
    return 0;
}

int mm_screen_layer_blit(mm_screen_t *screen, const char *name, const uint8_t *rgba,
                         int width, int height, int x, int y)
{
    mm_screen_layer_t *layer = find_layer(screen, name);
    if(layer == NULL) {
        set_error("no layer %s", name ? name : "(null)");
        return -1;
    }
    if(rgba == NULL || width <= 0 || height <= 0) {
        set_error("bad bitmap for layer %s", layer->name);
        return -1;
    }

    const int x0 = x < 0 ? 0 : x;
    const int y0 = y < 0 ? 0 : y;
    const int x1 = (x + width  > layer->width)  ? layer->width  : x + width;
    const int y1 = (y + height > layer->height) ? layer->height : y + height;
    if(x1 <= x0 || y1 <= y0) return 0;

    const uint32_t stride = layer->buf->header.stride;
    for(int row = y0; row < y1; row++) {
        uint8_t *dst = layer->buf->data + (size_t)row * stride + (size_t)x0 * 4;
        const uint8_t *src = rgba + ((size_t)(row - y) * width + (size_t)(x0 - x)) * 4;
        /* RGBA in, ARGB8888 (B,G,R,A in memory) out -- the same single colour
         * conversion drm_screen does in its backend adapter, in the same place:
         * at the boundary, once. */
        for(int col = x0; col < x1; col++) {
            dst[0] = src[2];
            dst[1] = src[1];
            dst[2] = src[0];
            dst[3] = src[3];
            dst += 4;
            src += 4;
        }
    }
    lv_obj_invalidate(layer->canvas);
    return 0;
}

int mm_screen_layer_scene(mm_screen_t *screen, const char *name, const char *scene_json)
{
    mm_screen_layer_t *layer = find_layer(screen, name);
    if(layer == NULL) {
        set_error("no layer %s", name ? name : "(null)");
        return -1;
    }
    if(layer->scene != NULL) {
        for(int o = 0; o < layer->scene->object_count; o++) {
            mm_path_destroy(layer->scene->objects[o].path);
        }
        free(layer->scene);
        layer->scene = NULL;
    }
    if(scene_json == NULL) return 0;            /* clearing the scene is legal */

    mm_scene_t *scene = calloc(1, sizeof(*scene));
    if(scene == NULL) {
        set_error("out of memory");
        return -1;
    }
    if(!mm_scene_from_json(scene_json, scene, g_error, sizeof(g_error))) {
        free(scene);
        return -1;
    }
    layer->scene = scene;
    layer->ripple_count = 0;
    return 0;
}

int mm_screen_layer_offset(mm_screen_t *screen, const char *name, double offset_ms)
{
    mm_screen_layer_t *layer = find_layer(screen, name);
    if(layer == NULL) {
        set_error("no layer %s", name ? name : "(null)");
        return -1;
    }
    layer->time_offset = offset_ms;
    return 0;
}

int mm_screen_layer_ripple(mm_screen_t *screen, const char *name, double origin,
                           double start_scene_time, double amplitude, double wavelength,
                           double speed, double life_ms, double width)
{
    mm_screen_layer_t *layer = find_layer(screen, name);
    if(layer == NULL) {
        set_error("no layer %s", name ? name : "(null)");
        return -1;
    }
    if(layer->ripple_count >= MM_MAX_RIPPLES) {
        for(int i = 1; i < MM_MAX_RIPPLES; i++) layer->ripples[i - 1] = layer->ripples[i];
        layer->ripple_count = MM_MAX_RIPPLES - 1;
    }
    mm_ripple_t *ripple = &layer->ripples[layer->ripple_count++];
    ripple->origin = (float)origin;
    ripple->start = (float)start_scene_time;
    ripple->amplitude = (float)amplitude;
    ripple->wavelength = (float)wavelength;
    ripple->speed = (float)speed;
    ripple->life_ms = (float)life_ms;
    ripple->width = (float)width;
    return 0;
}

const char *mm_screen_hit_test(const mm_screen_t *screen, int x, int y)
{
    if(screen == NULL) return NULL;
    const mm_screen_layer_t *hit = NULL;
    for(int i = 0; i < screen->layer_count; i++) {
        const mm_screen_layer_t *layer = &screen->layers[i];
        if(!layer->visible || !layer->interactive) continue;
        if(x < layer->x || x >= layer->x + layer->width) continue;
        if(y < layer->y || y >= layer->y + layer->height) continue;
        if(hit == NULL || layer->z >= hit->z) hit = layer;
    }
    return hit != NULL && hit->hit_id[0] != '\0' ? hit->hit_id : NULL;
}

/* -- render ---------------------------------------------------------------- */

int mm_screen_render(mm_screen_t *screen, double scene_time_ms)
{
    if(screen == NULL) {
        set_error("no screen");
        return -1;
    }
    const double started = now_ms();

    for(int i = 0; i < screen->layer_count; i++) {
        mm_screen_layer_t *layer = &screen->layers[i];
        if(layer->scene == NULL || !layer->visible) continue;

        /* Each layer keeps its own clock. With no offset -- the ordinary case
         * -- this is the screen's time and every layer is the same picture. */
        const float layer_time = (float)(scene_time_ms - layer->time_offset);
        mm_evaluate(layer->scene, layer_time);

        mm_ripple_t live[MM_MAX_RIPPLES];
        int live_count = 0;
        for(int r = 0; r < layer->ripple_count; r++) {
            if(mm_ripple_active(&layer->ripples[r], layer_time)) {
                live[live_count++] = layer->ripples[r];
            }
        }

        /* Transparent, not black: a scene layer composites over what is under
         * it, the same as a bitmap layer with alpha. */
        lv_canvas_fill_bg(layer->canvas, lv_color_hex(0x000000), LV_OPA_TRANSP);
        lv_layer_t draw;
        lv_canvas_init_layer(layer->canvas, &draw);
        mm_render_scene(&draw, layer->scene, layer->width, layer->height,
                        live, live_count, layer_time);
        lv_canvas_finish_layer(layer->canvas, &draw);
        lv_obj_invalidate(layer->canvas);
    }

    /* Redraw the dirty areas and present them now, rather than when LVGL's
     * refresh timer next comes round: the caller asked for the picture at
     * `scene_time_ms`, and must get that one, not the one before it. On DRM
     * this is a page flip, with no frame crossing a process boundary. */
    lv_refr_now(screen->display);
    screen->last_render_ms = now_ms() - started;
    return 0;
}

int mm_screen_snapshot(mm_screen_t *screen, uint8_t *out, size_t out_size)
{
    if(screen == NULL || out == NULL) {
        set_error("bad arguments to snapshot");
        return -1;
    }
    if(screen->display_buf == NULL) {
        set_error("snapshot needs the memory backend");
        return -1;
    }
    const size_t needed = (size_t)screen->width * screen->height * 4;
    if(out_size < needed) {
        set_error("output buffer too small: %zu < %zu", out_size, needed);
        return -1;
    }
    const uint8_t *src = screen->display_buf;
    for(size_t i = 0; i < needed; i += 4) {
        out[i + 0] = src[i + 2];
        out[i + 1] = src[i + 1];
        out[i + 2] = src[i + 0];
        out[i + 3] = 255;              /* the screen is opaque; X, not A */
    }
    return 0;
}
