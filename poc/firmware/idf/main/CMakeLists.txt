idf_component_register(
    SRCS "main.c"
    INCLUDE_DIRS "."
    REQUIRES mementum_player lvgl esp_timer
    EMBED_TXTFILES "${CMAKE_CURRENT_LIST_DIR}/../../../scenes/three-strokes.json"
)
