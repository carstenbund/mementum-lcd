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
#define MM_MAX_SUBPATHS    64
#define MM_MAX_ID          32
#define MM_MAX_TEXT        64
#define MM_MAX_PATH_DATA   8192

struct mm_path;

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
    MM_PROP_DEFORM_AMPLITUDE,
    MM_PROP_DEFORM_WAVELENGTH,
    MM_PROP_DEFORM_PHASE,
    MM_PROP_DEFORM_SWAY,
    MM_PROP_UNKNOWN
} mm_property_t;

typedef struct {
    uint8_t r, g, b;
} mm_color_t;

typedef struct {
    float tx, ty, scale;
} mm_transform_t;

typedef enum {
    MM_DEFORM_NONE = 0,
    MM_DEFORM_SINE,
    MM_DEFORM_HELIX,
    MM_DEFORM_UNKNOWN
} mm_deform_type_t;

/** A named deformation: SVG gives the geometry, the timeline moves it.
 *  `wavelength` and `amplitude` are design units, `phase` is cycles. */
typedef struct {
    mm_deform_type_t type;
    float amplitude;
    float wavelength;
    float phase;
    float focal;        /**< helix only: eye distance, in design units */
    /** helix only: how far the stroke moves *across* the picture, as against
     *  `amplitude`, which moves it *into* the picture. Separate because only
     *  the in-plane part can fold: an offset larger than the local radius of
     *  curvature makes the curve cross itself, which reads as unexplainable
     *  ripples in the tight parts of a stroke. */
    float sway;
} mm_deform_t;

/** The authored values of the animatable properties, as loaded.
 *
 *  The evaluator writes animated state in place, so it must start from the
 *  scene's own values every time rather than from whatever the last evaluation
 *  left behind. Without this, a property whose animation has not started yet
 *  keeps a stale value and the player accumulates state across frames -- which
 *  is precisely what §10 forbids, arriving through the back door. */
typedef struct {
    float opacity;
    float progress;
    bool visible;
    mm_transform_t transform;
    mm_deform_t deform;
} mm_authored_t;

typedef struct {
    char id[MM_MAX_ID];
    mm_object_type_t type;

    /* Animatable state. Written by the evaluator, never accumulated. */
    float opacity;
    float progress;
    bool visible;
    mm_transform_t transform;
    mm_deform_t deform;
    mm_authored_t authored;

    /* rect */
    float x, y, w, h;
    mm_color_t fill;

    /* path. Geometry is parsed once, at load: re-parsing `d` per frame would
     * put text parsing inside the frame loop, which §17 forbids, and the
     * parsed form is what every frame actually wants. The source string is not
     * kept — nothing downstream needs it. */
    struct mm_path *path;
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
