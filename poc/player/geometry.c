#include "geometry.h"

#include <ctype.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

/* Flattening: one step per this many units of control-polygon length, clamped.
 * Matches mementum_node/core/geometry.py. The two implementations land about
 * 0.02 per cent apart on the test signature, which is invisible -- and moot
 * once the composer declares the length. */
#define UNITS_PER_STEP 3.0f
#define MIN_STEPS 6
#define MAX_STEPS 64

static float point_distance(mm_point_t a, mm_point_t b)
{
    return sqrtf((b.x - a.x) * (b.x - a.x) + (b.y - a.y) * (b.y - a.y));
}

static int steps_for(mm_point_t from, const mm_segment_t *segment)
{
    const float control = point_distance(from, segment->c1) +
                          point_distance(segment->c1, segment->c2) +
                          point_distance(segment->c2, segment->to);
    int steps = (int)(control / UNITS_PER_STEP) + 1;
    if(steps < MIN_STEPS) steps = MIN_STEPS;
    if(steps > MAX_STEPS) steps = MAX_STEPS;
    return steps;
}

float mm_segment_length(mm_point_t from, const mm_segment_t *segment)
{
    const int steps = steps_for(from, segment);
    float length = 0.0f;
    mm_point_t previous = from;
    for(int i = 1; i <= steps; i++) {
        const float t = (float)i / (float)steps;
        const float u = 1.0f - t;
        const float a = u * u * u, b = 3 * u * u * t, c = 3 * u * t * t, d = t * t * t;
        mm_point_t point = {
            a * from.x + b * segment->c1.x + c * segment->c2.x + d * segment->to.x,
            a * from.y + b * segment->c1.y + c * segment->c2.y + d * segment->to.y,
        };
        length += point_distance(previous, point);
        previous = point;
    }
    return length;
}

/* -- parsing ------------------------------------------------------------- */

typedef struct {
    const char *p;
} scanner_t;

static void skip_separators(scanner_t *s)
{
    while(*s->p && (isspace((unsigned char)*s->p) || *s->p == ',')) s->p++;
}

static bool read_number(scanner_t *s, float *out)
{
    skip_separators(s);
    char *end = NULL;
    const float value = strtof(s->p, &end);
    if(end == s->p) return false;
    s->p = end;
    *out = value;
    return true;
}

static bool read_point(scanner_t *s, mm_point_t *out)
{
    return read_number(s, &out->x) && read_number(s, &out->y);
}

static mm_subpath_t *begin_subpath(mm_path_t *path, mm_point_t start)
{
    if(path->subpath_count >= MM_MAX_SUBPATHS) return NULL;
    mm_subpath_t *subpath = &path->subpaths[path->subpath_count++];
    memset(subpath, 0, sizeof(*subpath));
    subpath->start = start;
    return subpath;
}

static bool push_cubic(mm_subpath_t *subpath, mm_point_t c1, mm_point_t c2, mm_point_t to)
{
    if(subpath == NULL || subpath->segment_count >= MM_MAX_SEGMENTS) return false;
    mm_segment_t *segment = &subpath->segments[subpath->segment_count++];
    segment->c1 = c1;
    segment->c2 = c2;
    segment->to = to;
    return true;
}

/** A line is a cubic whose controls sit on it -- one segment type downstream. */
static bool push_line(mm_subpath_t *subpath, mm_point_t from, mm_point_t to)
{
    mm_point_t c1 = { from.x + (to.x - from.x) / 3.0f, from.y + (to.y - from.y) / 3.0f };
    mm_point_t c2 = { from.x + (to.x - from.x) * 2.0f / 3.0f,
                      from.y + (to.y - from.y) * 2.0f / 3.0f };
    return push_cubic(subpath, c1, c2, to);
}

static bool push_quadratic(mm_subpath_t *subpath, mm_point_t from, mm_point_t control,
                           mm_point_t to)
{
    mm_point_t c1 = { from.x + 2.0f / 3.0f * (control.x - from.x),
                      from.y + 2.0f / 3.0f * (control.y - from.y) };
    mm_point_t c2 = { to.x + 2.0f / 3.0f * (control.x - to.x),
                      to.y + 2.0f / 3.0f * (control.y - to.y) };
    return push_cubic(subpath, c1, c2, to);
}

bool mm_path_parse(const char *d, mm_path_t *out)
{
    if(d == NULL || out == NULL) return false;
    memset(out, 0, sizeof(*out));

    scanner_t scanner = { d };
    mm_subpath_t *current = NULL;
    mm_point_t cursor = { 0.0f, 0.0f };
    mm_point_t start = { 0.0f, 0.0f };
    char command = 0;

    for(;;) {
        skip_separators(&scanner);
        if(*scanner.p == '\0') break;

        if(isalpha((unsigned char)*scanner.p)) {
            command = *scanner.p++;
        }
        else if(command == 0) {
            return false;               /* numbers before any command */
        }
        else if(command == 'M') {
            command = 'L';              /* implicit lineto after moveto */
        }
        else if(command == 'm') {
            command = 'l';
        }

        const bool relative = islower((unsigned char)command) != 0;
        const char op = (char)toupper((unsigned char)command);

        if(op == 'Z') {
            if(current != NULL && current->segment_count > 0) {
                push_line(current, cursor, start);
                current->closed = true;
            }
            cursor = start;
            current = NULL;
            continue;
        }

        mm_point_t point = { 0.0f, 0.0f };
        switch(op) {
            case 'M':
                if(!read_point(&scanner, &point)) return false;
                if(relative) { point.x += cursor.x; point.y += cursor.y; }
                current = begin_subpath(out, point);
                if(current == NULL) return false;
                cursor = start = point;
                break;

            case 'L':
                if(!read_point(&scanner, &point)) return false;
                if(relative) { point.x += cursor.x; point.y += cursor.y; }
                if(!push_line(current, cursor, point)) return false;
                cursor = point;
                break;

            case 'H':
                if(!read_number(&scanner, &point.x)) return false;
                point.y = cursor.y;
                if(relative) point.x += cursor.x;
                if(!push_line(current, cursor, point)) return false;
                cursor = point;
                break;

            case 'V':
                if(!read_number(&scanner, &point.y)) return false;
                point.x = cursor.x;
                if(relative) point.y += cursor.y;
                if(!push_line(current, cursor, point)) return false;
                cursor = point;
                break;

            case 'C': {
                mm_point_t c1, c2;
                if(!read_point(&scanner, &c1) || !read_point(&scanner, &c2) ||
                   !read_point(&scanner, &point)) {
                    return false;
                }
                if(relative) {
                    c1.x += cursor.x; c1.y += cursor.y;
                    c2.x += cursor.x; c2.y += cursor.y;
                    point.x += cursor.x; point.y += cursor.y;
                }
                if(!push_cubic(current, c1, c2, point)) return false;
                cursor = point;
                break;
            }

            case 'Q': {
                mm_point_t control;
                if(!read_point(&scanner, &control) || !read_point(&scanner, &point)) return false;
                if(relative) {
                    control.x += cursor.x; control.y += cursor.y;
                    point.x += cursor.x; point.y += cursor.y;
                }
                if(!push_quadratic(current, cursor, control, point)) return false;
                cursor = point;
                break;
            }

            default:
                return false;           /* arcs and smooth shorthands are not in v1 */
        }
    }

    /* Measure. Cheap, and only used when the scene does not declare a length. */
    out->length = 0.0f;
    for(int i = 0; i < out->subpath_count; i++) {
        mm_subpath_t *subpath = &out->subpaths[i];
        mm_point_t from = subpath->start;
        subpath->length = 0.0f;
        for(int j = 0; j < subpath->segment_count; j++) {
            subpath->length += mm_segment_length(from, &subpath->segments[j]);
            from = subpath->segments[j].to;
        }
        out->length += subpath->length;
    }
    return out->subpath_count > 0;
}
