/**
 * Phase 0 task 0.3, steps 2 and 3 -- on the host, before any hardware.
 *
 * Two questions, in order:
 *
 *   2. Does LVGL's vector API render a path at all?
 *   3. Can a stroke be *revealed* progressively at runtime?  (risk R1)
 *
 * The answer to 3 is attempted the way the plan describes: a dash pattern of
 * [len*p, len] over a path whose length we precomputed ourselves, because
 * neither LVGL nor ThorVG exposes a path-length query. If this works, the IR
 * keeps `progress` as a runtime property. If it does not, `progress` becomes a
 * compile-time slice and the IR changes -- which must be reported before
 * Phase 1.
 *
 * Output is a raw RGBA dump per frame; the harness turns those into PNGs with
 * the same encoder it uses for its own frames, so nothing about the comparison
 * depends on the image library.
 */

#include "lvgl.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

#define CANVAS_W 480
#define CANVAS_H 320

/* The signature from poc/scenes/poc-signature.json, as cubic segments.
 * Hand-transcribed for the probe; the real player parses the JSON. */
typedef struct {
    float x1, y1, x2, y2, x, y;
} cubic_t;

static const float START_X = 40.0f, START_Y = 200.0f;

static const cubic_t SIGNATURE[] = {
    {  60, 140,  90, 130, 105, 175 },
    { 120, 220, 100, 252,  88, 236 },
    {  76, 220, 110, 180, 150, 176 },
    { 190, 172, 210, 200, 200, 220 },
    { 190, 240, 170, 230, 180, 205 },
    { 190, 180, 230, 164, 260, 176 },
    { 290, 188, 284, 216, 270, 220 },
    { 256, 224, 250, 204, 266, 190 },
    { 282, 176, 320, 170, 344, 186 },
    { 368, 202, 354, 236, 340, 226 },
    { 326, 216, 350, 164, 400, 160 },
    { 420, 158, 436, 166, 446, 180 },
};
#define SIGNATURE_SEGMENTS ((int)(sizeof(SIGNATURE) / sizeof(SIGNATURE[0])))

/* Arc length by flattening, matching mementum_node/core/geometry.py: the
 * dash reveal needs a length and nobody will give us one. */
static float cubic_length(float x0, float y0, const cubic_t *c, int steps)
{
    float length = 0.0f, px = x0, py = y0;
    for(int i = 1; i <= steps; i++) {
        float t = (float)i / (float)steps, u = 1.0f - t;
        float a = u * u * u, b = 3 * u * u * t, cc = 3 * u * t * t, d = t * t * t;
        float x = a * x0 + b * c->x1 + cc * c->x2 + d * c->x;
        float y = a * y0 + b * c->y1 + cc * c->y2 + d * c->y;
        length += sqrtf((x - px) * (x - px) + (y - py) * (y - py));
        px = x;
        py = y;
    }
    return length;
}

static float signature_length(void)
{
    float total = 0.0f, x = START_X, y = START_Y;
    for(int i = 0; i < SIGNATURE_SEGMENTS; i++) {
        total += cubic_length(x, y, &SIGNATURE[i], 64);
        x = SIGNATURE[i].x;
        y = SIGNATURE[i].y;
    }
    return total;
}

static void build_signature(lv_vector_path_t *path)
{
    lv_fpoint_t start = { START_X, START_Y };
    lv_vector_path_move_to(path, &start);
    for(int i = 0; i < SIGNATURE_SEGMENTS; i++) {
        lv_fpoint_t c1 = { SIGNATURE[i].x1, SIGNATURE[i].y1 };
        lv_fpoint_t c2 = { SIGNATURE[i].x2, SIGNATURE[i].y2 };
        lv_fpoint_t to = { SIGNATURE[i].x,  SIGNATURE[i].y  };
        lv_vector_path_cubic_to(path, &c1, &c2, &to);
    }
}

static void flush_cb(lv_display_t *display, const lv_area_t *area, uint8_t *px_map)
{
    LV_UNUSED(area);
    LV_UNUSED(px_map);
    lv_display_flush_ready(display);
}

static int dump_raw(const char *path, const uint8_t *data, size_t size)
{
    FILE *fh = fopen(path, "wb");
    if(fh == NULL) return -1;
    size_t written = fwrite(data, 1, size, fh);
    fclose(fh);
    return written == size ? 0 : -1;
}

int main(int argc, char **argv)
{
    const char *out_dir = argc > 1 ? argv[1] : ".";

    lv_init();

    static uint8_t display_buf[CANVAS_W * CANVAS_H * 4];
    lv_display_t *display = lv_display_create(CANVAS_W, CANVAS_H);
    lv_display_set_flush_cb(display, flush_cb);
    lv_display_set_buffers(display, display_buf, NULL, sizeof(display_buf),
                           LV_DISPLAY_RENDER_MODE_DIRECT);

    LV_DRAW_BUF_DEFINE_STATIC(canvas_buf, CANVAS_W, CANVAS_H, LV_COLOR_FORMAT_ARGB8888);
    LV_DRAW_BUF_INIT_STATIC(canvas_buf);

    lv_obj_t *canvas = lv_canvas_create(lv_screen_active());
    lv_canvas_set_draw_buf(canvas, &canvas_buf);

    const float total_length = signature_length();
    printf("probe: LVGL %d.%d.%d, path length %.3f px over %d cubic segments\n",
           LVGL_VERSION_MAJOR, LVGL_VERSION_MINOR, LVGL_VERSION_PATCH,
           (double)total_length, SIGNATURE_SEGMENTS);

    const float progresses[] = { 0.0f, 0.25f, 0.5f, 0.75f, 1.0f };
    const int frame_count = (int)(sizeof(progresses) / sizeof(progresses[0]));

    for(int i = 0; i < frame_count; i++) {
        const float progress = progresses[i];

        lv_canvas_fill_bg(canvas, lv_color_hex(0x101014), LV_OPA_COVER);

        lv_layer_t layer;
        lv_canvas_init_layer(canvas, &layer);

        lv_draw_vector_dsc_t *dsc = lv_draw_vector_dsc_create(&layer);
        lv_vector_path_t *path = lv_vector_path_create(LV_VECTOR_PATH_QUALITY_HIGH);
        build_signature(path);

        lv_draw_vector_dsc_set_fill_opa(dsc, LV_OPA_TRANSP);
        lv_draw_vector_dsc_set_stroke_color(dsc, lv_color_hex(0xe8e8f0));
        lv_draw_vector_dsc_set_stroke_opa(dsc, LV_OPA_COVER);
        lv_draw_vector_dsc_set_stroke_width(dsc, 3.0f);
        lv_draw_vector_dsc_set_stroke_cap(dsc, LV_VECTOR_STROKE_CAP_ROUND);
        lv_draw_vector_dsc_set_stroke_join(dsc, LV_VECTOR_STROKE_JOIN_ROUND);

        /* The reveal: draw len*p, then skip the rest of the path. */
        if(progress <= 0.0f) {
            lv_draw_vector_dsc_set_stroke_opa(dsc, LV_OPA_TRANSP);
        }
        else if(progress < 1.0f) {
            float dashes[2] = { total_length * progress, total_length };
            lv_draw_vector_dsc_set_stroke_dash(dsc, dashes, 2);
        }
        else {
            lv_draw_vector_dsc_set_stroke_dash(dsc, NULL, 0);
        }

        lv_draw_vector_dsc_add_path(dsc, path);
        lv_draw_vector(dsc);

        lv_vector_path_delete(path);
        lv_draw_vector_dsc_delete(dsc);
        lv_canvas_finish_layer(canvas, &layer);

        char out_path[512];
        snprintf(out_path, sizeof(out_path), "%s/probe_p%03d.raw",
                 out_dir, (int)(progress * 100.0f + 0.5f));
        if(dump_raw(out_path, canvas_buf.data, (size_t)CANVAS_W * CANVAS_H * 4) != 0) {
            fprintf(stderr, "probe: could not write %s\n", out_path);
            return 1;
        }
        printf("probe: progress %.2f -> %s\n", (double)progress, out_path);
    }

    printf("probe: done\n");
    return 0;
}
