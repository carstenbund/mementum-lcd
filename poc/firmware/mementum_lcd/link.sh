#!/bin/sh
# The Arduino IDE compiles what is in the sketch folder, and the player's C
# lives in poc/player/ because that is where it is tested. Symlink rather than
# copy: a copy is a second evaluator waiting to happen (§3.7).
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
player="$here/../../player"

for source in easing evaluator geometry ripple scene_json schedule render_lvgl; do
    ln -sf "$player/$source.c" "$here/$source.c" 2>/dev/null || true
    ln -sf "$player/$source.h" "$here/$source.h" 2>/dev/null || true
done
ln -sf "$player/scene_model.h" "$here/scene_model.h"
ln -sf "$player/easing.h" "$here/easing.h"

# cJSON, fetched by the host build, is the one third-party dependency.
cjson="$here/../../../third_party/cJSON"
if [ -f "$cjson/cJSON.c" ]; then
    ln -sf "$cjson/cJSON.c" "$here/cJSON.c"
    ln -sf "$cjson/cJSON.h" "$here/cJSON.h"
else
    echo "cJSON not fetched — run poc/host-player/fetch-cjson.sh" >&2
fi
echo "linked $(ls -1 "$here" | grep -c '\.c$') C sources into the sketch"
