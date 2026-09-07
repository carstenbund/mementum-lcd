/**
 * Normative easing curves -- the C half of the contract.
 *
 * The formulae and the fixed vectors live in `mementum_node/core/easing.py`;
 * this file must reproduce them exactly, and `tests/test_c_player.py` checks it
 * against the same vectors. If the Pi and the ESP32 interpolate differently
 * they diverge visibly with perfectly synchronised clocks, and it looks exactly
 * like a sync bug while being nothing of the kind (proposal §14, risk R6).
 */
#ifndef MM_EASING_H
#define MM_EASING_H

#include "scene_model.h"

mm_easing_t mm_easing_from_name(const char *name);
float mm_ease(mm_easing_t easing, float p);

#endif /* MM_EASING_H */
