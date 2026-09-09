/**
 * `drm_screen`, implemented on LVGL.
 *
 * `drm_screen` owns named RGBA layers, composites them by z, and pushes one
 * frame to `drm_display`. That vocabulary is good and stays; what changes is
 * who does the work. Here a layer is an LVGL object, composition is LVGL's own
 * (dirty-area, not whole-frame), and the frame reaches the panel through
 * whatever display driver LVGL was built with -- DRM/KMS on this host.
 *
 * The gain is not in `blit`: a bitmap is a bitmap either way. It is that a
 * layer can hold a *scene* instead of pixels, and then the picture is drawn
 * from primitives at the panel's own resolution, with nothing rasterised,
 * composited or colour-converted on the way.
 *
 *     drm_screen (numpy)      layer = RGBA array   -> blend all -> drm_display
 *     this file  (LVGL)       layer = lv_obj_t     -> LVGL      -> DRM/KMS
 *                             layer = scene        -> paths     -> DRM/KMS
 *
 * Every call is a command in `drm_screen.commands` under a different name:
 * CreateLayer, PlaceRawBuffer, SetPosition, SetZ, ShowLayer/HideLayer,
 * SetPointer, hit_test. Nothing new was invented except `layer_scene`.
 */
#ifndef MM_SCREEN_H
#define MM_SCREEN_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct mm_screen mm_screen_t;

/** `backend` is "drm" for a real panel or "memory" for a readable buffer.
 *  With "drm", width/height may be 0 to take the display's own mode. */
mm_screen_t *mm_screen_create(int width, int height, const char *backend);
void mm_screen_destroy(mm_screen_t *screen);

int mm_screen_width(const mm_screen_t *screen);
int mm_screen_height(const mm_screen_t *screen);

/* -- layers: the drm_screen command set ------------------------------------ */

int mm_screen_layer_create(mm_screen_t *screen, const char *name, int width, int height,
                           int x, int y, int z, int visible, double opacity,
                           int interactive, const char *hit_id);
int mm_screen_layer_delete(mm_screen_t *screen, const char *name);
int mm_screen_layer_clear(mm_screen_t *screen, const char *name);
int mm_screen_layer_visible(mm_screen_t *screen, const char *name, int visible);
int mm_screen_layer_position(mm_screen_t *screen, const char *name, int x, int y);
int mm_screen_layer_z(mm_screen_t *screen, const char *name, int z);
int mm_screen_layer_opacity(mm_screen_t *screen, const char *name, double opacity);
int mm_screen_layer_interactive(mm_screen_t *screen, const char *name, int interactive,
                                const char *hit_id);

/** PlaceRawBuffer: RGBA8888 bytes into a layer at (x, y), clipped. */
int mm_screen_layer_blit(mm_screen_t *screen, const char *name, const uint8_t *rgba,
                         int width, int height, int x, int y);

/** The primitive path: the layer holds a scene and is drawn from paths, at the
 *  panel's resolution, every time the screen is rendered. */
int mm_screen_layer_scene(mm_screen_t *screen, const char *name, const char *scene_json);

/** Shift a scene layer's own clock. The screen is rendered at one time; a
 *  layer with an offset is evaluated at `scene_time - offset`, which is what
 *  lets units on one wall start one after another, or hold different moments
 *  of the same scene, without anyone rendering twice. */
int mm_screen_layer_offset(mm_screen_t *screen, const char *name, double offset_ms);

/** A ripple on a scene layer -- local excitement, exactly as in the player. */
int mm_screen_layer_ripple(mm_screen_t *screen, const char *name, double origin,
                           double start_scene_time, double amplitude, double wavelength,
                           double speed, double life_ms, double width);

/** Topmost interactive layer covering the point, or NULL. Mutates nothing. */
const char *mm_screen_hit_test(const mm_screen_t *screen, int x, int y);

/* -- the render loop ------------------------------------------------------- */

/** Composite and present. Scene layers are evaluated at `scene_time_ms` first.
 *  Returns 0, or -1 with `mm_screen_error()` set. */
int mm_screen_render(mm_screen_t *screen, double scene_time_ms);

/** The last presented frame as RGBA8888. "memory" backend only. */
int mm_screen_snapshot(mm_screen_t *screen, uint8_t *out, size_t out_size);

/** Milliseconds spent inside the last mm_screen_render(). */
double mm_screen_last_render_ms(const mm_screen_t *screen);

const char *mm_screen_error(void);

#ifdef __cplusplus
}
#endif

#endif /* MM_SCREEN_H */
