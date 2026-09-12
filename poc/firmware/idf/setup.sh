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
echo "components/lvgl -> $(readlink "$here/components/lvgl")"
echo "now: idf.py set-target esp32s3 && idf.py build"
