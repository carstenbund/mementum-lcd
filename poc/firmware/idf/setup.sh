#!/bin/sh
# Point the IDF build at the vendored LVGL, the same way the sketch points at
# the player's C: a symlink made here rather than committed, because it leads
# into third_party/ and a fresh clone does not have that until fetch-lvgl.sh
# has run.
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
root="$here/../../.."

test -f "$root/third_party/lvgl/lvgl.h" || {
    echo "LVGL not fetched: run poc/host-player/fetch-lvgl.sh" >&2
    exit 1
}
test -f "$root/third_party/cJSON/cJSON.c" || {
    echo "cJSON not fetched: run poc/host-player/fetch-cjson.sh" >&2
    exit 1
}
ln -sfn ../../../../third_party/lvgl "$here/components/lvgl"

# LVGL's ESP component puts ${LVGL_ROOT_DIR}/../ on the include path and
# defines LV_CONF_INCLUDE_SIMPLE, so lv_conf.h has to sit beside the lvgl
# folder. Link it into both places the folder can appear as -- components/ if
# CMake keeps the symlink, third_party/ if it resolves it -- and link rather
# than copy, because the Arduino sketch and this build must not drift into two
# different device configurations.
ln -sfn ../../mementum_lcd/lv_conf.h "$here/components/lv_conf.h"
ln -sfn ../poc/firmware/mementum_lcd/lv_conf.h "$root/third_party/lv_conf.h"

echo "components/lvgl    -> $(readlink "$here/components/lvgl")"
echo "components/lv_conf.h -> $(readlink "$here/components/lv_conf.h")"
echo "now: idf.py set-target esp32s3 && idf.py build"
