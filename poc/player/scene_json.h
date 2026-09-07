/**
 * JSON -> scene model (implementation plan §0.1 `scene_json.c`).
 *
 * cJSON is the parser because it is what ESP-IDF already ships, so the device
 * build gains no new dependency. Load time is measured separately from frame
 * time (proposal §17): this runs once, never in the frame loop.
 */
#ifndef MM_SCENE_JSON_H
#define MM_SCENE_JSON_H

#include "scene_model.h"

/** Parse a scene package. Returns false and fills `error` on refusal --
 *  a scene that does not parse must fail visibly, not partially load. */
bool mm_scene_from_json(const char *json, mm_scene_t *scene, char *error, size_t error_size);

#endif /* MM_SCENE_JSON_H */
