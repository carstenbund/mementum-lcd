#!/bin/sh
# Fetch the pinned cJSON checkout the player parses scenes with.
#
# cJSON because ESP-IDF already ships it: the device build gains no new
# dependency, and the host and device parse scene packages with the same code.
set -eu

CJSON_VERSION="${CJSON_VERSION:-v1.7.18}"
DEST="${DEST:-$(dirname "$0")/../../third_party/cJSON}"

if [ ! -d "$DEST/.git" ]; then
    echo "cJSON: cloning $CJSON_VERSION into $DEST"
    git clone --depth 1 --branch "$CJSON_VERSION" https://github.com/DaveGamble/cJSON.git "$DEST"
fi
git -C "$DEST" checkout -q "$CJSON_VERSION"
echo "cJSON: at $(git -C "$DEST" describe --tags 2>/dev/null || echo "$CJSON_VERSION")"
