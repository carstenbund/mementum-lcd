# The player, as a component. The same files the host suite compiles and the
# Arduino sketch symlinks -- listed here, never copied, because a copy is a
# second evaluator waiting to happen (§3.7).
set(PLAYER_DIR "${CMAKE_CURRENT_LIST_DIR}/../../../../player")
set(CJSON_DIR  "${CMAKE_CURRENT_LIST_DIR}/../../../../../third_party/cJSON")

idf_component_register(
    SRCS
        "${PLAYER_DIR}/easing.c"
        "${PLAYER_DIR}/geometry.c"
        "${PLAYER_DIR}/evaluator.c"
        "${PLAYER_DIR}/scene_json.c"
        "${PLAYER_DIR}/render_lvgl.c"
        "${PLAYER_DIR}/ripple.c"
        "${PLAYER_DIR}/schedule.c"
        "${CJSON_DIR}/cJSON.c"
    INCLUDE_DIRS
        "${PLAYER_DIR}"
        "${CJSON_DIR}"
    REQUIRES lvgl
)

# The scene model holds fixed arrays sized for a worst case; -Os keeps the code
# small while the data is what actually costs (see docs/esp32-bring-up.md).
target_compile_options(${COMPONENT_LIB} PRIVATE -Os -Wall)
