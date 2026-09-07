#include "scene_json.h"

#include "easing.h"
#include "geometry.h"

#include "cJSON.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

static void fail(char *error, size_t size, const char *fmt, ...)
{
    if(error == NULL || size == 0) return;
    va_list args;
    va_start(args, fmt);
    vsnprintf(error, size, fmt, args);
    va_end(args);
}

static void copy_string(char *dst, size_t size, const cJSON *item, const char *fallback)
{
    const char *value = cJSON_IsString(item) ? item->valuestring : fallback;
    if(value == NULL) value = "";
    snprintf(dst, size, "%s", value);
}

static float number_or(const cJSON *object, const char *key, float fallback)
{
    const cJSON *item = cJSON_GetObjectItemCaseSensitive(object, key);
    return cJSON_IsNumber(item) ? (float)item->valuedouble : fallback;
}

static bool bool_or(const cJSON *object, const char *key, bool fallback)
{
    const cJSON *item = cJSON_GetObjectItemCaseSensitive(object, key);
    if(cJSON_IsBool(item)) return cJSON_IsTrue(item);
    return fallback;
}

/** `#rgb` / `#rrggbb`. Alpha lives in `opacity`, never in the colour. */
static mm_color_t parse_color(const cJSON *object, const char *key, mm_color_t fallback)
{
    const cJSON *item = cJSON_GetObjectItemCaseSensitive(object, key);
    if(!cJSON_IsString(item)) return fallback;

    const char *s = item->valuestring;
    if(*s == '#') s++;
    const size_t len = strlen(s);
    unsigned int r = 0, g = 0, b = 0;
    if(len == 6 && sscanf(s, "%2x%2x%2x", &r, &g, &b) == 3) {
        mm_color_t color = { (uint8_t)r, (uint8_t)g, (uint8_t)b };
        return color;
    }
    if(len == 3 && sscanf(s, "%1x%1x%1x", &r, &g, &b) == 3) {
        mm_color_t color = { (uint8_t)(r * 17), (uint8_t)(g * 17), (uint8_t)(b * 17) };
        return color;
    }
    return fallback;
}

static mm_property_t property_from_name(const char *name)
{
    if(name == NULL) return MM_PROP_UNKNOWN;
    if(strcmp(name, "opacity") == 0)          return MM_PROP_OPACITY;
    if(strcmp(name, "progress") == 0)         return MM_PROP_PROGRESS;
    if(strcmp(name, "visible") == 0)          return MM_PROP_VISIBLE;
    if(strcmp(name, "transform.tx") == 0)     return MM_PROP_TRANSFORM_TX;
    if(strcmp(name, "transform.ty") == 0)     return MM_PROP_TRANSFORM_TY;
    if(strcmp(name, "transform.scale") == 0)  return MM_PROP_TRANSFORM_SCALE;
    return MM_PROP_UNKNOWN;
}

static int find_object(const mm_scene_t *scene, const char *id)
{
    for(int i = 0; i < scene->object_count; i++) {
        if(strcmp(scene->objects[i].id, id) == 0) return i;
    }
    return -1;
}

static bool parse_object(const cJSON *raw, mm_object_t *object, char *error, size_t error_size)
{
    memset(object, 0, sizeof(*object));
    object->opacity = 1.0f;
    object->progress = 1.0f;
    object->visible = true;
    object->transform.scale = 1.0f;

    const cJSON *type = cJSON_GetObjectItemCaseSensitive(raw, "type");
    const cJSON *id = cJSON_GetObjectItemCaseSensitive(raw, "id");
    if(!cJSON_IsString(type) || !cJSON_IsString(id)) {
        fail(error, error_size, "object needs a string id and type");
        return false;
    }
    copy_string(object->id, sizeof(object->id), id, "");

    const mm_color_t black = { 0, 0, 0 };
    const mm_color_t white = { 255, 255, 255 };

    if(strcmp(type->valuestring, "rect") == 0) {
        object->type = MM_OBJ_RECT;
        object->x = number_or(raw, "x", 0.0f);
        object->y = number_or(raw, "y", 0.0f);
        object->w = number_or(raw, "w", 0.0f);
        object->h = number_or(raw, "h", 0.0f);
        object->fill = parse_color(raw, "fill", black);
    }
    else if(strcmp(type->valuestring, "path") == 0) {
        object->type = MM_OBJ_PATH;
        const cJSON *d = cJSON_GetObjectItemCaseSensitive(raw, "d");
        if(!cJSON_IsString(d)) {
            fail(error, error_size, "path %s has no d", object->id);
            return false;
        }
        copy_string(object->d, sizeof(object->d), d, "");
        object->stroke = parse_color(raw, "stroke", white);
        object->stroke_width = number_or(raw, "stroke_width", 1.0f);
        object->progress = number_or(raw, "progress", 1.0f);

        mm_path_t path;
        if(!mm_path_parse(object->d, &path)) {
            fail(error, error_size, "path %s: unsupported path data", object->id);
            return false;
        }
        /* The composer's length wins when it provides one: measured once,
         * agreed by every player, and no flattening pass on the device. */
        const cJSON *declared = cJSON_GetObjectItemCaseSensitive(raw, "length");
        object->length_declared = cJSON_IsNumber(declared);
        object->length = object->length_declared ? (float)declared->valuedouble : path.length;

        object->subpath_count = path.subpath_count;
        const cJSON *subpaths = cJSON_GetObjectItemCaseSensitive(raw, "subpaths");
        const bool subpaths_declared =
            cJSON_IsArray(subpaths) && cJSON_GetArraySize(subpaths) == path.subpath_count;
        for(int i = 0; i < path.subpath_count; i++) {
            object->subpath_length[i] =
                subpaths_declared ? (float)cJSON_GetArrayItem(subpaths, i)->valuedouble
                                  : path.subpaths[i].length;
        }
    }
    else if(strcmp(type->valuestring, "text") == 0) {
        object->type = MM_OBJ_TEXT;
        copy_string(object->text, sizeof(object->text),
                    cJSON_GetObjectItemCaseSensitive(raw, "content"), "");
        copy_string(object->font_id, sizeof(object->font_id),
                    cJSON_GetObjectItemCaseSensitive(raw, "font_id"), "");
        object->x = number_or(raw, "x", 0.0f);
        object->y = number_or(raw, "y", 0.0f);
        object->color = parse_color(raw, "color", white);
    }
    else {
        fail(error, error_size, "unsupported object type: %s", type->valuestring);
        return false;
    }

    object->opacity = number_or(raw, "opacity", 1.0f);
    object->visible = bool_or(raw, "visible", true);
    const cJSON *transform = cJSON_GetObjectItemCaseSensitive(raw, "transform");
    if(cJSON_IsObject(transform)) {
        object->transform.tx = number_or(transform, "tx", 0.0f);
        object->transform.ty = number_or(transform, "ty", 0.0f);
        object->transform.scale = number_or(transform, "scale", 1.0f);
    }
    return true;
}

static void order_layers(mm_scene_t *scene)
{
    for(int i = 0; i < scene->layer_count; i++) scene->layer_order[i] = i;
    /* Insertion sort by z, stable, so declaration order breaks ties exactly as
     * the Python reference does. */
    for(int i = 1; i < scene->layer_count; i++) {
        const int key = scene->layer_order[i];
        int j = i - 1;
        while(j >= 0 && scene->layers[scene->layer_order[j]].z > scene->layers[key].z) {
            scene->layer_order[j + 1] = scene->layer_order[j];
            j--;
        }
        scene->layer_order[j + 1] = key;
    }
}

bool mm_scene_from_json(const char *json, mm_scene_t *scene, char *error, size_t error_size)
{
    if(error != NULL && error_size > 0) error[0] = '\0';
    memset(scene, 0, sizeof(*scene));

    cJSON *root = cJSON_Parse(json);
    if(root == NULL) {
        fail(error, error_size, "scene is not valid JSON");
        return false;
    }

    bool ok = false;
    do {
        scene->version = (int)number_or(root, "version", 1.0f);
        if(scene->version != 1) {
            fail(error, error_size, "unsupported scene version: %d", scene->version);
            break;
        }
        scene->id = (int)number_or(root, "id", 0.0f);
        scene->width = (int)number_or(root, "width", 0.0f);
        scene->height = (int)number_or(root, "height", 0.0f);
        copy_string(scene->fit, sizeof(scene->fit),
                    cJSON_GetObjectItemCaseSensitive(root, "fit"), "contain");
        scene->duration_ms = number_or(root, "duration", 0.0f);

        const cJSON *layers = cJSON_GetObjectItemCaseSensitive(root, "layers");
        const cJSON *raw_layer = NULL;
        cJSON_ArrayForEach(raw_layer, layers) {
            if(scene->layer_count >= MM_MAX_LAYERS) {
                fail(error, error_size, "too many layers");
                break;
            }
            mm_layer_t *layer = &scene->layers[scene->layer_count];
            memset(layer, 0, sizeof(*layer));
            copy_string(layer->id, sizeof(layer->id),
                        cJSON_GetObjectItemCaseSensitive(raw_layer, "id"), "");
            layer->z = (int)number_or(raw_layer, "z", 0.0f);

            const cJSON *raw_object = NULL;
            cJSON_ArrayForEach(raw_object,
                               cJSON_GetObjectItemCaseSensitive(raw_layer, "objects")) {
                if(scene->object_count >= MM_MAX_OBJECTS) {
                    fail(error, error_size, "too many objects");
                    break;
                }
                if(!parse_object(raw_object, &scene->objects[scene->object_count],
                                 error, error_size)) {
                    break;
                }
                layer->object_index[layer->object_count++] = scene->object_count++;
            }
            scene->layer_count++;
        }
        if(error != NULL && error[0] != '\0') break;
        order_layers(scene);

        const cJSON *raw_animation = NULL;
        cJSON_ArrayForEach(raw_animation,
                           cJSON_GetObjectItemCaseSensitive(root, "animations")) {
            if(scene->animation_count >= MM_MAX_ANIMATIONS) {
                fail(error, error_size, "too many animations");
                break;
            }
            mm_animation_t *animation = &scene->animations[scene->animation_count];
            memset(animation, 0, sizeof(*animation));

            const cJSON *target = cJSON_GetObjectItemCaseSensitive(raw_animation, "target");
            const cJSON *property = cJSON_GetObjectItemCaseSensitive(raw_animation, "property");
            if(!cJSON_IsString(target) || !cJSON_IsString(property)) {
                fail(error, error_size, "animation needs a target and a property");
                break;
            }
            animation->target = find_object(scene, target->valuestring);
            if(animation->target < 0) {
                fail(error, error_size, "animation targets unknown object: %s",
                     target->valuestring);
                break;
            }
            animation->property = property_from_name(property->valuestring);
            if(animation->property == MM_PROP_UNKNOWN) {
                fail(error, error_size, "property is not animatable in v1: %s",
                     property->valuestring);
                break;
            }
            const cJSON *easing = cJSON_GetObjectItemCaseSensitive(raw_animation, "easing");
            animation->easing = mm_easing_from_name(cJSON_IsString(easing) ? easing->valuestring
                                                                           : "linear");
            if(animation->easing == MM_EASE_UNKNOWN) {
                fail(error, error_size, "unknown easing curve: %s", easing->valuestring);
                break;
            }
            animation->start_ms = number_or(raw_animation, "start", 0.0f);
            animation->duration_ms = number_or(raw_animation, "duration", 0.0f);
            animation->from_value = number_or(raw_animation, "from", 0.0f);
            animation->to_value = number_or(raw_animation, "to", 0.0f);

            const float end = animation->start_ms + animation->duration_ms;
            if(end > scene->duration_ms) scene->duration_ms = end;
            scene->animation_count++;
        }
        ok = error == NULL || error[0] == '\0';
    } while(0);

    cJSON_Delete(root);
    return ok;
}
