/**
 * state = evaluate(sceneTime) -- pure, and the only source of playback position
 * (proposal §10, §19).
 *
 * No accumulator, no frame counter, no dependence on call order. Seeking to a
 * time gives exactly the result of arriving there by stepping, which is what
 * makes a dropped frame, a missed PLAY and a late join the same problem.
 */
#ifndef MM_EVALUATOR_H
#define MM_EVALUATOR_H

#include "scene_model.h"

/** Resolve every animated property of `scene` at `scene_time_ms`, in place.
 *  In place is safe precisely because it is a pure function of the time: the
 *  animated fields are overwritten, never advanced. */
void mm_evaluate(mm_scene_t *scene, float scene_time_ms);

/** The value of one animation at a time. Exposed for the conformance tests. */
float mm_animation_value(const mm_animation_t *animation, float scene_time_ms);

#endif /* MM_EVALUATOR_H */
