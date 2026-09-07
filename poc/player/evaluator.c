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
        default: break;
    }
}

void mm_evaluate(mm_scene_t *scene, float scene_time_ms)
{
    /* Declaration order, so two animations on one property compose the same way
     * they do in the Python reference: the last one wins. */
    for(int i = 0; i < scene->animation_count; i++) {
        const mm_animation_t *animation = &scene->animations[i];
        if(animation->target < 0 || animation->target >= scene->object_count) continue;
        apply(&scene->objects[animation->target], animation->property,
              mm_animation_value(animation, scene_time_ms));
    }
}
