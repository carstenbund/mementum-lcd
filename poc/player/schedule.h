/**
 * The schedule, as a device holds it -- `mementum-led`'s `DisplaySchedule`,
 * for a panel that draws scenes instead of scrolling strings.
 *
 * The firmware's flow is the same one the Python participant runs, and it is
 * three lines long:
 *
 *     a push arrives     -> mm_schedule_adopt()   (idempotent on seq)
 *     every frame        -> mm_schedule_time()    (now - displayAt, or < 0)
 *     nothing arrives    -> nothing changes
 *
 * Nothing accumulates and nothing is caught up: the picture is a pure function
 * of the shared clock, so a dropped frame self-corrects on the next one and a
 * panel that missed a push is put right by the next heartbeat.
 *
 * This file is plain C with no dependencies so the ESP-IDF/Arduino build and
 * the host tests compile the same lines.
 */
#ifndef MM_SCHEDULE_H
#define MM_SCHEDULE_H

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define MM_HASH_LEN 65

typedef struct {
    uint32_t seq;              /**< monotonic; supersedes older, dedups repeats */
    double   display_at;       /**< shared-clock moment the scene starts */
    int      scene_id;
    char     scene_hash[MM_HASH_LEN];
    int      duration_ms;      /**< 0 = plays until told otherwise */
    bool     active;
    bool     loaded;           /**< the scene itself is in hand */
} mm_schedule_t;

/** Forget everything. What STOP means. */
void mm_schedule_clear(mm_schedule_t *schedule);

/** Take a schedule, unless it is one we already have.
 *  Returns true if this changed anything -- which is when the scene has to be
 *  fetched, and the only time a panel does any work on arrival. */
bool mm_schedule_adopt(mm_schedule_t *schedule, uint32_t seq, double display_at,
                       int scene_id, const char *scene_hash, int duration_ms);

/** Scene time at `now`, or a negative number before it starts.
 *  This is the whole of the renderer's contract with the network. */
double mm_schedule_time(const mm_schedule_t *schedule, double now);

/** Has this schedule run out? A scene with no duration never does. */
bool mm_schedule_finished(const mm_schedule_t *schedule, double now);

/** Should a frame be drawn at all at `now`? */
bool mm_schedule_showing(const mm_schedule_t *schedule, double now);

#ifdef __cplusplus
}
#endif

#endif /* MM_SCHEDULE_H */
