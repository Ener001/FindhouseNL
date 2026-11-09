"""Ortak ilan modeli + metin ayrıştırma yardımcıları."""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass

TYPES = ("room", "studio", "apartment", "house")


@dataclass
class Listing:
    source: str
    url: str
    title: str
    price: int | None = None          # EUR / ay
    city: str | None = None
    address: str | None = None
    postcode: str | None = None
    area_m2: int | None = None
    rooms: int | None = None
    type: str | None = None           # room | studio | apartment | house
    furnished: str | None = None      # furnished | upholstered | shell
    available_from: str | None = None   # YYYY-MM-DD
    image: str | None = None
    min_months: int | None = None
    max_months: int | None = None
    stay: str | None = None             # short | long

    def __post_init__(self):
        if not self.type:
            self.type = guess_type(f"{self.title} {self.address or ''}")
        if self.city:
            self.city = self.city.strip().title()

    @property
    def uid(self) -> str:
        return hashlib.sha1(f"{self.source}|{self.url}".encode()).hexdigest()[:16]

    @property
    def fingerprint(self) -> str:
        """Farklı sitelerdeki aynı evi yakalamak için kaba parmak izi."""
        street = normalize_address(self.address or self.title)
        price_bucket = (self.price or 0) // 50
        return hashlib.sha1(f"{self.city}|{street}|{price_bucket}".encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["uid"] = self.uid
        d["fingerprint"] = self.fingerprint
        return d


# ---------- ayrıştırma yardımcıları ----------

def parse_price(text: str | None) -> int | None:
    """'€ 1.250 per maand', '€1,750 per month', '1250.00' -> 1250"""
    if not text:
        return None
    m = re.search(r"\d[\d.,]*", text)
    if not m:
        return None
    s = re.sub(r"[.,](?=\d{3}(?!\d))", "", m.group())   # binlik ayırıcıları at
    s = s.replace(",", ".")
    try:
        return int(float(s))
    except ValueError:
        return None


def parse_int(text: str | None) -> int | None:
    if not text:
        return None
    m = re.search(r"\d+", text.replace(".", ""))
    return int(m.group()) if m else None


_TYPE_RULES = [
    ("studio", r"\bstudio"),
    ("room", r"^\s*(kamer|room|chambre)\b|\bshared room\b|\bkamer te huur\b"),
    ("apartment", r"\b(appartement|apartment|flat|bovenwoning|benedenwoning|penthouse|maisonnette|portiekflat)\b"),
    ("house", r"\b(huis|house|eengezinswoning|tussenwoning|hoekwoning|villa|woonhuis|twee-onder-een-kap)\b"),
    ("room", r"\b(kamer|room)\b"),
]


def guess_type(text: str) -> str | None:
    t = (text or "").lower()
    for typ, pattern in _TYPE_RULES:
        if re.search(pattern, t):
            return typ
    return None


def normalize_address(text: str) -> str:
    t = (text or "").lower()
    t = re.sub(r"^(appartement|apartment|kamer|room|studio|huis|house)\s+", "", t)
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def parse_furnished(text: str | None) -> str | None:
    t = (text or "").lower()
    if any(w in t for w in ("unfurnished", "kaal", "shell")):
        return "shell"
    if any(w in t for w in ("upholstered", "gestoffeerd")):
        return "upholstered"
    if any(w in t for w in ("furnished", "gemeubileerd")):
        return "furnished"
    return None


POSTCODE_RE = re.compile(r"\b(\d{4}\s?[A-Z]{2})\b")


def split_postcode_city(text: str | None) -> tuple[str | None, str | None]:
    """'1015 AB Amsterdam (Jordaan)' -> ('1015 AB', 'Amsterdam')"""
    if not text:
        return None, None
    text = re.sub(r"\(.*?\)", "", text).strip()
    m = POSTCODE_RE.search(text)
    if m:
        city = text[m.end():].strip(" ,") or None
        return m.group(1), city
    return None, text or None
