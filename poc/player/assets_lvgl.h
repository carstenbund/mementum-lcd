/**
 * Image assets for a loaded scene, through LVGL's file system layer.
 *
 * A scene names each picture and says what its file must be -- its size and
 * CRC32, written by the composer that also wrote the file. Checking them at
 * load means a card from another build shows a missing picture and a report,
 * never the wrong picture. Where files live is the caller's business: `root`
 * is an LVGL path prefix such as "S:/assets/", so the same code reads an SD
 * card on a panel and a directory on a host.
 */
#ifndef MM_ASSETS_LVGL_H
#define MM_ASSETS_LVGL_H

#include <stddef.h>

#include "scene_model.h"

/** Check every image object's file `<root><src>.bin` and mark it drawable.
 *  Returns how many images cannot be drawn (missing, wrong size, wrong CRC);
 *  `report` names the first of them. Undeclared size or CRC (0) is not
 *  checked. Call after mm_scene_from_json, before the scene is drawn. */
int mm_scene_load_assets(mm_scene_t *scene, const char *root, char *report, size_t report_size);

/** CRC-32 (IEEE 802.3, as zlib.crc32), continued from `crc`; start with 0. */
unsigned long mm_crc32(unsigned long crc, const unsigned char *data, size_t length);

#endif /* MM_ASSETS_LVGL_H */
