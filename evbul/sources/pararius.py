"""Pararius (pararius.com) — oda, stüdyo, daire, ev."""
from __future__ import annotations

from urllib.parse import urljoin

from ..models import Listing, parse_furnished, parse_int, parse_price, split_postcode_city
from .base import Source, text

BASE = "https://www.pararius.com"


class Pararius(Source):
    name = "pararius"

    def fetch(self, city: str, max_pages: int = 2) -> list[Listing]:
        out = []
        slug = city.lower().replace(" ", "-")
        price = ""
        if self.opts.get("max_price"):
            price = f"/{self.opts.get('min_price', 0)}-{self.opts['max_price']}"
        for page in range(1, max_pages + 1):
            url = f"{BASE}/apartments/{slug}{price}" + (f"/page-{page}" if page > 1 else "")
            items = self.parse(self.soup(url).select("section.listing-search-item"), city)
            out += items
            if not items:
                break
        return out

    def parse(self, cards, city: str) -> list[Listing]:
        res = []
        for c in cards:
            a = c.select_one("a.listing-search-item__link--title") or c.select_one("h2 a")
            if not a:
                continue
            pc, cty = split_postcode_city(text(c.select_one(".listing-search-item__sub-title")))
            img = c.select_one("img")
            res.append(Listing(
                source=self.name,
                url=urljoin(BASE, a.get("href", "")),
                title=text(a),
                address=text(a),
                postcode=pc,
                city=cty or city,
                price=parse_price(text(c.select_one(".listing-search-item__price"))),
                area_m2=parse_int(text(c.select_one(".illustrated-features__item--surface-area"))),
                rooms=parse_int(text(c.select_one(".illustrated-features__item--number-of-rooms"))),
                furnished=parse_furnished(text(c.select_one(".illustrated-features__item--interior"))),
                image=(img.get("src") or img.get("data-src")) if img else None,
            ))
        return res
