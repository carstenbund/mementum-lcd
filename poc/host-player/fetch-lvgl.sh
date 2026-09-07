#!/bin/sh
# Fetch the pinned LVGL checkout the host player builds against.
#
# Pinned deliberately: golden frames rot across library versions (risk R12), and
# "which LVGL?" must be answerable from the repository, not from someone's
# machine. ThorVG ships inside LVGL, so this is the only dependency.
set -eu

LVGL_VERSION="${LVGL_VERSION:-v9.5.0}"
DEST="${DEST:-$(dirname "$0")/../../third_party/lvgl}"

if [ -d "$DEST/.git" ]; then
    echo "lvgl: already present at $DEST ($(git -C "$DEST" describe --tags 2>/dev/null || echo unknown))"
else
    echo "lvgl: cloning $LVGL_VERSION into $DEST"
    git clone --depth 1 --branch "$LVGL_VERSION" https://github.com/lvgl/lvgl.git "$DEST"
fi

git -C "$DEST" fetch --depth 1 --tags origin "$LVGL_VERSION" >/dev/null 2>&1 || true
git -C "$DEST" checkout -q "$LVGL_VERSION"
echo "lvgl: at $(git -C "$DEST" describe --tags)"
