/**
 * The player, drawing straight to DRM — no bitmap in between.
 *
 * The question this answers: can LVGL stand where `drm_display` stands, so a
 * screen receives *primitives* rather than a rasterised buffer? A path is a few
 * hundred bytes; the same path rasterised is megabytes, and every frame of it
 * has to be composited and colour-converted on the way past.
 *
 * The swap is small because the player was never using LVGL as a UI toolkit —
 * no widgets, no object tree, just its draw API. Everything above the display
 * is unchanged; only where the frame goes is different:
 *
 *     headless   lv_display_create(w, h)   -> our own buffer -> caller
 *     DRM        lv_linux_drm_create()     -> a scanout buffer, page-flipped
 *
 * Build:  make -C poc/host-player drm
 * Run:    build/drm_player <scene.json> [seconds]
 *
 * It takes DRM master, so it will own the screen while it runs.
 */

#include "lvgl.h"
#include "player.h"
#include "scene_json.h"
#include "evaluator.h"
#include "render_lvgl.h"

#include "src/drivers/display/drm/lv_linux_drm.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <time.h>

static double now_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1000.0 + ts.tv_nsec / 1e6;
}

static char *slurp(const char *path)
{
    FILE *fh = fopen(path, "rb");
    if(fh == NULL) return NULL;
    fseek(fh, 0, SEEK_END);
    long size = ftell(fh);
    fseek(fh, 0, SEEK_SET);
    char *buffer = malloc((size_t)size + 1);
    if(buffer != NULL && fread(buffer, 1, (size_t)size, fh) == (size_t)size) buffer[size] = '\0';
    fclose(fh);
    return buffer;
}

int main(int argc, char **argv)
{
    if(argc < 2) {
        fprintf(stderr, "usage: %s <scene.json> [seconds] [capture-dir]\n", argv[0]);
        return 2;
    }
    const double seconds = argc > 2 ? atof(argv[2]) : 10.0;
    const char *capture = argc > 3 ? argv[3] : NULL;
    double next_capture = 0.0;
    int captured = 0;

    char *json = slurp(argv[1]);
    if(json == NULL) {
        fprintf(stderr, "cannot read %s\n", argv[1]);
        return 1;
    }

    lv_init();

    /* MM_MODE=1920x1080 asks the DRM backend for that mode instead of the first
     * one the connector lists. Must be set before the display is created. */
    const char *mode = getenv("MM_MODE");
    if(mode != NULL) setenv("LV_DRM_MODE", mode, 1);

    lv_display_t *display = lv_linux_drm_create();
    if(display == NULL) {
        fprintf(stderr, "no DRM display\n");
        return 1;
    }
    char *device = lv_linux_drm_find_device_path();
    if(lv_linux_drm_set_file(display, device ? device : "/dev/dri/card0", -1) != LV_RESULT_OK) {
        fprintf(stderr, "cannot open the DRM device (need to be in the video group,\n"
                        "and nothing else may hold DRM master)\n");
        return 1;
    }
    const int32_t width = lv_display_get_horizontal_resolution(display);
    const int32_t height = lv_display_get_vertical_resolution(display);
    printf("drm: %s, %dx%d\n", device ? device : "/dev/dri/card0", width, height);

    static mm_scene_t scene;
    char error[256] = "";
    if(!mm_scene_from_json(json, &scene, error, sizeof(error))) {
        fprintf(stderr, "scene: %s\n", error);
        return 1;
    }
    printf("scene: id %d, %dx%d design units, %d objects, %.1fs\n",
           scene.id, scene.width, scene.height, scene.object_count,
           scene.duration_ms / 1000.0);

    /* The canvas is the whole screen; the scene's fit policy maps the design
     * canvas onto it, exactly as it does on a panel. */
    lv_draw_buf_t *draw_buf = lv_draw_buf_create(width, height, LV_COLOR_FORMAT_ARGB8888, 0);
    lv_obj_t *canvas = lv_canvas_create(lv_display_get_screen_active(display));
    lv_canvas_set_draw_buf(canvas, draw_buf);

    const double started = now_ms();
    long frames = 0;
    double render_total = 0.0;
    for(;;) {
        const double elapsed = now_ms() - started;
        if(elapsed > seconds * 1000.0) break;

        const double scene_time = scene.duration_ms > 0
                                  ? fmod(elapsed, scene.duration_ms) : elapsed;
        const double before = now_ms();
        mm_evaluate(&scene, (float)scene_time);
        lv_canvas_fill_bg(canvas, lv_color_hex(0x000000), LV_OPA_COVER);
        lv_layer_t layer;
        lv_canvas_init_layer(canvas, &layer);
        mm_render_scene(&layer, &scene, width, height, NULL, 0, (float)scene_time);
        lv_canvas_finish_layer(canvas, &layer);
        render_total += now_ms() - before;

        lv_obj_invalidate(canvas);
        lv_timer_handler();          /* flushes the buffer to the scanout plane */
        frames++;

        /* What went to the scanout buffer, so the picture can be checked and
         * not merely the frame rate. */
        if(capture != NULL && elapsed >= next_capture) {
            char path[512];
            snprintf(path, sizeof(path), "%s/drm_%03d.raw", capture, captured);
            FILE *fh = fopen(path, "wb");
            if(fh != NULL) {
                fwrite(draw_buf->data, 1, (size_t)width * height * 4, fh);
                fclose(fh);
            }
            captured++;
            next_capture += 1000.0;
        }
    }

    const double wall = (now_ms() - started) / 1000.0;
    printf("frames %ld in %.1fs = %.1f fps, %.1f ms per render\n",
           frames, wall, frames / wall, render_total / (double)frames);
    if(capture != NULL) printf("captured %d frames of %dx%d to %s\n",
                               captured, width, height, capture);
    return 0;
}
