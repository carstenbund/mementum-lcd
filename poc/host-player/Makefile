# Host build of the player -- no cmake, no SDL, no window (plan §3.7).
#
# LVGL is plain C and ThorVG is plain C++; both compile with nothing but gcc,
# which keeps the conformance build reproducible and CI-friendly. The LVGL
# checkout is pinned by fetch-lvgl.sh; unpinned library versions rot golden
# frames (risk R12).

LVGL_DIR ?= ../../third_party/lvgl
CJSON_DIR ?= ../../third_party/cJSON
PLAYER_DIR ?= ../player
BUILD_DIR ?= build

# -MMD -MP so that editing a header rebuilds what includes it. Without this a
# change to scene_model.h leaves half the objects compiled against the old
# struct layout, which presents as heap corruption rather than as a build error.
CFLAGS := -O2 -g -Wall -fPIC -MMD -MP -I. -I$(LVGL_DIR) -I$(LVGL_DIR)/src \
          -I$(CJSON_DIR) -I$(PLAYER_DIR) -I/usr/include/libdrm -DLV_CONF_INCLUDE_SIMPLE
CXXFLAGS := $(CFLAGS) -std=c++14
LDFLAGS := -lm -lstdc++ -lpthread -ldrm

LVGL_CSRCS := $(shell find $(LVGL_DIR)/src -type f -name '*.c')
LVGL_CXXSRCS := $(shell find $(LVGL_DIR)/src -type f -name '*.cpp')
PROBE_SRCS := probe_vector.c
SUBPATH_SRCS := probe_subpath.c

# The player itself: portable C, shared verbatim with the future ESP-IDF build.
PLAYER_SRCS := $(PLAYER_DIR)/easing.c $(PLAYER_DIR)/geometry.c $(PLAYER_DIR)/evaluator.c \
               $(PLAYER_DIR)/scene_json.c $(PLAYER_DIR)/render_lvgl.c $(PLAYER_DIR)/ripple.c \
               $(PLAYER_DIR)/player.c $(PLAYER_DIR)/screen.c $(PLAYER_DIR)/schedule.c
CJSON_SRCS := $(CJSON_DIR)/cJSON.c
PLAYER_OBJS := $(patsubst $(PLAYER_DIR)/%,$(BUILD_DIR)/player/%.o,$(PLAYER_SRCS)) \
               $(patsubst $(CJSON_DIR)/%,$(BUILD_DIR)/cjson/%.o,$(CJSON_SRCS))
LIB := $(BUILD_DIR)/libmementum_player.so
# The same library under the name drm_screen_lvgl looks for first, so the
# plugin finds it without being told where a mementum checkout is.
PLUGIN_LIB := $(BUILD_DIR)/libdrm_screen_lvgl.so

LVGL_OBJS := $(patsubst $(LVGL_DIR)/%,$(BUILD_DIR)/lvgl/%.o,$(LVGL_CSRCS) $(LVGL_CXXSRCS))
PROBE_OBJS := $(patsubst %,$(BUILD_DIR)/%.o,$(PROBE_SRCS))
SUBPATH_OBJS := $(patsubst %,$(BUILD_DIR)/%.o,$(SUBPATH_SRCS))

.PHONY: all probe subpath lib drm clean
all: lib probe subpath
drm: $(BUILD_DIR)/drm_player
probe: $(BUILD_DIR)/probe_vector
subpath: $(BUILD_DIR)/probe_subpath
lib: $(LIB) $(PLUGIN_LIB)

$(LIB): $(PLAYER_OBJS) $(LVGL_OBJS)
	@mkdir -p $(dir $@)
	$(CC) -shared $^ -o $@ $(LDFLAGS)

$(PLUGIN_LIB): $(LIB)
	@ln -sf $(notdir $(LIB)) $@

$(BUILD_DIR)/player/%.c.o: $(PLAYER_DIR)/%.c
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -c $< -o $@

$(BUILD_DIR)/cjson/%.c.o: $(CJSON_DIR)/%.c
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -c $< -o $@

$(BUILD_DIR)/drm_player: $(BUILD_DIR)/drm_player.c.o $(PLAYER_OBJS) $(LVGL_OBJS)
	@mkdir -p $(dir $@)
	$(CC) $^ -o $@ $(LDFLAGS)

$(BUILD_DIR)/probe_vector: $(PROBE_OBJS) $(LVGL_OBJS)
	@mkdir -p $(dir $@)
	$(CC) $^ -o $@ $(LDFLAGS)

$(BUILD_DIR)/probe_subpath: $(SUBPATH_OBJS) $(LVGL_OBJS)
	@mkdir -p $(dir $@)
	$(CC) $^ -o $@ $(LDFLAGS)

$(BUILD_DIR)/lvgl/%.c.o: $(LVGL_DIR)/%.c
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -c $< -o $@

$(BUILD_DIR)/lvgl/%.cpp.o: $(LVGL_DIR)/%.cpp
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) -c $< -o $@

$(BUILD_DIR)/%.c.o: %.c
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -c $< -o $@

clean:
	rm -rf $(BUILD_DIR)

-include $(shell find $(BUILD_DIR) -name '*.d' 2>/dev/null)
