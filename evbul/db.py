"""SQLite depolama: ekleme/güncelleme, tekrar tespiti, filtreli sorgu."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from .models import Listing

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    uid TEXT PRIMARY KEY,
    source TEXT, url TEXT, title TEXT,
    price INTEGER, city TEXT, address TEXT, postcode TEXT,
    area_m2 INTEGER, rooms INTEGER, type TEXT, furnished TEXT,
    available_from TEXT, image TEXT,
    fingerprint TEXT, duplicate_of TEXT,
    first_seen REAL, last_seen REAL,
    favorite INTEGER DEFAULT 0, hidden INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_fp ON listings(fingerprint);
CREATE INDEX IF NOT EXISTS ix_seen ON listings(first_seen);
"""

# sonradan eklenen kolonlar (eski veritabanlarını otomatik günceller)
EXTRA_COLS = {"description": "TEXT", "min_months": "INTEGER", "max_months": "INTEGER",
              "stay": "TEXT", "detail_at": "REAL", "ai_used": "INTEGER DEFAULT 0"}
# kart metninden tahmin edilen alanlar: detay sayfasından gelen değeri ezmesin
SOFT_COLS = ["available_from", "min_months", "max_months", "stay"]

COLS = ["source", "url", "title", "price", "city", "address", "postcode", "area_m2",
        "rooms", "type", "furnished", "available_from", "image", "min_months", "max_months", "stay"]


class DB:
    def __init__(self, path: str | Path = "evbul.db"):
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        have = {r["name"] for r in self.conn.execute("PRAGMA table_info(listings)")}
        for col, typ in EXTRA_COLS.items():
            if col not in have:
                self.conn.execute(f"ALTER TABLE listings ADD COLUMN {col} {typ}")
        self.conn.commit()

    def upsert(self, l: Listing) -> bool:
        """İlanı kaydeder. Yeni ise True döner."""
        now = time.time()
        row = self.conn.execute("SELECT uid FROM listings WHERE uid=?", (l.uid,)).fetchone()
        d = l.to_dict()
        if row:
            sets = ", ".join(f"{c}=COALESCE({c}, ?)" if c in SOFT_COLS else f"{c}=COALESCE(?, {c})"
                             for c in COLS)
            self.conn.execute(f"UPDATE listings SET {sets}, last_seen=? WHERE uid=?",
                              [d[c] for c in COLS] + [now, l.uid])
            self.conn.commit()
            return False
        dup = self.conn.execute(
            "SELECT uid FROM listings WHERE fingerprint=? AND source!=? AND duplicate_of IS NULL",
            (l.fingerprint, l.source)).fetchone()
        self.conn.execute(
            f"INSERT INTO listings (uid, {', '.join(COLS)}, fingerprint, duplicate_of, first_seen, last_seen) "
            f"VALUES (?, {', '.join('?' * len(COLS))}, ?, ?, ?, ?)",
            [l.uid] + [d[c] for c in COLS] + [l.fingerprint, dup["uid"] if dup else None, now, now])
        self.conn.commit()
        return dup is None   # başka sitede zaten varsa "yeni" sayma

    def query(self, types=None, sources=None, cities=None, min_price=None, max_price=None,
              min_area=None, min_rooms=None, furnished=None, q=None, since_hours=None,
              favorites=False, show_hidden=False, include_duplicates=False, max_age_hours=None,
              available_by=None, stay=None, known_only=False,
              sort="newest", limit=300) -> list[dict]:
        where, args = [], []

        def in_clause(col, values):
            values = [v for v in (values or []) if v]
            if values:
                where.append(f"LOWER({col}) IN ({','.join('?' * len(values))})")
                args.extend(v.lower() for v in values)

        in_clause("type", types)
        in_clause("source", sources)
        in_clause("city", cities)
        in_clause("furnished", furnished)
        if min_price is not None:
            where.append("price >= ?"); args.append(min_price)
        if max_price is not None:
            where.append("price <= ?"); args.append(max_price)
        if min_area is not None:
            where.append("area_m2 >= ?"); args.append(min_area)
        if min_rooms is not None:
            where.append("rooms >= ?"); args.append(min_rooms)
        if q:
            where.append("(title LIKE ? OR address LIKE ? OR postcode LIKE ?)")
            args += [f"%{q}%"] * 3
        if since_hours:
            where.append("first_seen >= ?"); args.append(time.time() - since_hours * 3600)
        if max_age_hours:
            # siteden kalkmış (uzun süredir görülmeyen) ilanları gösterme; favoriler hep kalır
            where.append("(last_seen >= ? OR favorite = 1)"); args.append(time.time() - max_age_hours * 3600)
        if favorites:
            where.append("favorite = 1")
        if available_by:   # bu tarihe kadar taşınılabilir
            where.append("(available_from <= ?" + ("" if known_only else " OR available_from IS NULL") + ")")
            args.append(available_by)
        if stay:
            stays = [x for x in (stay if isinstance(stay, list) else [stay]) if x]
            if stays:
                where.append(f"(stay IN ({','.join('?' * len(stays))})"
                             + ("" if known_only else " OR stay IS NULL") + ")")
                args.extend(stays)
        if not show_hidden:
            where.append("hidden = 0")
        if not include_duplicates:
            where.append("duplicate_of IS NULL")

        order = {"newest": "first_seen DESC", "price_asc": "price IS NULL, price ASC",
                 "price_desc": "price DESC", "area_desc": "area_m2 DESC",
                 "available": "available_from IS NULL, available_from ASC",
                 "ppm2": "CASE WHEN area_m2>0 THEN price*1.0/area_m2 END IS NULL, price*1.0/area_m2 ASC"
                 }.get(sort, "first_seen DESC")
        sql = "SELECT * FROM listings"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += f" ORDER BY {order} LIMIT ?"
        args.append(limit)
        rows = [dict(r) for r in self.conn.execute(sql, args)]
        # aynı evin diğer sitelerdeki linkleri
        for r in rows:
            r["also_on"] = [dict(x) for x in self.conn.execute(
                "SELECT source, url FROM listings WHERE duplicate_of=?", (r["uid"],))]
        return rows

    def needs_details(self, limit=25) -> list[dict]:
        """Açıklaması henüz çekilmemiş ilanlar (en yeniler önce)."""
        return [dict(r) for r in self.conn.execute(
            "SELECT uid, source, url FROM listings WHERE detail_at IS NULL AND duplicate_of IS NULL "
            "AND hidden = 0 ORDER BY first_seen DESC LIMIT ?", (limit,))]

    def set_details(self, uid: str, description: str | None, info: dict):
        """Detay sayfası sonuçları kart tahminlerinden daha güvenilir: varsa üzerine yazar."""
        self.conn.execute(
            "UPDATE listings SET description=COALESCE(?, description), "
            "available_from=COALESCE(?, available_from), min_months=COALESCE(?, min_months), "
            "max_months=COALESCE(?, max_months), stay=COALESCE(?, stay), "
            "ai_used=?, detail_at=? WHERE uid=?",
            (description, info.get("available_from"), info.get("min_months"), info.get("max_months"),
             info.get("stay"), 1 if info.get("ai") else 0, time.time(), uid))
        self.conn.commit()

    def get(self, uid: str) -> dict | None:
        r = self.conn.execute("SELECT * FROM listings WHERE uid=?", (uid,)).fetchone()
        return dict(r) if r else None

    def set_flag(self, uid: str, flag: str, value: int):
        if flag not in ("favorite", "hidden"):
            raise ValueError(flag)
        self.conn.execute(f"UPDATE listings SET {flag}=? WHERE uid=?", (value, uid))
        self.conn.commit()

    def stats(self) -> dict:
        r = self.conn.execute(
            "SELECT COUNT(*) n, MAX(last_seen) last FROM listings WHERE duplicate_of IS NULL").fetchone()
        by_src = {x["source"]: x["n"] for x in self.conn.execute(
            "SELECT source, COUNT(*) n FROM listings GROUP BY source")}
        cities = [x["city"] for x in self.conn.execute(
            "SELECT DISTINCT city FROM listings WHERE city IS NOT NULL ORDER BY city")]
        return {"total": r["n"], "last_update": r["last"], "by_source": by_src, "cities": cities}
