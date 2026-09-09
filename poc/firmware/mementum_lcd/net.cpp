#include "net.h"

#include <HTTPClient.h>
#include <WebServer.h>
#include <WiFi.h>

// ---- state -----------------------------------------------------------------

mm_schedule_t mm_current;
int  mm_client_id = 0;
bool mm_connected = false;
bool mm_clock_synced = false;

static mm_net_config config;
static WebServer server(80);
static int32_t clock_offset = 0;
static uint32_t last_heartbeat = 0;
static uint32_t heartbeat_interval = 5000;
static char *scene_buffer = nullptr;      // PSRAM: a scene is kilobytes, not bytes
static size_t scene_size = 0;

// Ripples are transient and there are never many at once; a small fixed array
// is the right shape on a device with no allocator worth calling.
#define MM_NET_MAX_RIPPLES 4
struct mm_pending_ripple { double at; float x, y, amplitude, strength; bool live; };
static mm_pending_ripple ripples[MM_NET_MAX_RIPPLES];

uint32_t mm_server_now() { return (uint32_t)((int32_t)millis() + clock_offset); }

const char *mm_scene_json() { return scene_buffer; }

// ---- the panel's own routes (the server pushes to these) -------------------

static void send_json(int code, const String &body) {
    server.send(code, "application/json", body);
}

// Idempotent on seq: a repeated push, or a heartbeat carrying the schedule we
// are already playing, must not restart the scene.
static void handle_play() {
    if(!server.hasArg("seq") || !server.hasArg("at")) {
        send_json(400, "{\"status\":\"error\",\"message\":\"missing seq or at\"}");
        return;
    }
    const uint32_t seq = strtoul(server.arg("seq").c_str(), nullptr, 10);
    const double at = strtod(server.arg("at").c_str(), nullptr);
    const int scene_id = server.hasArg("scene") ? server.arg("scene").toInt() : 0;
    const int duration = server.hasArg("duration") ? server.arg("duration").toInt() : 0;
    const String hash = server.hasArg("hash") ? server.arg("hash") : String("");

    if(scene_id == 0) {
        // The LED form: a bare string. This panel draws scenes, and compiling
        // words into strokes is the composer's job -- say so rather than show
        // nothing (the server has /text for exactly this).
        send_json(400, "{\"status\":\"error\",\"message\":\"this panel takes scenes\"}");
        return;
    }

    if(mm_schedule_adopt(&mm_current, seq, at, scene_id, hash.c_str(), duration)) {
        Serial.printf("PLAY seq=%lu scene=%d at=%.0f now=%lu\n",
                      (unsigned long)seq, scene_id, at, (unsigned long)mm_server_now());
    }
    send_json(200, "{\"status\":\"ok\"}");
}

static void handle_ripple() {
    const double at = server.hasArg("at") ? strtod(server.arg("at").c_str(), nullptr) : 0.0;
    for(int i = 0; i < MM_NET_MAX_RIPPLES; i++) {
        if(ripples[i].live) continue;
        ripples[i].live = true;
        ripples[i].at = at;
        ripples[i].x = server.hasArg("x") ? server.arg("x").toFloat() : 0.5f;
        ripples[i].y = server.hasArg("y") ? server.arg("y").toFloat() : 0.5f;
        ripples[i].amplitude = server.hasArg("amplitude") ? server.arg("amplitude").toFloat() : 0.0f;
        ripples[i].strength = server.hasArg("strength") ? server.arg("strength").toFloat() : 1.0f;
        break;
    }
    // Fire and forget by design: one that arrives too late is simply not shown.
    send_json(200, "{\"status\":\"ok\"}");
}

static void handle_clear() {
    mm_schedule_clear(&mm_current);
    send_json(200, "{\"status\":\"ok\"}");
}

static void handle_status() {
    char body[220];
    snprintf(body, sizeof(body),
             "{\"id\":%d,\"scene\":%d,\"seq\":%lu,\"scene_time\":%.0f,"
             "\"loaded\":%s,\"offset\":%ld,\"heap\":%lu}",
             mm_client_id, mm_current.scene_id, (unsigned long)mm_current.seq,
             mm_schedule_time(&mm_current, (double)mm_server_now()),
             mm_current.loaded ? "true" : "false", (long)clock_offset,
             (unsigned long)ESP.getFreeHeap());
    send_json(200, body);
}

// ---- talking to the server -------------------------------------------------

static bool register_with_server() {
    HTTPClient http;
    String url = String(config.server) + "/register?format=json&kind=lcd&version=lcd/1"
               + "&port=" + String(config.listen_port)
               + "&width=" + String(config.width) + "&height=" + String(config.height)
               + "&x=" + String(config.x, 2) + "&y=" + String(config.y, 2);
    http.begin(url);
    http.setTimeout(3000);
    const int code = http.GET();
    if(code < 200 || code >= 300) {
        Serial.printf("register failed: %d\n", code);
        http.end();
        return false;
    }
    const String body = http.getString();
    http.end();

    // Small enough to read by hand; a JSON parser on the device would be a
    // dependency bought for four fields.
    int at = body.indexOf("\"id\":");
    if(at >= 0) mm_client_id = atoi(body.c_str() + at + 5);
    at = body.indexOf("\"heartbeat_interval\":");
    if(at >= 0) heartbeat_interval = strtoul(body.c_str() + at + 21, nullptr, 10);

    // The running schedule comes back here: late join, at no extra cost.
    const int sched = body.indexOf("\"schedule\":");
    if(sched >= 0) {
        const char *s = body.c_str() + sched;
        const char *scene = strstr(s, "\"scene_id\":");
        const char *seq = strstr(s, "\"seq\":");
        const char *when = strstr(s, "\"display_at\":");
        const char *dur = strstr(s, "\"duration\":");
        if(scene && seq && when && atoi(scene + 11) > 0) {
            mm_schedule_adopt(&mm_current, strtoul(seq + 6, nullptr, 10),
                              strtod(when + 13, nullptr), atoi(scene + 11), nullptr,
                              dur ? atoi(dur + 11) : 0);
        }
    }
    Serial.printf("registered: id=%d heartbeat=%lums\n", mm_client_id,
                  (unsigned long)heartbeat_interval);
    return true;
}

// Cristian's algorithm, best of three: keep the sample with the smallest round
// trip, because that is the one with the least uncertainty in it.
static void sync_clock() {
    int32_t best_offset = clock_offset;
    uint32_t best_rtt = UINT32_MAX;
    for(int i = 0; i < 3; i++) {
        HTTPClient http;
        http.setConnectTimeout(2000);
        http.setTimeout(2000);
        http.begin(String(config.server) + "/time");
        const uint32_t t0 = millis();
        if(http.GET() == 200) {
            const uint32_t server_ms = strtoul(http.getString().c_str(), nullptr, 10);
            const uint32_t t1 = millis();
            const uint32_t rtt = t1 - t0;
            if(rtt < best_rtt) {
                best_rtt = rtt;
                best_offset = (int32_t)(server_ms + rtt / 2 - t1);
            }
        }
        http.end();
    }
    if(best_rtt != UINT32_MAX) {
        clock_offset = best_offset;
        mm_clock_synced = true;
        Serial.printf("clock synced: offset=%ld rtt=%lu\n", (long)clock_offset,
                      (unsigned long)best_rtt);
    }
}

// The recovery path. Whatever this panel missed -- a push, a stop, a whole
// show -- it learns here, because the schedule is state rather than an event.
static void send_heartbeat() {
    HTTPClient http;
    http.setTimeout(2000);
    http.begin(String(config.server) + "/heartbeat?format=json&port="
               + String(config.listen_port) + "&seq=" + String(mm_current.seq));
    if(http.GET() == 200) {
        const String body = http.getString();
        const char *scene = strstr(body.c_str(), "\"scene_id\":");
        const char *seq = strstr(body.c_str(), "\"seq\":");
        const char *when = strstr(body.c_str(), "\"display_at\":");
        const char *dur = strstr(body.c_str(), "\"duration\":");
        const char *state = strstr(body.c_str(), "\"state\":\"idle\"");
        if(state != nullptr) {
            mm_schedule_clear(&mm_current);
        }
        else if(scene && seq && when && atoi(scene + 11) > 0) {
            mm_schedule_adopt(&mm_current, strtoul(seq + 6, nullptr, 10),
                              strtod(when + 13, nullptr), atoi(scene + 11), nullptr,
                              dur ? atoi(dur + 11) : 0);
        }
    }
    else {
        // Unknown to the server (it restarted, or we were purged): register again.
        mm_client_id = 0;
        register_with_server();
    }
    http.end();
}

// ---- the asset plane -------------------------------------------------------

bool mm_fetch_scene() {
    if(!mm_current.active || mm_current.scene_id == 0) return false;
    if(mm_current.loaded) return true;

    HTTPClient http;
    http.setTimeout(5000);
    http.begin(String(config.server) + "/scene/" + String(mm_current.scene_id));
    const int code = http.GET();
    if(code != 200) {
        Serial.printf("scene %d fetch failed: %d\n", mm_current.scene_id, code);
        http.end();
        return false;
    }
    const int length = http.getSize();
    if(length > 0 && (size_t)length + 1 > scene_size) {
        free(scene_buffer);
        // PSRAM: an ESP32-S3 module has it, and a scene is comfortably larger
        // than anything worth putting on the internal heap.
        scene_buffer = (char *)ps_malloc((size_t)length + 1);
        scene_size = scene_buffer ? (size_t)length + 1 : 0;
    }
    if(scene_buffer == nullptr) {
        http.end();
        return false;
    }
    const String body = http.getString();
    strncpy(scene_buffer, body.c_str(), scene_size - 1);
    scene_buffer[scene_size - 1] = '\0';
    http.end();

    mm_current.loaded = true;
    Serial.printf("scene %d fetched: %d bytes\n", mm_current.scene_id, length);
    return true;
}

// ---- lifecycle -------------------------------------------------------------

bool mm_net_begin(const mm_net_config &cfg) {
    config = cfg;
    mm_schedule_clear(&mm_current);

    WiFi.mode(WIFI_STA);
    WiFi.begin(config.ssid, config.password);
    const uint32_t deadline = millis() + 20000;
    while(WiFi.status() != WL_CONNECTED && millis() < deadline) {
        delay(200);
    }
    mm_connected = WiFi.status() == WL_CONNECTED;
    if(!mm_connected) {
        Serial.println("no wifi");
        return false;
    }
    Serial.printf("wifi: %s\n", WiFi.localIP().toString().c_str());

    sync_clock();
    register_with_server();

    server.on("/play", handle_play);
    server.on("/ripple", handle_ripple);
    server.on("/clear", handle_clear);
    server.on("/status", handle_status);
    server.on("/", []() { send_json(200, "{\"status\":\"ok\"}"); });
    server.begin(config.listen_port);
    return true;
}

void mm_net_loop() {
    server.handleClient();
    const uint32_t now = millis();
    if(now - last_heartbeat >= heartbeat_interval) {
        last_heartbeat = now;
        send_heartbeat();
        // Re-sync occasionally rather than every beat: the offset moves slowly
        // and a round trip costs more than it is worth every few seconds.
        static uint8_t beats = 0;
        if(++beats % 12 == 0) sync_clock();
    }
}
