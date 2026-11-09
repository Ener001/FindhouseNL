"""Ayarlarla yönetilen genel adaptör (HouseHunting, Findify ve eklemek istediğin her site).

config.yaml içinde:
  househunting:
    url: "https://househunting.nl/en/housing-offer/?city={city}&page={page}"
    link_pattern: "/en/housing-offer/[^/?#]+/?$"   # ilan detay linki regex'i
    # İsteğe bağlı CSS seçicileri (verilmezse metinden tahmin edilir):
    card: "div.property"
    title: "h3"
    price: ".price"
    area: ".surface"
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from ..models import (POSTCODE_RE, Listing, guess_type, parse_furnished, parse_int, parse_price)
from ..extract import rule_extract
from .base import Source, jsonld_objects, text


class Generic(Source):
    def __init__(self, name: str, opts: dict, debug_dir=None, fetcher=None):
        super().__init__(opts, debug_dir, fetcher)
        self.name = name

    def fetch(self, city: str, max_pages: int = 2) -> list[Listing]:
        tpl = self.opts.get("url")
        if not tpl:
            raise ValueError(f"{self.name}: config'de 'url' yok")
        out, seen = [], set()
        for page in range(1, max_pages + 1):
            url = tpl.format(city=city.lower().replace(" ", "-"), page=page,
                             max_price=self.opts.get("max_price", ""),
                             min_price=self.opts.get("min_price", 0))
            soup = self.soup(url)
            items = [l for l in self.parse(soup, url, city) if l.url not in seen]
            seen.update(l.url for l in items)
            out += items
            if not items or "{page}" not in tpl:
                break
        return out

    def parse(self, soup, page_url: str, city: str) -> list[Listing]:
        o = self.opts
        if o.get("card"):
            cards = soup.select(o["card"])
            pairs = [(c, c.select_one(o.get("link", "a[href]"))) for c in cards]
        elif o.get("link_pattern", "auto") == "auto":
            pairs = _auto_pairs(soup, page_url)
        else:
            pat = re.compile(o["link_pattern"])
            pairs, seen = [], set()
            for a in soup.find_all("a", href=True):
                href = urljoin(page_url, a["href"]).split("#")[0]
                if pat.search(href) and href not in seen and href.rstrip("/") != page_url.rstrip("/"):
                    seen.add(href)
                    pairs.append((_card_of(a, pat, page_url), a))
        res = []
        for card, a in pairs:
            if not a:
                continue
            card = card or a
            blob = card.get_text(" ", strip=True)
            title = text(card.select_one(o["title"])) if o.get("title") else None
            if not title and o.get("title_regex"):
                m = re.search(o["title_regex"].replace("{city}", re.escape(city)), blob, re.I)
                title = m.group(1).strip() if m else None
            title = title or text(card.find(["h2", "h3", "h4"])) or text(a)
            if not o.get("title") and not o.get("title_regex") and \
                    (not title or len(title) > 50 or title.lower() in ("details", "bekijk", "view", "meer info")):
                m = re.search(r"([A-Z][\w'.\- ]{2,40}?)\s*,\s*" + re.escape(city), blob)
                if m:
                    title = re.sub(r"^(?:(?:New|Nieuw|Top ad|React for free|Tenant-verified|Flexible cancellation"
                                   r"|\d+(?:\.\d)?|\(\d+\))\s+)+", "", m.group(1)).strip()
            if title and len(title) > 80:
                title = title[:77] + "…"
            if not title:
                continue
            price_txt = text(card.select_one(o["price"])) if o.get("price") else \
                (m.group() if (m := re.search(r"€\s*[\d.,]+", blob)) else None)
            area_txt = text(card.select_one(o["area"])) if o.get("area") else \
                (m.group() if (m := re.search(r"\d+\s*m(²|2)", blob)) else None)
            rooms = re.search(r"(\d+)\s*(slaapkamers?|bedrooms?|kamers?|rooms?)\b", blob, re.I) or \
                re.search(r"(?:slaapkamers?|bedrooms?)\s*:?\s*(\d+)", blob, re.I)
            pc = POSTCODE_RE.search(blob)
            img = card.find("img")
            if o.get("strict_city") and city.lower() not in blob.lower():
                continue
            full = urljoin(page_url, a["href"])
            ex = rule_extract(blob)
            res.append(Listing(
                available_from=ex["available_from"], min_months=ex["min_months"],
                max_months=ex["max_months"], stay=ex["stay"],
                source=self.name, url=full, title=title, address=title,
                type=guess_type(title) or guess_type(re.sub(r"[/_-]", " ", full.split("//")[-1])),
                city=city, postcode=pc.group(1) if pc else None,
                price=parse_price(price_txt), area_m2=parse_int(area_txt),
                rooms=int(rooms.group(1)) if rooms else None,
                furnished=parse_furnished(blob),
                image=(img.get("src") or img.get("data-src")) if img else None,
            ))
        if not res:
            for obj in jsonld_objects(soup):
                if obj.get("url") and obj.get("name") and obj.get("@type") not in ("WebSite", "Organization"):
                    offer = obj.get("offers") or {}
                    res.append(Listing(source=self.name, url=obj["url"], title=obj["name"], city=city,
                                       price=parse_price(str(offer.get("price", ""))) if isinstance(offer, dict) else None))
        return res


def _norm(page_url, href):
    return urljoin(page_url, href).split("#")[0].split("?")[0].rstrip("/")


def _card_of(a, pat, page_url):
    """İçinde SADECE bu ilanın linki olan en büyük kapsayıcı = ilan kartı.
    pat: regex ya da ilan URL'lerinden oluşan bir küme."""
    is_listing = (lambda u: u in pat) if isinstance(pat, set) else \
        (lambda u: bool(pat.search(u)))

    def n_listings(el):
        return len({_norm(page_url, x["href"]) for x in el.find_all("a", href=True)
                    if is_listing(_norm(page_url, x["href"]))})
    card = a
    el = a.parent
    while el is not None and el.name not in ("body", "html") and n_listings(el) <= 1:
        card, el = el, el.parent
    return card


def _auto_pairs(soup, page_url):
    """link_pattern verilmemişse ilan linklerini kendimiz buluruz:
    aynı sitedeki linkleri URL yapısına göre gruplar, kartlarında en çok
    fiyat (€) geçen grubu ilan listesi sayarız."""
    host = urlparse(page_url).netloc.replace("www.", "")
    page = _norm(page_url, page_url)
    groups: dict[tuple, dict] = {}
    for a in soup.find_all("a", href=True):
        u = _norm(page_url, a["href"])
        pu = urlparse(u)
        if pu.netloc.replace("www.", "") != host or u == page or pu.scheme not in ("http", "https"):
            continue
        segs = [x for x in pu.path.split("/") if x]
        if len(segs) < 2:
            continue
        sig = (len(segs), segs[0])
        groups.setdefault(sig, {}).setdefault(u, a)
    best, best_score = None, 1
    for sig, links in groups.items():
        if len(links) < 2:
            continue
        urls = set(links)
        score = sum(1 for a in links.values() if "€" in _card_of(a, urls, page_url).get_text())
        if score > best_score:
            best, best_score = links, score
    if not best:
        return []
    urls = set(best)
    pairs = [(_card_of(a, urls, page_url), a) for a in best.values()]
    return [(c, a) for c, a in pairs if "€" in c.get_text()]   # fiyatsız (menü vb.) linkleri at
