/**
 * The player, as a library (implementation plan §3.7).
 *
 * The same C that runs on the device, callable from the host: load a scene,
 * ask for the picture at a scene time, get an RGBA frame back. That is the
 * whole surface, because it is the whole job.
 *
 * The buffer handed back is RGBA8888 in memory order, matching
 * `mementum_node.core.framebuffer.Frame` -- one colour conversion, here at the
 * boundary, and nowhere else (invariant 1).
 */
#ifndef MM_PLAYER_H
#define MM_PLAYER_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct mm_player mm_player_t;

/** Idempotent; safe to call from every binding. */
int mm_player_init(void);

/** Load a scene package for a display of the given size. NULL on refusal. */
mm_player_t *mm_player_load(const char *scene_json, int width, int height);

void mm_player_destroy(mm_player_t *player);

/** Evaluate at `scene_time_ms` and composite. Returns 0 on success.
 *  `out` must hold width * height * 4 bytes. */
int mm_player_render(mm_player_t *player, double scene_time_ms, uint8_t *out, size_t out_size);

/** Start a ripple on this unit. Runtime state, not scene content: it comes
 *  from a finger on this panel or from the sequencer relaying somebody else's.
 *  The oldest is dropped once the unit is holding its limit. */
int mm_player_add_ripple(mm_player_t *player, double origin, double start_scene_time,
                         double amplitude, double wavelength, double speed,
                         double life_ms, double width);

/** How many ripples this player is currently holding. */
int mm_player_ripple_count(const mm_player_t *player);

/** Discard them all. */
void mm_player_clear_ripples(mm_player_t *player);

/* -- the schedule a device holds (schedule.h) ------------------------------ */

/** The firmware's schedule logic, reachable from the host so the lines the
 *  ESP32 runs are the lines the tests run. Opaque here; see schedule.h. */
int    mm_schedule_size(void);
void   mm_schedule_reset(void *schedule);
int    mm_schedule_take(void *schedule, unsigned int seq, double display_at,
                        int scene_id, const char *scene_hash, int duration_ms);
double mm_schedule_at(const void *schedule, double now);
int    mm_schedule_visible(const void *schedule, double now);
int    mm_schedule_over(const void *schedule, double now);

/** Why the last call failed. Never NULL. */
const char *mm_player_error(void);

/* -- introspection, for the conformance tests ------------------------------ */

double mm_player_scene_duration(const mm_player_t *player);
int    mm_player_object_count(const mm_player_t *player);
double mm_player_path_length(const mm_player_t *player, const char *object_id);
int    mm_player_subpath_count(const mm_player_t *player, const char *object_id);
/** The evaluated value of a property at a time, without rendering. This is what
 *  the easing and evaluator conformance checks compare against Python. */
double mm_player_property_at(const mm_player_t *player, const char *object_id,
                             const char *property, double scene_time_ms);
/** Direct access to the normative curves, for the fixed-vector test. */
double mm_player_ease(const char *easing, double p);

#ifdef __cplusplus
}
#endif

#endif /* MM_PLAYER_H */
