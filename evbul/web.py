"""Bağımlılıksız küçük web sunucusu: arayüz + JSON API."""
from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import updater
from .db import DB

log = logging.getLogger("evbul")
INDEX = (Path(__file__).parent / "static" / "index.html").read_bytes


def serve(cfg: dict, db: DB, wake: threading.Event, state: dict, host="127.0.0.1", port=8000):
    """Tarama tek bir arka plan işçisinde yapılır (tarayıcı tek thread'de kalmalı);
    'Şimdi tara' butonu sadece o işçiyi uyandırır."""

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, obj, code=200):
            body = json.dumps(obj, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v for k, v in parse_qs(u.query).items()}
            one = lambda k, cast=str: cast(q[k][0]) if q.get(k) and q[k][0] != "" else None  # noqa: E731
            many = lambda k: [x for v in q.get(k, []) for x in v.split(",") if x]  # noqa: E731
            if u.path == "/":
                body = INDEX()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)
            elif u.path == "/api/listings":
                self._json(db.query(
                    types=many("type"), sources=many("source"),
                    cities=many("city") or (cfg.get("cities") or []),
                    furnished=many("furnished"),
                    min_price=one("min_price", int), max_price=one("max_price", int),
                    min_area=one("min_area", int), min_rooms=one("min_rooms", int),
                    q=one("q"), since_hours=one("since_hours", float),
                    favorites=one("favorites") == "1", sort=one("sort") or "newest",
                    max_age_hours=cfg.get("keep_hours", 48),
                    available_by=one("available_by"), stay=many("stay"),
                    known_only=one("known_only") == "1"))
            elif u.path == "/api/update":
                info = updater.check()
                self._json({"available": bool(info), **(info or {})})
            elif u.path == "/api/stats":
                self._json({**db.stats(), "scraping": state["scraping"],
                            "last_report": state["last_report"],
                            "sources": list((cfg.get("sources") or {}).keys())})
            else:
                self._json({"error": "not found"}, 404)

        def do_POST(self):
            u = urlparse(self.path)
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            if u.path == "/api/flag":
                db.set_flag(body["uid"], body["flag"], int(body["value"]))
                self._json({"ok": True})
            elif u.path == "/api/scrape":
                wake.set()
                self._json({"started": True})
            elif u.path == "/api/update":
                try:
                    self._json(updater.apply_update())
                except Exception as e:  # noqa: BLE001
                    self._json({"ok": False, "error": str(e)[:200]})
            else:
                self._json({"error": "not found"}, 404)

    srv = ThreadingHTTPServer((host, port), H)
    log.info("Arayüz hazır → http://%s:%d", host, port)
    srv.serve_forever()
