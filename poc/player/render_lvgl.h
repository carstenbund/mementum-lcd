/**
 * Evaluated scene state -> LVGL/ThorVG (implementation plan §0.1 `render_lvgl.c`).
 *
 * Above this file there is nothing but pure evaluation; below it is the display
 * driver. On the host that driver writes into a memory buffer, on the device
 * into a panel, and this layer does not know which.
 */
#ifndef MM_RENDER_LVGL_H
#define MM_RENDER_LVGL_H

#include "scene_model.h"
#include "ripple.h"

#include "lvgl.h"

/** Composite an *already evaluated* scene into a canvas layer. */
void mm_render_scene(lv_layer_t *layer, const mm_scene_t *scene, int out_w, int out_h,
                     const mm_ripple_t *ripples, int ripple_count, float scene_time_ms);

#endif /* MM_RENDER_LVGL_H */
