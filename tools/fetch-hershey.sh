#!/bin/sh
# Fetch the Hershey stroke fonts used by the handwriting converter.
#
# The font *data* carries its own permissive licence, quoted in
# tools/handwriting.py and reproduced with any scene it generates:
#
#   The Hershey Fonts were originally created by Dr. A. V. Hershey while
#   working at the U. S. National Bureau of Standards. The format of the font
#   data in this distribution was originally created by James Hurt,
#   Cognition Inc.
#
# It is a composer-side asset: nothing on the device ever loads a .jhf. The
# player receives ordinary paths.
set -eu

DEST="${DEST:-$(dirname "$0")/../third_party/hershey-fonts}"

if [ ! -d "$DEST/.git" ]; then
    echo "hershey: cloning into $DEST"
    git clone --depth 1 https://github.com/kamalmostafa/hershey-fonts.git "$DEST"
fi
echo "hershey: $(ls "$DEST/hershey-fonts"/*.jhf | wc -l) stroke fonts available"
