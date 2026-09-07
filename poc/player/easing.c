#include "easing.h"

#include <string.h>

mm_easing_t mm_easing_from_name(const char *name)
{
    if(name == NULL) return MM_EASE_LINEAR;
    if(strcmp(name, "linear") == 0)      return MM_EASE_LINEAR;
    if(strcmp(name, "ease-in") == 0)     return MM_EASE_IN;
    if(strcmp(name, "ease-out") == 0)    return MM_EASE_OUT;
    if(strcmp(name, "ease-in-out") == 0) return MM_EASE_IN_OUT;
    return MM_EASE_UNKNOWN;
}

float mm_ease(mm_easing_t easing, float p)
{
    if(p <= 0.0f) return 0.0f;
    if(p >= 1.0f) return 1.0f;

    switch(easing) {
        case MM_EASE_LINEAR:
            return p;
        case MM_EASE_IN:
            return p * p;
        case MM_EASE_OUT: {
            const float q = 1.0f - p;
            return 1.0f - q * q;
        }
        case MM_EASE_IN_OUT: {
            if(p < 0.5f) return 2.0f * p * p;
            const float q = 1.0f - p;
            return 1.0f - 2.0f * q * q;
        }
        default:
            return p;
    }
}
