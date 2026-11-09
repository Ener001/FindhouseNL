"""Holland2Stay — Magento GraphQL API (beta).

Alan adları resmi olarak belgelenmemiş. Bilinmeyen bir alan sorulunca API
'Cannot query field "x"' hatası döner; bu durumda o alanı düşürüp tekrar
deniyoruz, böylece şema değişse bile çalışmaya devam eder.
"""
from __future__ import annotations

import re

from ..models import Listing, parse_price
from .base import Blocked, Source, log

API = "https://api.holland2stay.com/graphql/"
SITE = "https://www.holland2stay.com/residences/"

EXTRA_FIELDS = ["city", "basic_rent", "living_area", "no_of_rooms",
                "available_startdate", "available_to_book", "finishing", "type_of_contract"]
OPTION_ATTRS = ["city", "available_to_book", "no_of_rooms", "finishing"]


class Holland2Stay(Source):
    name = "holland2stay"
    _cache: list[Listing] | None = None

    def fetch(self, city: str, max_pages: int = 2) -> list[Listing]:
        if self._cache is None:
            self._cache = self._fetch_all(max_pages)
        return [l for l in self._cache if (l.city or "").lower() == city.lower()]

    # ---- GraphQL ----
    def _gql(self, query: str) -> dict:
        try:
            return self.fetcher.post_json(API, {"query": query}, origin="https://www.holland2stay.com/")
        except Blocked as e:
            raise Blocked(f"holland2stay: {e}") from None

    def _options(self) -> dict[str, dict[str, str]]:
        attrs = ",".join(f'{{attribute_code:"{a}",entity_type:"catalog_product"}}' for a in OPTION_ATTRS)
        try:
            data = self._gql(f"{{customAttributeMetadata(attributes:[{attrs}])"
                             "{items{attribute_code attribute_options{value label}}}}")
            return {i["attribute_code"]: {o["value"]: o["label"] for o in i.get("attribute_options") or []}
                    for i in data["data"]["customAttributeMetadata"]["items"]}
        except Blocked:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("holland2stay seçenek etiketleri alınamadı: %s", e)
            return {}

    def _fetch_all(self, max_pages: int) -> list[Listing]:
        opts = self._options()
        fields = list(EXTRA_FIELDS)
        out = []
        for page in range(1, max_pages * 3 + 1):
            for _ in range(len(EXTRA_FIELDS) + 1):
                q = ("{products(filter:{},pageSize:100,currentPage:%d){total_count items{"
                     "name url_key small_image{url} "
                     "price_range{minimum_price{regular_price{value}}} %s}}}" % (page, " ".join(fields)))
                data = self._gql(q)
                errs = data.get("errors") or []
                bad = [m.group(1) for e in errs
                       if (m := re.search(r'Cannot query field "(\w+)"', e.get("message", "")))]
                if bad:
                    fields = [f for f in fields if f not in bad]
                    continue
                if errs:
                    raise RuntimeError(errs[0].get("message"))
                break
            items = (data.get("data") or {}).get("products", {}).get("items") or []
            for it in items:
                l = self._to_listing(it, opts)
                if l:
                    out.append(l)
            if len(items) < 100:
                break
        log.info("holland2stay: %d ilan (alanlar: %s)", len(out), fields)
        return out

    def _to_listing(self, it: dict, opts: dict) -> Listing | None:
        def label(attr):
            v = it.get(attr)
            return opts.get(attr, {}).get(str(v), v) if v is not None else None

        avail = str(label("available_to_book") or "")
        if avail and re.search(r"not|occupied|booked|lottery", avail, re.I):
            return None
        price = it.get("basic_rent") or (it.get("price_range") or {}).get(
            "minimum_price", {}).get("regular_price", {}).get("value")
        rooms_label = str(label("no_of_rooms") or "")
        return Listing(
            source=self.name,
            url=SITE + (it.get("url_key") or "") + ".html",
            title=it.get("name") or "Holland2Stay",
            address=it.get("name"),
            city=str(label("city")) if label("city") else None,
            price=parse_price(str(price)) if price else None,
            area_m2=parse_price(str(it.get("living_area"))) if it.get("living_area") else None,
            rooms=int(m.group()) if (m := re.search(r"\d+", rooms_label)) else None,
            type="studio" if "studio" in rooms_label.lower() else
                 ("room" if "room" in rooms_label.lower() and "bedroom" not in rooms_label.lower() else
                  "apartment" if rooms_label else None),
            furnished="furnished" if "furnish" in str(label("finishing") or "").lower() else None,
            available_from=(str(it["available_startdate"])[:10] if it.get("available_startdate") else None),
            image=(it.get("small_image") or {}).get("url"),
        )
