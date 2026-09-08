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

# Local patches. third_party/ is not tracked here, so a change made to the
# vendored tree is lost on the next fetch unless it lives in patches/ -- which
# also keeps "what did we change about LVGL?" answerable from the repository.
PATCHES="$(dirname "$0")/patches"
for patch in "$PATCHES"/*.patch; do
    [ -e "$patch" ] || continue
    name="$(basename "$patch")"
    if patch -p1 -d "$DEST" --dry-run --silent -R < "$patch" >/dev/null 2>&1; then
        echo "lvgl: $name already applied"
    elif patch -p1 -d "$DEST" --silent < "$patch"; then
        echo "lvgl: applied $name"
    else
        echo "lvgl: FAILED to apply $name -- check it against $LVGL_VERSION" >&2
        exit 1
    fi
done
