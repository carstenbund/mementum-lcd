/**
 * The network half of a panel -- `mementum-led`'s ws_wifi.cpp, for a panel
 * that draws scenes.
 *
 * The flow is that firmware's, unchanged, because it was right:
 *
 *     connect -> /register -> adopt the id the server gives us
 *     every N seconds -> /heartbeat (which carries the running schedule)
 *     Cristian sync against /time, best of three round trips
 *     serve /play, /ripple, /clear, /status so the server can push
 *
 * One thing differs and it is the whole reason this file exists separately: a
 * matrix is told a *string*, which fits in the push. A panel is told a *scene*,
 * which does not -- so a push carries an id and a hash, and the panel fetches
 * `/scene/<id>` once. Holding the library is the server's job; a device with a
 * few megabytes cannot do it, which is why this firmware has no server mode.
 */
#ifndef MM_NET_H
#define MM_NET_H

#include <Arduino.h>

#include "schedule.h"

/** What this panel is, on the wall. Set before mm_net_begin(). */
struct mm_net_config {
    const char *ssid;
    const char *password;
    const char *server;          /**< "http://192.168.4.1:8080" */
    uint16_t    listen_port;     /**< where the server pushes to us */
    int         width;
    int         height;
    float       x, y;            /**< where this panel stands, in metres */
};

extern mm_schedule_t mm_current;   /**< what this panel has been told to show */
extern int  mm_client_id;          /**< the id the server gave us, or 0 */
extern bool mm_connected;
extern bool mm_clock_synced;

/** Join the network, register, sync, and start serving the push routes. */
bool mm_net_begin(const mm_net_config &config);

/** Call often. Serves pending requests and heartbeats when it is time. */
void mm_net_loop();

/** The shared clock: local millis plus the offset Cristian's algorithm found.
 *  Every panel on the wall answers this the same, which is the whole trick. */
uint32_t mm_server_now();

/** Fetch the scene the current schedule names, if we do not hold it already.
 *  Returns true when `mm_current.loaded` can be trusted. */
bool mm_fetch_scene();

/** The scene bytes last fetched (owned here; valid until the next fetch). */
const char *mm_scene_json();

#endif /* MM_NET_H */
