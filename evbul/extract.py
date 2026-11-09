"""İlan metninden müsaitlik tarihi ve kira süresi çıkarımı.

1) Kurallarla (ücretsiz, çevrimdışı): NL + EN kalıplar.
2) İsteğe bağlı yapay zekâ (Claude API): kuralların çözemediği ilanlar için.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, timedelta

import requests

log = logging.getLogger("evbul")

MONTHS = {
    # EN
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4,
    "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9,
    "september": 9, "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
    # NL
    "januari": 1, "februari": 2, "maart": 3, "mei": 5, "juni": 6, "juli": 7, "augustus": 8,
    "okt": 10, "oktober": 10,
}
_MON = "|".join(sorted(MONTHS, key=len, reverse=True))

DATE_NUM = r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})"
DATE_TXT = rf"(\d{{1,2}})(?:st|nd|rd|th|e)?\s+({_MON})\.?,?\s+(\d{{4}})"
ANY_DATE = rf"(?:{DATE_NUM}|{DATE_TXT})"

NOW_RE = re.compile(r"\b(per direct|direct beschikbaar|per omgaande|immediately|available now|"
                    r"available immediately|beschikbaar per direct|asap)\b", re.I)
AVAIL_RE = re.compile(rf"(?:available|beschikbaar(?:heid)?|vanaf|from|per|ingangsdatum|start(?:ing)?|"
                      rf"move[- ]in)\s*(?:date)?\s*(?:from|per|vanaf|on)?\s*:?\s*{ANY_DATE}", re.I)
RANGE_RE = re.compile(rf"{ANY_DATE}\s*(?:-|–|t/m|tot|until|to|till)\s*{ANY_DATE}", re.I)

INDEFINITE_RE = re.compile(r"\b(onbepaalde tijd|indefinite(?:ly)?|unlimited|long[- ]term|"
                           r"lange termijn|permanent)\b", re.I)
SHORT_RE = re.compile(r"\b(short[- ]stay|short[- ]term|korte termijn|tijdelijk(?:e)? huur|"
                      r"temporary rental|tijdelijke verhuur|kort verblijf|holiday rental)\b", re.I)
_UNIT = r"(maanden|maand|months?|mnd|jaar|jaren|years?|yr)"
MIN_RE = re.compile(rf"(?:minimaal|minimum|min\.?|at least|ten minste)\s*(?:huur(?:periode|termijn)?|"
                    rf"rental period|stay|period|duration)?\s*:?\s*(\d+)\s*{_UNIT}", re.I)
MAX_RE = re.compile(rf"(?:maximaal|maximum|max\.?|up to|tot)\s*(?:huur(?:periode|termijn)?|"
                    rf"rental period|stay|period|duration)?\s*:?\s*(\d+)\s*{_UNIT}", re.I)
FOR_RE = re.compile(rf"(?:for|voor|periode van|period of|contract (?:of|van))\s+(\d+)\s*{_UNIT}", re.I)


def _to_date(groups) -> date | None:
    g = [x for x in groups if x is not None]
    try:
        if len(g) == 3 and g[1].isdigit():
            d, m, y = map(int, g)
        else:
            d, m, y = int(g[0]), MONTHS[g[1].lower().rstrip(".")], int(g[2])
        return date(y, m, d)
    except (ValueError, KeyError, IndexError):
        return None


def _months(n: str, unit: str) -> int:
    return int(n) * (12 if unit.lower().startswith(("j", "y")) else 1)


def rule_extract(text: str, today: date | None = None) -> dict:
    """Döner: {available_from: 'YYYY-MM-DD'|None, min_months, max_months, stay}"""
    today = today or date.today()
    t = re.sub(r"\s+", " ", text or "")
    out = {"available_from": None, "min_months": None, "max_months": None, "stay": None}

    rng = RANGE_RE.search(t)
    if rng:
        a, b = _to_date(rng.groups()[:6]), _to_date(rng.groups()[6:])
        if a and b and b > a:
            out["available_from"] = a.isoformat()
            months = round((b - a).days / 30.4)
            out["max_months"] = months
            out["min_months"] = out["min_months"] or None
    if not out["available_from"]:
        if (m := AVAIL_RE.search(t)) and (d := _to_date(m.groups())):
            out["available_from"] = d.isoformat()
        elif NOW_RE.search(t):
            out["available_from"] = today.isoformat()
    if out["available_from"] and out["available_from"] < today.isoformat():
        out["available_from"] = today.isoformat()      # geçmiş tarih = hemen

    if m := MIN_RE.search(t):
        out["min_months"] = _months(*m.groups())
    if m := MAX_RE.search(t):
        out["max_months"] = _months(*m.groups())
    if out["min_months"] is None and out["max_months"] is None and (m := FOR_RE.search(t)):
        out["min_months"] = out["max_months"] = _months(*m.groups())

    # rakamlar anahtar kelimelerden önce gelir ("tijdelijk, max 18 maanden" = uzun dönem mümkün)
    mn, mx = out["min_months"], out["max_months"]
    if (mn or 0) >= 12 or (mx is not None and mx >= 12):
        out["stay"] = "long"
    elif mx is not None and mx < 12:
        out["stay"] = "short"
    elif INDEFINITE_RE.search(t):
        out["stay"] = "long"
    elif SHORT_RE.search(t):
        out["stay"] = "short"
    return out


# ---------------- yapay zekâ (isteğe bağlı) ----------------

AI_PROMPT = """You read Dutch/English rental listings. Today is {today}.
Return ONLY a JSON object with these keys:
"available_from": move-in date as YYYY-MM-DD (today's date if available immediately, null if not stated),
"min_months": minimum rental period in months (integer or null),
"max_months": maximum rental period in months (integer or null, null if indefinite),
"stay": "short" if the rental is limited to under 12 months, "long" if 12+ months or indefinite, null if unclear.

Listing:
\"\"\"{text}\"\"\""""


def ai_extract(text: str, api_key: str, model: str = "claude-haiku-5-5") -> dict | None:
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": model, "max_tokens": 200, "messages": [{"role": "user", "content":
                  AI_PROMPT.format(today=date.today().isoformat(), text=text[:6000])}]},
            timeout=30)
        r.raise_for_status()
        raw = r.json()["content"][0]["text"]
        data = json.loads(re.search(r"\{.*\}", raw, re.S).group())
        out = {k: data.get(k) for k in ("available_from", "min_months", "max_months", "stay")}
        if out["stay"] not in ("short", "long"):
            out["stay"] = None
        if out["available_from"] and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(out["available_from"])):
            out["available_from"] = None
        return out
    except Exception as e:  # noqa: BLE001
        log.warning("Yapay zekâ çıkarımı başarısız: %s", e)
        return None


def analyze(text: str, ai_cfg: dict | None = None, ai_text: str | None = None) -> dict:
    """Önce kurallar (tüm sayfa metni); eksik kalan alanlar için, anahtar varsa,
    yapay zekâ (açıklama metni)."""
    res = rule_extract(text)
    key = (ai_cfg or {}).get("api_key") or os.environ.get("ANTHROPIC_API_KEY")
    if key and (ai_cfg or {}).get("enabled", True) and (ai_text or text) and \
            (res["stay"] is None or res["available_from"] is None):
        ai = ai_extract(ai_text or text, key, (ai_cfg or {}).get("model", "claude-haiku-5-5"))
        if ai:
            for k, v in ai.items():
                if res.get(k) is None and v is not None:
                    res[k] = v
            res["ai"] = True
    return res
