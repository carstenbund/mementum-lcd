#!/bin/sh
# Compile and upload the sketch with arduino-cli, so steps A1-A3 of the
# bring-up plan are a command rather than a paragraph of IDE settings.
#
#   ./build.sh                 compile only
#   ./build.sh /dev/ttyACM0    compile and upload
#
# The board flags are the ones that matter and the ones an IDE hides: PSRAM has
# to be on (a six-path scene is ~450 KB of parsed geometry before a pixel), and
# the partition scheme has to leave room for an application carrying ThorVG.
set -eu

here="$(cd "$(dirname "$0")" && pwd)"
port="${1:-}"

FQBN="${FQBN:-esp32:esp32:esp32s3}"
# opi = octal PSRAM; use 'enabled' for quad. huge_app leaves ~3 MB for the
# application, which ThorVG needs and the default 1.2 MB does not.
OPTS="${OPTS:-PSRAM=opi,PartitionScheme=huge_app,FlashSize=8M,CPUFreq=240,USBMode=hwcdc}"

command -v arduino-cli >/dev/null || {
    echo "arduino-cli not found: https://arduino.github.io/arduino-cli/" >&2
    exit 1
}

sh "$here/link.sh"

echo "== libraries =="
arduino-cli lib install "lvgl@9.5.0" 2>/dev/null || \
    echo "  install LVGL 9.5.0 by hand, or point libraries.txt at the vendored checkout"

echo "== compile =="
arduino-cli compile --fqbn "$FQBN:$OPTS" --warnings default "$here"

if [ -n "$port" ]; then
    echo "== upload to $port =="
    arduino-cli upload --fqbn "$FQBN:$OPTS" -p "$port" "$here"
    echo "== monitor =="
    arduino-cli monitor -p "$port" -c baudrate=115200
fi
