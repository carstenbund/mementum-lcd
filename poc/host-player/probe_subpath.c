/**
 * Does the dash pattern run *across* subpaths, or restart at every moveTo?
 *
 * It decides how `progress` can be implemented for a multi-stroke path, which
 * is the semantics question the host protocol left open. Three separated
 * 100 px horizontal lines in one path, total length 300, drawn with a single
 * dash pattern of [150, 300] -- i.e. "reveal the first half".
 *
 *   continuous across subpaths -> line 1 whole, line 2 half, line 3 absent
 *   restarts per subpath       -> all three lines whole, because each 100 px
 *                                 subpath fits inside the 150 px dash
 *
 * The two outcomes are impossible to confuse, which is the point.
 */

#include "lvgl.h"

#include <stdio.h>
#include <stdint.h>

#define CANVAS_W 240
#define CANVAS_H 120

static void flush_cb(lv_display_t *display, const lv_area_t *area, uint8_t *px_map)
{
    LV_UNUSED(area);
    LV_UNUSED(px_map);
    lv_display_flush_ready(display);
}

/* Three subpaths, each 100 px long, 20 px apart vertically. */
static void build_three_strokes(lv_vector_path_t *path)
{
    for(int i = 0; i < 3; i++) {
        lv_fpoint_t from = { 20.0f, 30.0f + 25.0f * i };
        lv_fpoint_t to   = { 120.0f, 30.0f + 25.0f * i };
        lv_vector_path_move_to(path, &from);
        lv_vector_path_line_to(path, &to);
    }
}

int main(int argc, char **argv)
{
    const char *out = argc > 1 ? argv[1] : "probe_subpath.raw";

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
    lv_canvas_fill_bg(canvas, lv_color_hex(0x101014), LV_OPA_COVER);

    lv_layer_t layer;
    lv_canvas_init_layer(canvas, &layer);

    lv_draw_vector_dsc_t *dsc = lv_draw_vector_dsc_create(&layer);
    lv_vector_path_t *path = lv_vector_path_create(LV_VECTOR_PATH_QUALITY_HIGH);
    build_three_strokes(path);

    lv_draw_vector_dsc_set_fill_opa(dsc, LV_OPA_TRANSP);
    lv_draw_vector_dsc_set_stroke_color(dsc, lv_color_hex(0xe8e8f0));
    lv_draw_vector_dsc_set_stroke_opa(dsc, LV_OPA_COVER);
    lv_draw_vector_dsc_set_stroke_width(dsc, 3.0f);

    float dashes[2] = { 150.0f, 300.0f };   /* progress 0.5 of 300 px total */
    lv_draw_vector_dsc_set_stroke_dash(dsc, dashes, 2);
    lv_draw_vector_dsc_add_path(dsc, path);
    lv_draw_vector(dsc);

    lv_vector_path_delete(path);
    lv_draw_vector_dsc_delete(dsc);
    lv_canvas_finish_layer(canvas, &layer);

    FILE *fh = fopen(out, "wb");
    if(fh == NULL) return 1;
    fwrite(canvas_buf.data, 1, (size_t)CANVAS_W * CANVAS_H * 4, fh);
    fclose(fh);
    printf("probe_subpath: wrote %s\n", out);
    return 0;
}
