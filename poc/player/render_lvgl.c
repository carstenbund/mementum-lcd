#include "render_lvgl.h"

#include "geometry.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

/* The design canvas is not the physical resolution (proposal §6): a node whose
 * display differs maps the canvas onto it with the scene's fit policy. */
typedef struct {
    float scale_x, scale_y;
    float offset_x, offset_y;
} viewport_t;

static viewport_t viewport_for(const mm_scene_t *scene, int out_w, int out_h)
{
    viewport_t viewport;
    const float sx = (float)out_w / (float)scene->width;
    const float sy = (float)out_h / (float)scene->height;

    if(strcmp(scene->fit, "fill") == 0) {
        viewport.scale_x = sx;
        viewport.scale_y = sy;
    }
    else if(strcmp(scene->fit, "cover") == 0) {
        viewport.scale_x = viewport.scale_y = sx > sy ? sx : sy;
    }
    else {
        viewport.scale_x = viewport.scale_y = sx < sy ? sx : sy;
    }
    viewport.offset_x = ((float)out_w - (float)scene->width * viewport.scale_x) / 2.0f;
    viewport.offset_y = ((float)out_h - (float)scene->height * viewport.scale_y) / 2.0f;
    return viewport;
}

static lv_fpoint_t to_device(const viewport_t *viewport, const mm_object_t *object,
                             float x, float y)
{
    const float ox = x * object->transform.scale + object->transform.tx;
    const float oy = y * object->transform.scale + object->transform.ty;
    lv_fpoint_t point = {
        viewport->offset_x + ox * viewport->scale_x,
        viewport->offset_y + oy * viewport->scale_y,
    };
    return point;
}

static lv_color_t to_lv_color(mm_color_t color)
{
    return lv_color_make(color.r, color.g, color.b);
}

static void render_rect(lv_layer_t *layer, const viewport_t *viewport,
                        const mm_object_t *object, lv_opa_t opa)
{
    lv_draw_vector_dsc_t *dsc = lv_draw_vector_dsc_create(layer);
    lv_vector_path_t *path = lv_vector_path_create(LV_VECTOR_PATH_QUALITY_HIGH);

    const lv_fpoint_t top_left = to_device(viewport, object, object->x, object->y);
    const lv_fpoint_t bottom_right =
        to_device(viewport, object, object->x + object->w, object->y + object->h);
    lv_vector_path_append_rectangle(path, top_left.x, top_left.y,
                                    bottom_right.x - top_left.x,
                                    bottom_right.y - top_left.y, 0, 0);

    lv_draw_vector_dsc_set_stroke_opa(dsc, LV_OPA_TRANSP);
    lv_draw_vector_dsc_set_fill_color(dsc, to_lv_color(object->fill));
    lv_draw_vector_dsc_set_fill_opa(dsc, opa);
    lv_draw_vector_dsc_add_path(dsc, path);
    lv_draw_vector(dsc);

    lv_vector_path_delete(path);
    lv_draw_vector_dsc_delete(dsc);
}

static void build_subpath(lv_vector_path_t *path, const viewport_t *viewport,
                          const mm_object_t *object, const mm_subpath_t *subpath)
{
    lv_fpoint_t start = to_device(viewport, object, subpath->start.x, subpath->start.y);
    lv_vector_path_move_to(path, &start);
    for(int i = 0; i < subpath->segment_count; i++) {
        const mm_segment_t *segment = &subpath->segments[i];
        lv_fpoint_t c1 = to_device(viewport, object, segment->c1.x, segment->c1.y);
        lv_fpoint_t c2 = to_device(viewport, object, segment->c2.x, segment->c2.y);
        lv_fpoint_t to = to_device(viewport, object, segment->to.x, segment->to.y);
        lv_vector_path_cubic_to(path, &c1, &c2, &to);
    }
    if(subpath->closed) lv_vector_path_close(path);
}

/**
 * Stroke a path revealed to `progress`.
 *
 * `progress` is the fraction of the total ordered drawing length: one pen
 * trajectory across every subpath in order, nothing drawn during the lift
 * between strokes. That cannot be expressed as a single dash pattern, because
 * the dash restarts at every moveTo (measured in probe_subpath.c) -- so the
 * sequencing is done here: completed strokes plain, the current one dashed, the
 * rest not drawn at all.
 */
static void render_path(lv_layer_t *layer, const viewport_t *viewport,
                        const mm_object_t *object, lv_opa_t opa)
{
    if(object->progress <= 0.0f) return;

    mm_path_t path_data;
    if(!mm_path_parse(object->d, &path_data)) return;

    const float scale = viewport->scale_x < viewport->scale_y ? viewport->scale_x
                                                              : viewport->scale_y;
    const float width = object->stroke_width * object->transform.scale * scale;
    const float progress = object->progress > 1.0f ? 1.0f : object->progress;

    /* Lengths are in design units; the dash pattern is in device units. */
    float total = object->length > 0.0f ? object->length : path_data.length;
    float target = total * progress;
    float walked = 0.0f;

    for(int i = 0; i < path_data.subpath_count; i++) {
        const float subpath_length = object->subpath_count == path_data.subpath_count
                                         ? object->subpath_length[i]
                                         : path_data.subpaths[i].length;
        if(walked >= target) break;                     /* not started yet: draw nothing */

        const bool whole = progress >= 1.0f || walked + subpath_length <= target;
        const float revealed = target - walked;

        lv_draw_vector_dsc_t *dsc = lv_draw_vector_dsc_create(layer);
        lv_vector_path_t *path = lv_vector_path_create(LV_VECTOR_PATH_QUALITY_HIGH);
        build_subpath(path, viewport, object, &path_data.subpaths[i]);

        lv_draw_vector_dsc_set_fill_opa(dsc, LV_OPA_TRANSP);
        lv_draw_vector_dsc_set_stroke_color(dsc, to_lv_color(object->stroke));
        lv_draw_vector_dsc_set_stroke_opa(dsc, opa);
        lv_draw_vector_dsc_set_stroke_width(dsc, width);
        lv_draw_vector_dsc_set_stroke_cap(dsc, LV_VECTOR_STROKE_CAP_ROUND);
        lv_draw_vector_dsc_set_stroke_join(dsc, LV_VECTOR_STROKE_JOIN_ROUND);

        if(whole) {
            /* No dash at all once a stroke is complete. A declared length even
             * slightly short of the renderer's own would otherwise leave the
             * last fraction permanently undrawn -- the signature never quite
             * finishing, at the moment someone is watching it finish. */
            lv_draw_vector_dsc_set_stroke_dash(dsc, NULL, 0);
        }
        else {
            float dashes[2] = { revealed * scale, subpath_length * scale * 2.0f };
            lv_draw_vector_dsc_set_stroke_dash(dsc, dashes, 2);
        }

        lv_draw_vector_dsc_add_path(dsc, path);
        lv_draw_vector(dsc);

        lv_vector_path_delete(path);
        lv_draw_vector_dsc_delete(dsc);

        walked += subpath_length;
    }
}

/**
 * Text through LVGL's own font assets.
 *
 * `font_id` resolves to a built-in Montserrat of the requested size, which is a
 * stand-in: the real answer is a preprocessed font asset carried on the asset
 * plane and addressed by content hash, so that every player rasterises the same
 * glyphs (proposal §9, §18). Until then, text is the one part of a scene where
 * this player and the Python reference are *expected* to differ.
 */
static const lv_font_t *font_for(const char *font_id)
{
    const char *dash = strrchr(font_id, '-');
    const int size = dash != NULL ? atoi(dash + 1) : 0;

    if(size >= 26) return &lv_font_montserrat_28;
    if(size >= 22) return &lv_font_montserrat_24;
    if(size >= 18) return &lv_font_montserrat_20;
    if(size >= 15) return &lv_font_montserrat_16;
    return &lv_font_montserrat_14;
}

static void render_text(lv_layer_t *layer, const viewport_t *viewport,
                        const mm_object_t *object, lv_opa_t opa)
{
    if(object->text[0] == '\0') return;

    lv_draw_label_dsc_t dsc;
    lv_draw_label_dsc_init(&dsc);
    dsc.text = object->text;
    dsc.font = font_for(object->font_id);
    dsc.color = to_lv_color(object->color);
    dsc.opa = opa;

    const lv_fpoint_t origin = to_device(viewport, object, object->x, object->y);
    lv_area_t area = {
        (int32_t)origin.x, (int32_t)origin.y,
        (int32_t)origin.x + 1000, (int32_t)origin.y + 200,
    };
    lv_draw_label(layer, &dsc, &area);
}

void mm_render_scene(lv_layer_t *layer, const mm_scene_t *scene, int out_w, int out_h)
{
    const viewport_t viewport = viewport_for(scene, out_w, out_h);

    for(int i = 0; i < scene->layer_count; i++) {
        const mm_layer_t *scene_layer = &scene->layers[scene->layer_order[i]];
        for(int j = 0; j < scene_layer->object_count; j++) {
            const mm_object_t *object = &scene->objects[scene_layer->object_index[j]];
            if(!object->visible) continue;

            float alpha = object->opacity;
            if(alpha <= 0.0f) continue;
            if(alpha > 1.0f) alpha = 1.0f;
            const lv_opa_t opa = (lv_opa_t)(alpha * 255.0f + 0.5f);

            switch(object->type) {
                case MM_OBJ_RECT: render_rect(layer, &viewport, object, opa); break;
                case MM_OBJ_PATH: render_path(layer, &viewport, object, opa); break;
                case MM_OBJ_TEXT: render_text(layer, &viewport, object, opa); break;
                default: break;
            }
        }
    }
}
