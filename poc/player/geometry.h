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

#define MM_MAX_SEGMENTS 256

typedef struct {
    float x, y;
} mm_point_t;

typedef struct {
    mm_point_t c1, c2, to;      /**< every segment is a cubic; lines get collinear controls */
} mm_segment_t;

typedef struct {
    mm_point_t start;
    mm_segment_t segments[MM_MAX_SEGMENTS];
    int segment_count;
    bool closed;
    float length;
} mm_subpath_t;

typedef struct {
    mm_subpath_t subpaths[MM_MAX_SUBPATHS];
    int subpath_count;
    float length;
} mm_path_t;

/** Parse an SVG `d` subset: M L H V C Q Z, absolute and relative.
 *  Returns false on anything else, rather than guessing. */
bool mm_path_parse(const char *d, mm_path_t *out);

/** Flattened arc length of one cubic segment. */
float mm_segment_length(mm_point_t from, const mm_segment_t *segment);

#endif /* MM_GEOMETRY_H */
