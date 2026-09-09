"""The server log, as a thing you can watch.

Ported from `mementum-led`'s: a ring of recent events, levels, and a fan-out to
whoever is listening -- which is what makes `/logstream` possible and, with it,
an operator page that shows what the wall is being told rather than guessing.

Two details are the LED server's and are kept because they were learned the
hard way: stdout is line-buffered (under systemd it is a pipe, so `print` would
otherwise sit in a buffer until it filled, and `journalctl -f` would show
nothing while the show ran), and a subscriber that stops reading is dropped
rather than allowed to back the server up.
"""

from __future__ import annotations

import collections
import queue
import sys
import threading
import time

__all__ = ["ServerLog"]

try:  # pragma: no cover - depends on how the process was started
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except (AttributeError, ValueError):
    pass


class ServerLog:
    def __init__(self, history: int = 200, echo: bool = True):
        self.history: collections.deque = collections.deque(maxlen=history)
        self.echo = echo
        self._subscribers: list[queue.Queue] = []
        self._lock = threading.Lock()

    def emit(self, message: str, level: str = "status", journal: bool = True) -> dict:
        event = {"t": time.time(), "level": level, "message": message}
        with self._lock:
            self.history.append(event)
            subscribers = list(self._subscribers)
        if journal and self.echo:
            print(message, flush=True)
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(event)
            except queue.Full:              # a listener that stopped reading
                pass
        return event

    def subscribe(self) -> queue.Queue:
        subscriber: queue.Queue = queue.Queue(maxsize=256)
        with self._lock:
            self._subscribers.append(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue) -> None:
        with self._lock:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)

    def recent(self, limit: int = 50) -> list[dict]:
        with self._lock:
            return list(self.history)[-limit:]
