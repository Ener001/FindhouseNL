"""Yeni sürüm kontrolü ve tek tıkla güncelleme.

- Repoya atılan her commit yeni bir sürüm sayılır (GitHub'daki son commit'e bakılır).
- Kod ZIP olarak indirildiyse: "Güncelle" düğmesi yeni kodu indirip kurar;
  config.yaml, veritabanı, tarayıcı profili ve debug klasörü korunur.
- Klasör bir git reposuysa (geliştiricinin kendi bilgisayarı) bildirim gösterilmez.
- Windows kurulum dosyasıyla kurulduysa (.exe): GitHub Releases'teki son kurulum dosyasına
  bakılır; "Güncelle" yeni kurulum dosyasını indirip çalıştırır, program kendini yeniden açar.
"""
from __future__ import annotations

import io
import json
import logging
import os
import shutil
import subprocess
import sys
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

RELEASES = f"https://api.github.com/repos/{REPO}/releases/latest"
SETUP_NAME = "FindHouseInNL-Setup.exe"
FROZEN = getattr(sys, "frozen", False)

ROOT = Path(__file__).resolve().parent.parent
# kurulu sürümde program klasörüne yazılmaz; durum dosyası veri klasöründe (çalışma dizini) tutulur
STATE = (Path.cwd() if FROZEN else ROOT) / ".version"
KEEP = {"config.yaml", "evbul.db", "evbul.db-journal", "browser_profile", "debug", ".version", ".git", ".venv"}

_cache: dict = {"at": 0.0, "info": None}


def is_dev_checkout() -> bool:
    return not FROZEN and (ROOT / ".git").exists()


def _build() -> int:
    try:
        from ._build import BUILD
        return int(BUILD)
    except Exception:  # noqa: BLE001
        return 0


def latest_release() -> dict | None:
    """GitHub Releases'teki son Windows kurulum dosyası: {build, sha, message, url}"""
    try:
        r = requests.get(RELEASES, timeout=10, headers={"Accept": "application/vnd.github+json",
                                                        "User-Agent": "FindHouseInNL"})
        if r.status_code != 200:
            return None
        j = r.json()
        tag = j.get("tag_name") or ""
        build = int(tag.lstrip("bv").split(".")[-1]) if tag.lstrip("bv").replace(".", "").isdigit() else 0
        url = next((a["browser_download_url"] for a in j.get("assets") or [] if a.get("name") == SETUP_NAME), None)
        if not build or not url:
            return None
        msg = (j.get("body") or j.get("name") or "").strip().split("\n")[0][:140]
        return {"build": build, "sha": tag, "message": msg, "date": j.get("published_at", ""), "url": url}
    except Exception as e:  # noqa: BLE001
        log.info("güncelleme kontrolü yapılamadı: %s", e)
        return None


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
    if FROZEN:
        rel = latest_release()
        if rel is not None:
            _cache["info"] = rel if rel["build"] > _build() else None
        return _cache["info"]
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
    if FROZEN:
        return _apply_installer()
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


def _apply_installer() -> dict:
    """Yeni kurulum dosyasını indirip sessizce çalıştırır; kurulum bitince program kendini açar."""
    rel = latest_release()
    if not rel:
        return {"ok": False, "error": "Yeni sürüm bilgisi alınamadı, biraz sonra tekrar dene."}
    dst = Path(tempfile.gettempdir()) / SETUP_NAME
    with requests.get(rel["url"], timeout=300, stream=True, headers={"User-Agent": "FindHouseInNL"}) as r:
        r.raise_for_status()
        with open(dst, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)
    subprocess.Popen([str(dst), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                     creationflags=0x00000008 if os.name == "nt" else 0)   # DETACHED_PROCESS
    # kurulum programı bu programı kapatıp yenisini açar; biz de hemen çıkalım
    import threading
    threading.Timer(2.0, lambda: os._exit(0)).start()
    log.info("Güncelleme kuruluyor → sürüm %s", rel["build"])
    return {"ok": True, "installer": True, "sha": rel["sha"]}
