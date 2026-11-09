"""Funda (funda.nl) — güçlü bot koruması var, en iyi gayret (best effort).

Kart HTML'i sık değiştiği için CSS sınıfına değil, ilan linklerine (/detail/huur/)
ve kart içindeki metne (€, m², posta kodu) dayanıyoruz.
"""
from __future__ import annotations

import json
import re
from urllib.parse import quote, urljoin

from ..models import Listing, POSTCODE_RE, parse_int, parse_price
from .base import Source, jsonld_objects

BASE = "https://www.funda.nl"
DETAIL_RE = re.compile(r"/detail/huur/")


class Funda(Source):
    name = "funda"

    def fetch(self, city: str, max_pages: int = 2) -> list[Listing]:
        out = []
        area = quote(json.dumps([city.lower().replace(" ", "-")]))
        price = ""
        if self.opts.get("max_price"):
            price = f"&price=%22{self.opts.get('min_price', 0)}-{self.opts['max_price']}%22"
        for page in range(1, max_pages + 1):
            url = f"{BASE}/zoeken/huur?selected_area={area}{price}&search_result={page}"
            items = self.parse(self.soup(url), city)
            out += items
            if not items:
                break
        return out

    def parse(self, soup, city: str) -> list[Listing]:
        seen, res = set(), []
        for a in soup.find_all("a", href=DETAIL_RE):
            url = urljoin(BASE, a["href"].split("?")[0])
            if url in seen:
                continue
            card = _card_of(a)
            blob = card.get_text(" ", strip=True) if card else a.get_text(" ", strip=True)
            title = a.get_text(" ", strip=True) or _title_from_url(url)
            if not title:
                continue
            seen.add(url)
            pc = POSTCODE_RE.search(blob)
            m2 = re.search(r"(\d+)\s*m²", blob)
            rooms = re.search(r"(\d+)\s*(kamers?|rooms?)", blob, re.I)
            price = re.search(r"€\s*[\d.,]+", blob)
            img = card.find("img") if card else None
            res.append(Listing(
                source=self.name, url=url, title=title, address=title,
                postcode=pc.group(1) if pc else None, city=city,
                price=parse_price(price.group()) if price else None,
                area_m2=int(m2.group(1)) if m2 else None,
                rooms=int(rooms.group(1)) if rooms else None,
                type=_type_from_url(url),
                image=img.get("src") if img else None,
            ))
        if not res:  # yedek: JSON-LD ItemList
            for o in jsonld_objects(soup):
                u = o.get("url")
                if u and DETAIL_RE.search(u) and u not in seen:
                    seen.add(u)
                    res.append(Listing(source=self.name, url=u, city=city,
                                       title=o.get("name") or _title_from_url(u),
                                       type=_type_from_url(u)))
        return res


def _card_of(a):
    """Linkten yukarı çıkıp fiyat içeren en küçük kapsayıcıyı bul."""
    el = a
    for _ in range(6):
        el = el.parent
        if el is None:
            return None
        if "€" in el.get_text():
            return el
    return None


def _title_from_url(url: str) -> str:
    # /detail/huur/amsterdam/appartement-prinsengracht-123/43123456/
    parts = [p for p in url.split("/") if p]
    slug = next((p for p in parts if "-" in p and not p.isdigit()), "")
    return slug.replace("-", " ").title()


def _type_from_url(url: str) -> str | None:
    u = url.lower()
    if "/appartement-" in u:
        return "apartment"
    if "/huis-" in u:
        return "house"
    if "/studio-" in u:
        return "studio"
    if "/kamer-" in u:
        return "room"
    return None
