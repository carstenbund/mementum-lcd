#include "assets_lvgl.h"

#include "lvgl.h"

#include <stdio.h>
#include <string.h>

unsigned long mm_crc32(unsigned long crc, const unsigned char *data, size_t length)
{
    static unsigned long table[256];
    static int ready = 0;
    if(!ready) {
        for(unsigned long n = 0; n < 256; n++) {
            unsigned long c = n;
            for(int k = 0; k < 8; k++) c = (c & 1) ? 0xEDB88320UL ^ (c >> 1) : c >> 1;
            table[n] = c;
        }
        ready = 1;
    }
    crc = (crc ^ 0xFFFFFFFFUL) & 0xFFFFFFFFUL;
    for(size_t i = 0; i < length; i++) crc = table[(crc ^ data[i]) & 0xFF] ^ (crc >> 8);
    return (crc ^ 0xFFFFFFFFUL) & 0xFFFFFFFFUL;
}

/** Read the whole file once: its length, and its CRC if one is declared. */
static const char *check_file(const mm_object_t *object, const char *path)
{
    lv_fs_file_t file;
    if(lv_fs_open(&file, path, LV_FS_MODE_RD) != LV_FS_RES_OK) return "missing";

    unsigned char buffer[1024];
    unsigned long crc = 0;
    uint32_t size = 0;
    for(;;) {
        uint32_t read = 0;
        if(lv_fs_read(&file, buffer, sizeof(buffer), &read) != LV_FS_RES_OK) {
            lv_fs_close(&file);
            return "unreadable";
        }
        if(read == 0) break;
        size += read;
        if(object->asset_crc != 0u) crc = mm_crc32(crc, buffer, read);
    }
    lv_fs_close(&file);

    if(object->asset_size != 0u && size != object->asset_size) return "the wrong size";
    if(object->asset_crc != 0u && (uint32_t)crc != object->asset_crc) return "a different picture (CRC)";
    return NULL;
}

int mm_scene_load_assets(mm_scene_t *scene, const char *root, char *report, size_t report_size)
{
    int failed = 0;
    if(report != NULL && report_size > 0) report[0] = '\0';

    for(int i = 0; i < scene->object_count; i++) {
        mm_object_t *object = &scene->objects[i];
        if(object->type != MM_OBJ_IMAGE) continue;

        object->asset_ok = false;
        int written = snprintf(object->asset_path, sizeof(object->asset_path), "%s%s.bin",
                               root, object->text);
        const char *problem = (written < 0 || (size_t)written >= sizeof(object->asset_path))
                              ? "a path too long" : check_file(object, object->asset_path);
        if(problem == NULL) {
            object->asset_ok = true;
            continue;
        }
        if(failed == 0 && report != NULL && report_size > 0) {
            snprintf(report, report_size, "image %s: %s.bin is %s", object->id, object->text, problem);
        }
        failed++;
    }
    return failed;
}
