#include "ripple.h"

#include <math.h>

bool mm_ripple_active(const mm_ripple_t *ripple, float scene_time_ms)
{
    const float age = scene_time_ms - ripple->start;
    return age >= 0.0f && age <= ripple->life_ms;
}

float mm_ripple_offset(const mm_ripple_t *ripple, float distance, float scene_time_ms)
{
    const float age = scene_time_ms - ripple->start;
    if(age < 0.0f || age > ripple->life_ms) return 0.0f;

    const float travelled =
        fabsf(distance - ripple->origin) - ripple->speed * age / 1000.0f;
    const float envelope =
        expf(-(travelled * travelled) / (2.0f * ripple->width * ripple->width));
    const float decay = 1.0f - age / ripple->life_ms;

    return ripple->amplitude * decay * decay * envelope *
           sinf(2.0f * (float)M_PI * travelled / ripple->wavelength);
}

float mm_ripple_total(const mm_ripple_t *ripples, int count, float distance,
                      float scene_time_ms)
{
    float total = 0.0f;
    for(int i = 0; i < count; i++) {
        total += mm_ripple_offset(&ripples[i], distance, scene_time_ms);
    }
    return total;
}
