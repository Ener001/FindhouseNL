"""Tüm site adaptörlerinin temel sınıfı + basit HTTP getirici."""
from __future__ import annotations

import json
import logging
import random
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from ..models import Listing

log = logging.getLogger("evbul")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

BLOCK_TITLES = ("just a moment", "je bent bijna op de pagina", "attention required",
                "access denied", "are you a robot", "toegang geweigerd",
                "even geduld", "een moment geduld", "één moment")


class Blocked(Exception):
    """Site captcha / bot koruması döndürdü."""


def looks_blocked(html: str) -> bool:
    m = re.search(r"<title[^>]*>(.*?)</title>", html[:30000], re.I | re.S)
    title = (m.group(1) if m else "").strip().lower()
    return any(t in title for t in BLOCK_TITLES)


class HttpFetcher:
    """Tarayıcısız mod (hızlı ama korumalı sitelerde engellenir)."""

    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8"})

    def html(self, url: str) -> str:
        time.sleep(random.uniform(1.0, 2.5))
        r = self.s.get(url, timeout=20)
        if r.status_code in (403, 429) or looks_blocked(r.text):
            raise Blocked(f"{r.status_code} @ {url}")
        r.raise_for_status()
        return r.text

    def post_json(self, url: str, payload: dict, origin: str | None = None) -> dict:
        r = self.s.post(url, json=payload, timeout=20)
        if r.status_code in (403, 429):
            raise Blocked(f"{r.status_code} @ {url}")
        return r.json()

    def close(self):
        pass


class Source:
    name = "base"

    def __init__(self, opts: dict | None = None, debug_dir: str | None = None, fetcher=None):
        self.opts = opts or {}
        self.debug_dir = Path(debug_dir) if debug_dir else None
        self.fetcher = fetcher or HttpFetcher()

    def fetch(self, city: str, max_pages: int = 2) -> list[Listing]:
        raise NotImplementedError

    def html(self, url: str) -> str:
        try:
            text = self.fetcher.html(url)
        except Blocked as e:
            raise Blocked(f"{self.name}: {e}") from None
        self._dump(url, text)
        return text

    def soup(self, url: str) -> BeautifulSoup:
        return BeautifulSoup(self.html(url), "html.parser")

    def _dump(self, url: str, text: str):
        if self.debug_dir:
            self.debug_dir.mkdir(parents=True, exist_ok=True)
            fn = self.debug_dir / f"{self.name}_{abs(hash(url)) % 10**8}.html"
            fn.write_text(text, encoding="utf-8")
            log.info("debug: %s -> %s", url, fn)


def jsonld_objects(soup: BeautifulSoup) -> list[dict]:
    """Sayfadaki tüm JSON-LD nesnelerini düz liste olarak döndürür."""
    out = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            o = stack.pop()
            if isinstance(o, dict):
                out.append(o)
                for k in ("@graph", "itemListElement"):
                    if isinstance(o.get(k), list):
                        stack.extend(o[k])
                if isinstance(o.get("item"), dict):
                    stack.append(o["item"])
    return out


def text(el) -> str | None:
    return el.get_text(" ", strip=True) if el else None
