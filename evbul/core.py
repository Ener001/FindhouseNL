"""Ayarlar, filtre eşleştirme, tarama turu ve Telegram bildirimi."""
from __future__ import annotations

import logging
from pathlib import Path

import requests
import yaml

from .db import DB
from .models import Listing
from .sources import Blocked, build

log = logging.getLogger("evbul")


def load_config(path="config.yaml") -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def _g(item, k):
    return item.get(k) if isinstance(item, dict) else getattr(item, k, None)


def matches(item, f: dict) -> bool:
    """Bildirim filtresi. Bilinmeyen (None) değerler elenmez, kaçırmamak daha iyi
    (filters.known_only: true ise müsaitlik/süre bilinmeyenler elenir)."""
    f = f or {}
    g = lambda k: _g(item, k)  # noqa: E731
    known_only = f.get("known_only", False)
    if f.get("types") and g("type") and g("type") not in f["types"]:
        return False
    if f.get("max_price") and g("price") and g("price") > f["max_price"]:
        return False
    if f.get("min_price") and g("price") and g("price") < f["min_price"]:
        return False
    if f.get("min_area") and g("area_m2") and g("area_m2") < f["min_area"]:
        return False
    if f.get("min_rooms") and g("rooms") and g("rooms") < f["min_rooms"]:
        return False
    if f.get("furnished") and g("furnished") and g("furnished") not in f["furnished"]:
        return False
    if f.get("available_by"):
        av = g("available_from")
        if (av and av > str(f["available_by"])) or (not av and known_only):
            return False
    if f.get("stay"):
        wanted = f["stay"] if isinstance(f["stay"], list) else [f["stay"]]
        st = g("stay")
        if (st and st not in wanted) or (not st and known_only):
            return False
    words = [w.lower() for w in f.get("exclude_words") or []]
    hay = f"{g('title') or ''} {g('description') or ''}".lower()
    if any(w in hay for w in words):
        return False
    return True


def make_fetcher(cfg: dict):
    """config.yaml → mode: browser (varsayılan) ya da http."""
    b = cfg.get("browser") or {}
    if (cfg.get("mode") or "browser") == "http":
        from .sources import HttpFetcher
        return HttpFetcher()
    from .browser import BrowserFetcher
    return BrowserFetcher(
        profile_dir=b.get("profile_dir", "browser_profile"),
        port=b.get("port", 9222),
        extra_args=b.get("extra_args"),
        wait_minutes=b.get("challenge_wait_minutes", 5),
        on_challenge=lambda url: send_text(cfg, f"⚠️ EvBul doğrulama bekliyor, tarayıcı penceresine bak:\n{url}"))


def run_once(cfg: dict, db: DB, debug_dir=None, only: list[str] | None = None, fetcher=None) -> dict:
    filters = cfg.get("filters") or {}
    report = {"new": [], "errors": {}, "counts": {}}
    for name, opts in (cfg.get("sources") or {}).items():
        opts = dict(opts or {})
        if only and name not in only:
            continue
        if not only and not opts.get("enabled", True):
            continue
        opts.setdefault("max_price", filters.get("max_price"))
        opts.setdefault("min_price", filters.get("min_price") or 0)
        src = build(name, opts, debug_dir, fetcher)
        n = 0
        for city in cfg.get("cities") or []:
            try:
                for l in src.fetch(city, cfg.get("max_pages", 2)):
                    n += 1
                    if db.upsert(l) and matches(l, filters):
                        report["new"].append(l)
            except Blocked as e:
                log.warning("ENGELLENDİ — %s (bu tur atlanıyor)", e)
                report["errors"][name] = "engellendi (captcha/403)"
                break
            except Exception as e:  # noqa: BLE001
                log.exception("%s / %s hata", name, city)
                report["errors"][name] = str(e)[:200]
        report["counts"][name] = n
        log.info("%-13s %4d ilan", name, n)

    # ---- açıklamalar: yeni ilanların detay sayfaları ----
    if fetcher and (cfg.get("details") or {}).get("enabled", True):
        fetch_details(cfg, db, fetcher)

    # bildirim: açıklamadan çıkan müsaitlik/süre bilgisiyle birlikte tekrar süz
    rows = [r for l in report["new"] if (r := db.get(l.uid))]
    report["new"] = [r for r in rows if matches(r, filters)]
    log.info("Yeni ve filtrene uyan: %d", len(report["new"]))
    notify(cfg, report["new"])
    return report


def fetch_details(cfg: dict, db: DB, fetcher) -> int:
    from .detail import extract_detail
    from .extract import analyze
    d = cfg.get("details") or {}
    ai_cfg = cfg.get("ai") or {}
    blocked_hosts, done = set(), 0
    todo = db.needs_details(d.get("per_round", 25))
    if todo:
        log.info("Açıklamalar çekiliyor: %d ilan", len(todo))
    for row in todo:
        host = row["url"].split("/")[2]
        if host in blocked_hosts:
            continue
        try:
            html = fetcher.html(row["url"])
        except Blocked:
            blocked_hosts.add(host)
            continue
        except Exception as e:  # noqa: BLE001
            log.warning("detay alınamadı %s: %s", row["url"], e)
            db.set_details(row["uid"], None, {})   # tekrar tekrar denemesin
            continue
        desc, page_text = extract_detail(html)
        info = analyze(page_text, ai_cfg, ai_text=desc or page_text)
        db.set_details(row["uid"], desc, info)
        done += 1
    return done


TYPE_TR = {"room": "Oda", "studio": "Stüdyo", "apartment": "Daire", "house": "Ev"}


def send_text(cfg: dict, msg: str):
    tg = cfg.get("telegram") or {}
    if not (tg.get("bot_token") and tg.get("chat_id")):
        return
    try:
        requests.post(f"https://api.telegram.org/bot{tg['bot_token']}/sendMessage",
                      json={"chat_id": tg["chat_id"], "text": msg, "parse_mode": "HTML"},
                      timeout=10)
    except requests.RequestException as e:
        log.warning("Telegram gönderilemedi: %s", e)


def notify(cfg: dict, listings):
    for l in listings[:20]:
        g = lambda k: _g(l, k)  # noqa: E731
        bits = [TYPE_TR.get(g("type") or "", "?"), g("city") or ""]
        if g("price"):
            bits.append(f"€{g('price')}")
        if g("area_m2"):
            bits.append(f"{g('area_m2')} m²")
        extra = []
        if g("available_from"):
            extra.append(f"📅 {g('available_from')}")
        if g("stay"):
            extra.append("⏳ uzun dönem" if g("stay") == "long" else "⏳ kısa dönem")
        msg = f"🏠 <b>{g('title')}</b>\n{' · '.join(b for b in bits if b)}"
        if extra:
            msg += "\n" + " · ".join(extra)
        send_text(cfg, f"{msg}\n<i>{g('source')}</i>\n{g('url')}")
