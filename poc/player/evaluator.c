#include "evaluator.h"

#include "easing.h"

float mm_animation_value(const mm_animation_t *animation, float scene_time_ms)
{
    if(scene_time_ms <= animation->start_ms) return animation->from_value;
    if(animation->duration_ms <= 0.0f ||
       scene_time_ms >= animation->start_ms + animation->duration_ms) {
        return animation->to_value;
    }
    const float p = (scene_time_ms - animation->start_ms) / animation->duration_ms;
    const float eased = mm_ease(animation->easing, p);
    return animation->from_value + (animation->to_value - animation->from_value) * eased;
}

static void apply(mm_object_t *object, mm_property_t property, float value)
{
    switch(property) {
        case MM_PROP_OPACITY:         object->opacity = value; break;
        case MM_PROP_PROGRESS:        object->progress = value; break;
        case MM_PROP_VISIBLE:         object->visible = value != 0.0f; break;
        case MM_PROP_TRANSFORM_TX:    object->transform.tx = value; break;
        case MM_PROP_TRANSFORM_TY:    object->transform.ty = value; break;
        case MM_PROP_TRANSFORM_SCALE: object->transform.scale = value; break;
        case MM_PROP_DEFORM_AMPLITUDE:  object->deform.amplitude = value; break;
        case MM_PROP_DEFORM_WAVELENGTH: object->deform.wavelength = value; break;
        case MM_PROP_DEFORM_PHASE:      object->deform.phase = value; break;
        case MM_PROP_DEFORM_SWAY:       object->deform.sway = value; break;
        default: break;
    }
}

void mm_evaluate(mm_scene_t *scene, float scene_time_ms)
{
    /* Start from the authored values every time. The evaluator writes state in
     * place for the device's sake, so this reset is what keeps it a pure
     * function of the time: seeking backwards must give the same picture as
     * arriving forwards, and a property whose animation has not started yet
     * must show what the scene said, not what the last frame left. */
    for(int i = 0; i < scene->object_count; i++) {
        mm_object_t *object = &scene->objects[i];
        object->opacity = object->authored.opacity;
        object->progress = object->authored.progress;
        object->visible = object->authored.visible;
        object->transform = object->authored.transform;
        object->deform = object->authored.deform;
    }

    /* The animation that applies to a property is the last one, in declaration
     * order, whose start has been reached (decision 0006). One that has not
     * started must not impose its `from` value on an earlier phase, which is
     * what makes a phase list -- build up, then decay -- work at all. */
    for(int i = 0; i < scene->animation_count; i++) {
        const mm_animation_t *animation = &scene->animations[i];
        if(animation->target < 0 || animation->target >= scene->object_count) continue;
        if(animation->start_ms > scene_time_ms) continue;

        bool superseded = false;
        for(int j = i + 1; j < scene->animation_count; j++) {
            const mm_animation_t *later = &scene->animations[j];
            if(later->target == animation->target &&
               later->property == animation->property &&
               later->start_ms <= scene_time_ms) {
                superseded = true;
                break;
            }
        }
        if(superseded) continue;

        apply(&scene->objects[animation->target], animation->property,
              mm_animation_value(animation, scene_time_ms));
    }
}
