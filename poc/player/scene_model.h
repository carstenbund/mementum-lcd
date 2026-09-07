/**
 * The scene model, in C (implementation plan §0.1 `scene_model.h`).
 *
 * These are the structs the ESP32 player holds, and the host build compiles the
 * very same file. That is the point of §3.7: one evaluator, not two, so
 * C-versus-Python divergence is caught by construction rather than by
 * discipline (risk R6).
 *
 * Deliberately a subset -- rect, path, text, and the v1 animatable properties.
 * Fixed-capacity arrays rather than dynamic growth: an embedded player wants a
 * bounded memory story more than it wants generality, and Phase 1 will say what
 * the real bounds are.
 */
#ifndef MM_SCENE_MODEL_H
#define MM_SCENE_MODEL_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define MM_MAX_LAYERS      8
#define MM_MAX_OBJECTS     32
#define MM_MAX_ANIMATIONS  32
#define MM_MAX_SUBPATHS    16
#define MM_MAX_ID          32
#define MM_MAX_TEXT        64
#define MM_MAX_PATH_DATA   4096

typedef enum {
    MM_OBJ_RECT = 0,
    MM_OBJ_PATH,
    MM_OBJ_TEXT
} mm_object_type_t;

typedef enum {
    MM_EASE_LINEAR = 0,
    MM_EASE_IN,
    MM_EASE_OUT,
    MM_EASE_IN_OUT,
    MM_EASE_UNKNOWN
} mm_easing_t;

/** v1 animatable properties (proposal §10). */
typedef enum {
    MM_PROP_OPACITY = 0,
    MM_PROP_PROGRESS,
    MM_PROP_VISIBLE,
    MM_PROP_TRANSFORM_TX,
    MM_PROP_TRANSFORM_TY,
    MM_PROP_TRANSFORM_SCALE,
    MM_PROP_UNKNOWN
} mm_property_t;

typedef struct {
    uint8_t r, g, b;
} mm_color_t;

typedef struct {
    float tx, ty, scale;
} mm_transform_t;

typedef struct {
    char id[MM_MAX_ID];
    mm_object_type_t type;

    /* Animatable state. Written by the evaluator, never accumulated. */
    float opacity;
    float progress;
    bool visible;
    mm_transform_t transform;

    /* rect */
    float x, y, w, h;
    mm_color_t fill;

    /* path */
    char d[MM_MAX_PATH_DATA];
    mm_color_t stroke;
    float stroke_width;
    /* Arc length, from the scene when the composer provides it, otherwise
     * measured on load. Per-subpath because the dash pattern restarts at every
     * moveTo, so the player has to sequence the strokes itself. */
    float length;
    float subpath_length[MM_MAX_SUBPATHS];
    int subpath_count;
    bool length_declared;

    /* text */
    char text[MM_MAX_TEXT];
    char font_id[MM_MAX_ID];
    mm_color_t color;
} mm_object_t;

typedef struct {
    char id[MM_MAX_ID];
    int z;
    int object_index[MM_MAX_OBJECTS];
    int object_count;
} mm_layer_t;

typedef struct {
    int target;                 /**< index into mm_scene_t.objects */
    mm_property_t property;
    float start_ms;
    float duration_ms;
    float from_value;
    float to_value;
    mm_easing_t easing;
} mm_animation_t;

typedef struct {
    int version;
    int id;
    int width, height;
    char fit[16];
    float duration_ms;

    mm_object_t objects[MM_MAX_OBJECTS];
    int object_count;

    mm_layer_t layers[MM_MAX_LAYERS];
    int layer_count;
    int layer_order[MM_MAX_LAYERS];      /**< paint order, by z then declaration */

    mm_animation_t animations[MM_MAX_ANIMATIONS];
    int animation_count;
} mm_scene_t;

#endif /* MM_SCENE_MODEL_H */
