/**
 * Path geometry: parse `d`, split into subpaths, measure arc length.
 *
 * Two jobs beyond drawing.
 *
 * *Subpaths are first-class.* The dash pattern restarts at every moveTo
 * (measured in `probe_subpath.c`), so a single dash cannot express "one pen
 * trajectory across three strokes". The player has to sequence them itself,
 * which means it needs each subpath separately and its length.
 *
 * *Length is a fallback.* When the scene declares `length`, that is the number
 * used: the composer measures once and every player agrees. Measuring here is
 * for scenes that do not carry it.
 */
#ifndef MM_GEOMETRY_H
#define MM_GEOMETRY_H

#include "scene_model.h"
#include "ripple.h"

/* Refusal limits, not allocation sizes. A path is stored at exactly the size
 * its content needs (see `mm_path_create`); these are what the player declines
 * to draw rather than truncate -- a handwritten phrase runs to 15 segments in
 * its longest stroke and the signature to 12, so both are generous. */
#define MM_MAX_SEGMENTS 48

typedef struct {
    float x, y;
} mm_point_t;

typedef struct {
    mm_point_t c1, c2, to;      /**< every segment is a cubic; lines get collinear controls */
} mm_segment_t;

typedef struct {
    mm_point_t start;
    mm_segment_t *segments;     /**< into the path's own pool; never owned here */
    int segment_count;
    bool closed;
    float length;
} mm_subpath_t;

/**
 * A parsed path, stored at the size its content needs.
 *
 * One allocation holds the header, the subpath array and every segment, in
 * that order, so a path is one `malloc` and one `free` and the segments of a
 * subpath stay contiguous for the flattening loop. The saving is not a tidy:
 * fixed arrays for the worst case cost 75 KB per object, and a panel with
 * 520 KB of RAM cannot hold six of those (`docs/pico-bring-up.md`).
 */
typedef struct mm_path {
    mm_subpath_t *subpaths;     /**< into the same block as this header */
    int subpath_count;
    int segment_count;          /**< total across all subpaths */
    float length;
} mm_path_t;

/**
 * The parse target: fixed pools, sized for the refusal limits.
 *
 * Transient by design -- allocated by `mm_path_create`, filled by the parser,
 * copied into an exactly sized path, and freed before the caller sees
 * anything. It exists so that there is one grammar rather than a parser and a
 * separate counting pass that could disagree about what a `d` string means.
 */
typedef struct {
    mm_subpath_t subpaths[MM_MAX_SUBPATHS];
    mm_segment_t segments[MM_MAX_SUBPATHS * MM_MAX_SEGMENTS];
    int subpath_count;
    int segment_count;
    float length;
} mm_path_scratch_t;

/** Parse into a freshly allocated path of exactly the needed size, or NULL.
 *  Caller frees with `mm_path_destroy`. */
mm_path_t *mm_path_create(const char *d);
void mm_path_destroy(mm_path_t *path);

/** Parse an SVG `d` subset: M L H V C Q Z, absolute and relative, into the
 *  transient scratch. Returns false on anything else, rather than guessing. */
bool mm_path_parse(const char *d, mm_path_scratch_t *out);

/** Pack a parsed scratch into one exactly sized allocation. NULL on refusal. */
mm_path_t *mm_path_pack(const mm_path_scratch_t *scratch);

/** What this path costs, resident. Reported rather than estimated, because a
 *  budget for a 520 KB panel is only worth as much as its arithmetic. */
size_t mm_path_bytes(const mm_path_t *path);

/** Flattened arc length of one cubic segment. */
float mm_segment_length(mm_point_t from, const mm_segment_t *segment);

/* -- deformation ----------------------------------------------------------
 *
 * The sampling rule is part of the contract, not an implementation detail:
 * both players must sample a deformed path identically or the wave differs in
 * shape. Uniform steps of 2.0 design units along the undeformed arc length,
 * always including the final point -- the same rule as
 * `mementum_node/core/geometry.py`.
 */

#define MM_DEFORM_SAMPLE_STEP 2.0f
#define MM_MAX_POINTS 2048

/* Helix: the same travelling wave a quarter cycle apart in-plane and in depth,
 * projected back onto the design canvas. There is no 3D pipeline behind it --
 * one `z` per sample and one perspective divide -- and what sells the depth is
 * that nearer parts of the stroke are drawn thicker and brighter.
 *
 * These three numbers must match `mementum_node/core/geometry.py` exactly, or
 * the two players band the stroke differently and the ribbons disagree. */
#define MM_HELIX_FOCAL 520.0f
#define MM_HELIX_BANDS 8
#define MM_HELIX_SHADE_FAR 0.45f

float mm_perspective_scale(float z, float focal);
float mm_band_depth(int band);
int   mm_band_of(float t);

/** Flatten a subpath into a polyline. Returns the number of points written. */
int mm_subpath_flatten(const mm_subpath_t *subpath, mm_point_t *out, int max_points);

/** Trim a polyline to `length` of arc, then resample it uniformly and offset
 *  each sample perpendicular to the path by a travelling sine:
 *
 *      offset = amplitude * sin(2*pi * (distance / wavelength + phase))
 *
 *  `phase` is in cycles. Returns the number of points written. */
/** Trim, resample and deform. When `depth_out` is non-NULL it receives each
 *  sample's depth factor, 0 (far) to 1 (near) -- meaningful for a helix, and
 *  1.0 everywhere for a flat deformation. */
/** `distance_offset` is how far along the whole path this subpath begins, so a
 *  ripple sits on the pen's trajectory rather than restarting in every stroke. */
int mm_polyline_deform(const mm_point_t *points, int count, float length,
                       const mm_deform_t *deform, float centre_x, float centre_y,
                       const mm_ripple_t *ripples, int ripple_count, float scene_time_ms,
                       float distance_offset,
                       mm_point_t *out, float *depth_out, int max_points);

/** Trim a polyline to `length` of arc without deforming it. */
int mm_polyline_trim(const mm_point_t *points, int count, float length,
                     mm_point_t *out, int max_points);

#endif /* MM_GEOMETRY_H */
