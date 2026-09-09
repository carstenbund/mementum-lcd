#include "schedule.h"

#include <string.h>

void mm_schedule_clear(mm_schedule_t *schedule)
{
    if(schedule == NULL) return;
    memset(schedule, 0, sizeof(*schedule));
}

bool mm_schedule_adopt(mm_schedule_t *schedule, uint32_t seq, double display_at,
                       int scene_id, const char *scene_hash, int duration_ms)
{
    if(schedule == NULL) return false;

    /* Idempotent on seq: a push repeated (or a heartbeat carrying the schedule
     * we are already playing) must not restart the scene. This is what lets
     * the server re-send freely and the panel re-read the schedule as often as
     * it likes -- the recovery path costs nothing when nothing was missed. */
    if(schedule->active && schedule->seq == seq && schedule->scene_id == scene_id) {
        return false;
    }

    /* An older sequence number is a late packet, not a new instruction. */
    if(schedule->active && seq < schedule->seq) {
        return false;
    }

    const bool same_scene = schedule->active && schedule->scene_id == scene_id &&
                            (scene_hash == NULL ||
                             strncmp(schedule->scene_hash, scene_hash, MM_HASH_LEN - 1) == 0);

    schedule->seq = seq;
    schedule->display_at = display_at;
    schedule->scene_id = scene_id;
    schedule->duration_ms = duration_ms;
    schedule->active = true;
    /* The bytes we hold are still the bytes we hold: a new moment for the same
     * scene is not a reason to fetch it again. */
    schedule->loaded = same_scene ? schedule->loaded : false;
    if(scene_hash != NULL) {
        strncpy(schedule->scene_hash, scene_hash, MM_HASH_LEN - 1);
        schedule->scene_hash[MM_HASH_LEN - 1] = '\0';
    }
    else {
        schedule->scene_hash[0] = '\0';
    }
    return true;
}

double mm_schedule_time(const mm_schedule_t *schedule, double now)
{
    if(schedule == NULL || !schedule->active) return -1.0;
    return now - schedule->display_at;
}

bool mm_schedule_finished(const mm_schedule_t *schedule, double now)
{
    if(schedule == NULL || !schedule->active) return true;
    if(schedule->duration_ms <= 0) return false;      /* holds until told otherwise */
    return mm_schedule_time(schedule, now) > (double)schedule->duration_ms;
}

bool mm_schedule_showing(const mm_schedule_t *schedule, double now)
{
    const double t = mm_schedule_time(schedule, now);
    return t >= 0.0 && !mm_schedule_finished(schedule, now);
}
