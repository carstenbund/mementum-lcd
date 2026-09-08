/**
 * Touch ripples on the device (mirrors `mementum_node/core/ripple.py`).
 *
 * A ripple is runtime state, not scene content: it is induced by somebody
 * touching this unit, or by the sequencer telling this unit that somebody
 * touched another one. It never reaches the scene package or the shared
 * timeline — the animation is the work, and this is a second layer
 * (decision 0008).
 *
 * Like everything else the player draws, a ripple is a pure function of time:
 * its shape is `f(distance along the stroke, time since it started)`, so a
 * dropped frame costs nothing and a seek is exact.
 */
#ifndef MM_RIPPLE_H
#define MM_RIPPLE_H

#include <stdbool.h>

/** A unit holds only a few live ripples; the oldest is dropped. */
#define MM_MAX_RIPPLES 4

typedef struct {
    float origin;       /**< arc distance along the stroke where it started */
    float start;        /**< scene time at which it starts */
    float amplitude;    /**< design units, in-plane */
    float wavelength;
    float speed;        /**< design units per second, along the stroke */
    float life_ms;
    float width;        /**< how wide the travelling crest is */
} mm_ripple_t;

bool  mm_ripple_active(const mm_ripple_t *ripple, float scene_time_ms);
float mm_ripple_offset(const mm_ripple_t *ripple, float distance, float scene_time_ms);

/** Total offset from every live ripple. */
float mm_ripple_total(const mm_ripple_t *ripples, int count, float distance,
                      float scene_time_ms);

#endif /* MM_RIPPLE_H */
