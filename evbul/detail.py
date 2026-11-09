"""İlan detay sayfasından açıklama metnini çıkarır (siteye özel ayar gerektirmez)."""
from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

DESC_HINT = re.compile(r"descri|omschrijving|beschrijving|about|toelichting|details?-text|"
                       r"listing-detail|property-text|object-text", re.I)


def _clean(t: str) -> str:
    t = re.sub(r"[ \t\xa0]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n\n", t)
    return t.strip()


def extract_detail(html: str) -> tuple[str | None, str]:
    """Döner: (açıklama, sayfanın ana metni). Ana metin müsaitlik/süre çıkarımı için kullanılır."""
    soup = BeautifulSoup(html, "html.parser")

    jsonld_desc = None
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for o in (data if isinstance(data, list) else [data]):
            if isinstance(o, dict) and isinstance(o.get("description"), str) and len(o["description"]) > 120:
                jsonld_desc = o["description"]
    meta = soup.find("meta", attrs={"property": "og:description"}) or soup.find("meta", attrs={"name": "description"})
    meta_desc = meta.get("content") if meta else None

    for t in soup(["script", "style", "noscript", "svg", "nav", "header", "footer", "form", "aside", "iframe"]):
        t.decompose()
    for t in soup.find_all(attrs={"class": re.compile(r"cookie|consent|newsletter|footer|navbar|menu", re.I)}):
        t.decompose()
    page_text = _clean(soup.get_text("\n"))[:15000]

    # 1) adında "description/omschrijving" geçen en dolu blok
    best, best_len = None, 0
    for el in soup.find_all(attrs={"class": DESC_HINT}) + soup.find_all(attrs={"id": DESC_HINT}):
        txt = _clean(el.get_text("\n"))
        if 150 < len(txt) < 12000 and len(txt) > best_len:
            best, best_len = txt, len(txt)
    # 2) yoksa: en çok paragraf metni içeren kapsayıcı
    if not best:
        scores: dict = {}
        for p in soup.find_all("p"):
            txt = p.get_text(" ", strip=True)
            if len(txt) > 40 and p.parent is not None:
                scores[id(p.parent)] = scores.get(id(p.parent), (p.parent, 0))
                scores[id(p.parent)] = (p.parent, scores[id(p.parent)][1] + len(txt))
        if scores:
            el, n = max(scores.values(), key=lambda x: x[1])
            if n > 150:
                best = _clean(el.get_text("\n"))
    desc = best or jsonld_desc or meta_desc
    if desc and len(desc) > 5000:
        desc = desc[:5000].rsplit(" ", 1)[0] + "…"
    return desc, page_text
