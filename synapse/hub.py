"""Optional real-time invalidation hub (~100 LOC, stdlib only).

Design principle: push notifications, pull truth.
The hub NEVER stores memory -- it only broadcasts "cache invalidated" pings
so other machines re-read git. Truth stays durable in the repo.

    python -m synapse.hub            # serve on :7610
    curl -N localhost:7610/events    # subscribe (SSE stream)
    curl -X POST localhost:7610/notify?who=dev-a   # broadcast invalidation
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_subscribers: list = []
_lock = threading.Lock()
_history: list[dict] = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silence default noise
        pass

    def _sse(self, event: dict):
        payload = f"data: {json.dumps(event)}\n\n"
        self.wfile.write(f"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
                         f"Cache-Control: no-cache\r\nConnection: keep-alive\r\n\r\n".encode())
        self.wfile.write(payload.encode())
        self.wfile.flush()
        with _lock:
            _subscribers.append(self.wfile)
        try:
            while True:  # hold the connection open; client disconnects on error
                self.rfile.readline(1024)
        except OSError:
            pass
        finally:
            with _lock:
                if self.wfile in _subscribers:
                    _subscribers.remove(self.wfile)

    def do_GET(self):
        if self.path.startswith("/events"):
            self._sse({"type": "hello", "at": _now()})
        elif self.path.startswith("/health"):
            self._json(200, {"ok": True, "subscribers": len(_subscribers)})
        else:
            self._json(404, {"error": "use /events or /health"})

    def do_POST(self):
        if not self.path.startswith("/notify"):
            self._json(404, {"error": "use /notify"})
            return
        event = {"type": "invalidate", "at": _now(),
                 "who": self.path.split("who=")[-1] or "unknown"}
        with _lock:
            _history.append(event)
            dead = []
            for w in list(_subscribers):
                try:
                    w.write(f"data: {json.dumps(event)}\n\n".encode())
                    w.flush()
                except OSError:
                    dead.append(w)
            for w in dead:
                _subscribers.remove(w)
        self._json(200, {"broadcast": True})

    def _json(self, code: int, obj: dict):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main(port: int = 7610):
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"synapse hub listening on :{port} (SSE /events, POST /notify)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    import sys
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 7610)
