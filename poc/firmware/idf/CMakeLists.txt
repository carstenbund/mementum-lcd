# The panel, as an ESP-IDF project.
#
#   idf.py set-target esp32s3
#   idf.py menuconfig        (sdkconfig.defaults already sets what matters)
#   idf.py build flash monitor
#
# LVGL arrives as a managed component: the checkout in third_party/ carries
# idf_component.yml, so it is an IDF component already and nothing here has to
# vendor it a second time. Point at that checkout rather than the registry so
# the device builds the exact LVGL the host suite was measured against
# (including poc/host-player/patches/), which is what makes "the same picture"
# a claim rather than a hope.
cmake_minimum_required(VERSION 3.16)

# components/lvgl is a symlink to third_party/lvgl -- the same checkout the host
# builds, patches and all. Pointing EXTRA_COMPONENT_DIRS at third_party itself
# would make IDF try to treat cJSON and the fonts as components too.
set(EXTRA_COMPONENT_DIRS "${CMAKE_CURRENT_LIST_DIR}/components")

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(mementum_panel)
