#!/usr/bin/env python3
"""EvBul — Hollanda kiralık ev toplayıcı.

  py run.py serve            # arayüz (http://127.0.0.1:8000) + arka planda düzenli tarama
  py run.py scrape           # bir kez tara
  py run.py scrape --only funda --debug   # tek siteyi test et, HTML'i debug/ klasörüne kaydet
  py run.py watch            # arayüzsüz: düzenli tara + Telegram
  py run.py telegram-test    # Telegram ayarını dene
"""
import argparse
import logging
import random
import threading

from evbul.core import load_config, make_fetcher, notify, run_once
from evbul.db import DB
from evbul.models import Listing


def worker(cfg, db_path, wake: threading.Event, state: dict, interval_minutes):
    """Tek tarama işçisi. Tarayıcı bu thread'de açılır ve açık kalır."""
    db = DB(db_path)
    fetcher = None
    try:
        while True:
            state["scraping"] = True
            try:
                fetcher = fetcher or make_fetcher(cfg)
                r = run_once(cfg, db, fetcher=fetcher)
                state["last_report"] = {"new": len(r["new"]), "errors": r["errors"], "counts": r["counts"]}
            except Exception as e:  # noqa: BLE001
                logging.exception("tur hatası")
                state["last_report"] = {"new": 0, "errors": {"genel": str(e)[:200]}, "counts": {}}
                if fetcher:          # tarayıcı kapandıysa bir dahaki turda yeniden aç
                    try:
                        fetcher.close()
                    except Exception:  # noqa: BLE001
                        pass
                    fetcher = None
            finally:
                state["scraping"] = False
            timeout = interval_minutes * 60 * random.uniform(0.85, 1.15) if interval_minutes else None
            wake.wait(timeout)
            wake.clear()
    finally:
        if fetcher:
            fetcher.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["scrape", "watch", "serve", "telegram-test"])
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--db", default="evbul.db")
    ap.add_argument("--only", nargs="*", help="sadece bu kaynaklar (kapalı olsa bile)")
    ap.add_argument("--debug", action="store_true", help="çekilen HTML'leri debug/ klasörüne yaz")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-watch", action="store_true", help="serve: sadece 'Şimdi tara' ile tara")
    a = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    cfg = load_config(a.config)
    interval = cfg.get("interval_minutes", 10)

    if a.cmd == "scrape":
        db, fetcher = DB(a.db), make_fetcher(cfg)
        try:
            r = run_once(cfg, db, debug_dir="debug" if a.debug else None, only=a.only, fetcher=fetcher)
        finally:
            fetcher.close()
        for l in r["new"][:30]:
            print(f"  [{l['source']}] {l['type'] or '?':9} €{l['price'] or '?':>5}  {l['area_m2'] or '?':>4} m²  "
                  f"📅 {l['available_from'] or '?'}  ⏳ {l['stay'] or '?'}  {l['title']}  {l['url']}")
    elif a.cmd == "watch":
        worker(cfg, a.db, threading.Event(), {}, interval)
    elif a.cmd == "serve":
        from evbul.web import serve
        wake, state = threading.Event(), {"scraping": False, "last_report": None}
        threading.Thread(target=worker, args=(cfg, a.db, wake, state, None if a.no_watch else interval),
                         daemon=True).start()
        serve(cfg, DB(a.db), wake, state, port=a.port)
    elif a.cmd == "telegram-test":
        notify(cfg, [Listing("test", "https://example.com", "Test ilanı — EvBul çalışıyor",
                             price=1200, area_m2=40, city="Amsterdam", type="studio")])
        print("Gönderildi (gelmediyse bot_token / chat_id'yi kontrol et).")


if __name__ == "__main__":
    main()
