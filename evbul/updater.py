"""Yeni sürüm kontrolü ve tek tıkla güncelleme.

- Repoya atılan her commit yeni bir sürüm sayılır (GitHub'daki son commit'e bakılır).
- Kod ZIP olarak indirildiyse: "Güncelle" düğmesi yeni kodu indirip kurar;
  config.yaml, veritabanı, tarayıcı profili ve debug klasörü korunur.
- Klasör bir git reposuysa (geliştiricinin kendi bilgisayarı) bildirim gösterilmez.
"""
from __future__ import annotations

import io
import json
import logging
import shutil
import tempfile
import time
import zipfile
from pathlib import Path

import requests

log = logging.getLogger("evbul")

REPO = "Ener001/FindhouseNL"
BRANCH = "master"
API = f"https://api.github.com/repos/{REPO}/commits/{BRANCH}"
ZIP = f"https://codeload.github.com/{REPO}/zip/refs/heads/{BRANCH}"

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / ".version"
KEEP = {"config.yaml", "evbul.db", "evbul.db-journal", "browser_profile", "debug", ".version", ".git", ".venv"}

_cache: dict = {"at": 0.0, "info": None}


def is_dev_checkout() -> bool:
    return (ROOT / ".git").exists()


def _read_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _write_state(d: dict):
    try:
        STATE.write_text(json.dumps(d), encoding="utf-8")
    except OSError as e:
        log.warning("sürüm bilgisi yazılamadı: %s", e)


def latest() -> dict | None:
    """GitHub'daki son commit: {sha, message, date}"""
    try:
        r = requests.get(API, timeout=10, headers={"Accept": "application/vnd.github+json",
                                                   "User-Agent": "FindHouseInNL"})
        if r.status_code != 200:
            return None
        j = r.json()
        c = j.get("commit") or {}
        return {"sha": j.get("sha", ""), "message": (c.get("message") or "").split("\n")[0][:140],
                "date": (c.get("committer") or {}).get("date", "")}
    except Exception as e:  # noqa: BLE001
        log.info("güncelleme kontrolü yapılamadı: %s", e)
        return None


def check(max_age_s: int = 1800) -> dict | None:
    """Yeni sürüm varsa {sha, message, date} döner, yoksa None."""
    if is_dev_checkout():
        return None
    now = time.time()
    if now - _cache["at"] < max_age_s:
        return _cache["info"]
    _cache["at"] = now
    lt = latest()
    if not lt or not lt["sha"]:
        return _cache["info"]
    st = _read_state()
    if not st.get("sha"):
        # ilk çalıştırma: yeni indirilmiş kod en güncel kabul edilir
        _write_state({"sha": lt["sha"], "installed_at": now})
        _cache["info"] = None
        return None
    _cache["info"] = lt if lt["sha"] != st["sha"] else None
    return _cache["info"]


def should_announce(info: dict) -> bool:
    """Aynı sürüm için Telegram'a bir kez haber ver."""
    st = _read_state()
    if st.get("announced") == info["sha"]:
        return False
    st["announced"] = info["sha"]
    _write_state(st)
    return True


def apply_update() -> dict:
    """Son kodu indirip kurar. Kullanıcı verileri korunur."""
    if is_dev_checkout():
        return {"ok": False, "error": "Bu klasör bir git reposu; 'git pull' kullan."}
    lt = latest()
    r = requests.get(ZIP, timeout=60, headers={"User-Agent": "FindHouseInNL"})
    r.raise_for_status()
    with tempfile.TemporaryDirectory() as tmp:
        zipfile.ZipFile(io.BytesIO(r.content)).extractall(tmp)
        roots = [p for p in Path(tmp).iterdir() if p.is_dir()]
        if len(roots) != 1 or not (roots[0] / "run.py").exists():
            return {"ok": False, "error": "İndirilen paket beklenen biçimde değil."}
        src = roots[0]
        for item in src.iterdir():
            if item.name in KEEP:
                continue
            dst = ROOT / item.name
            if item.is_dir():
                shutil.copytree(item, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dst)
    st = _read_state()
    st.update({"sha": (lt or {}).get("sha", st.get("sha")), "installed_at": time.time()})
    _write_state(st)
    _cache.update({"at": 0.0, "info": None})
    log.info("Güncellendi → %s", (lt or {}).get("sha", "?")[:7])
    return {"ok": True, "sha": (lt or {}).get("sha", "")}
