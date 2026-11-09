"""Gerçek bir Chrome penceresi üzerinden sayfa açan getirici.

Nasıl çalışır:
- Normal bir Chrome penceresini, ayrı bir "FindHouseInNL" profiliyle başlatır (otomasyon
  modunda değil). Pencere zaten açıksa yenisini açmaz, ona bağlanır.
- Uygulama bu pencerede kendi sekmesini kullanır; sen pencereyi açık bırakırsın.
- Çerezler/oturumlar browser_profile/ klasöründe kalıcıdır.
- Doğrulama sayfası çıkarsa DURUR, haber verir ve senin tamamlamanı bekler.
  Captcha çözmeye ya da gizlenmeye çalışmaz.

Not: Chrome, ana (günlük) profilinin dışarıdan kontrol edilmesine izin vermediği
için ayrı bir profil kullanıyoruz.
"""
from __future__ import annotations

import json
import logging
import os
import random
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

from .sources.base import Blocked, looks_blocked

log = logging.getLogger("evbul")


def find_browser() -> str | None:
    env = os.environ
    cands = [
        Path(env.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
        Path(env.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
        Path(env.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
        Path(env.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
        Path(env.get("PROGRAMFILES", r"C:\Program Files")) / "Microsoft/Edge/Application/msedge.exe",
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    ]
    for c in cands:
        if str(c) and c.is_file():
            return str(c)
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chrome"):
        if p := shutil.which(name):
            return p
    return None


def _cdp_alive(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as r:
            return "webSocketDebuggerUrl" in json.loads(r.read())
    except Exception:  # noqa: BLE001
        return False


def ensure_chrome(port: int, profile_dir: str, extra_args: list[str] | None = None) -> None:
    """FindHouseInNL Chrome penceresi açık değilse normal şekilde başlatır."""
    if _cdp_alive(port):
        return
    exe = find_browser()
    if not exe:
        raise RuntimeError("Chrome ya da Edge bulunamadı.")
    profile = str(Path(profile_dir).resolve())
    args = [exe, f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
            "--no-first-run", "--no-default-browser-check", *(extra_args or []),
            "about:blank"]
    log.info("FindHouseInNL Chrome penceresi açılıyor (%s)", Path(exe).name)
    flags = 0x00000008 | 0x00000200 if os.name == "nt" else 0   # DETACHED | NEW_PROCESS_GROUP
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=flags, start_new_session=os.name != "nt")
    for _ in range(40):
        if _cdp_alive(port):
            return
        time.sleep(0.5)
    raise RuntimeError("Chrome açıldı ama bağlanılamadı. Başka bir FindHouseInNL penceresi takılı kalmış "
                       "olabilir: tüm Chrome pencerelerini kapatıp tekrar dene.")


class BrowserFetcher:
    def __init__(self, profile_dir="browser_profile", port=9222, on_challenge=None,
                 wait_minutes=5, extra_args=None, **_):
        from playwright.sync_api import sync_playwright
        self.on_challenge = on_challenge
        self.wait_s = wait_minutes * 60
        self.port, self.profile_dir, self.extra_args = port, profile_dir, extra_args
        self.pw = sync_playwright().start()
        self._connect()

    def _connect(self):
        ensure_chrome(self.port, self.profile_dir, self.extra_args)
        self.browser = self.pw.chromium.connect_over_cdp(f"http://127.0.0.1:{self.port}")
        self.ctx = self.browser.contexts[0] if self.browser.contexts else self.browser.new_context()
        self.page = self.ctx.new_page()   # uygulamanın kendi sekmesi
        log.info("FindHouseInNL Chrome'a bağlandı.")

    def _alive(self) -> bool:
        try:
            return self.browser.is_connected() and not self.page.is_closed()
        except Exception:  # noqa: BLE001
            return False

    def _content(self) -> str:
        for _ in range(5):
            try:
                return self.page.content()
            except Exception:  # noqa: BLE001  (sayfa o an yönleniyorsa)
                self.page.wait_for_timeout(1000)
        return ""

    def _wait_for_human(self, url: str):
        if not looks_blocked(self._content()):
            return
        log.warning(">>> DOĞRULAMA GEREKİYOR: FindHouseInNL Chrome penceresinde 'insanım' adımını tamamla "
                    "(%d dk bekliyorum) — %s", self.wait_s // 60, url)
        if self.on_challenge:
            self.on_challenge(url)
        try:
            self.page.bring_to_front()
        except Exception:  # noqa: BLE001
            pass
        deadline = time.time() + self.wait_s
        while time.time() < deadline:
            self.page.wait_for_timeout(2000)
            if not looks_blocked(self._content()):
                log.info("Doğrulama geçti, devam ediyorum.")
                self.page.wait_for_timeout(1500)
                return
        raise Blocked(f"doğrulama zaman aşımı @ {url}")

    def html(self, url: str) -> str:
        if not self._alive():          # pencereyi/sekmeyi kapattıysan yeniden aç
            log.info("Chrome bağlantısı kopmuş, yeniden bağlanıyorum.")
            self._connect()
        time.sleep(random.uniform(2.0, 4.0))
        self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
        self._wait_for_human(url)
        try:
            self.page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:  # noqa: BLE001
            pass
        return self._content()

    def post_json(self, url: str, payload: dict, origin: str | None = None) -> dict:
        """API çağrısını sitenin kendi sayfasının içinden yapar (gerçek ziyaretçi gibi)."""
        if origin and not self.page.url.startswith(origin):
            self.html(origin)
        res = self.page.evaluate(
            """async ([u, p]) => {
                 const r = await fetch(u, {method: 'POST', credentials: 'include',
                   headers: {'Content-Type': 'application/json'}, body: JSON.stringify(p)});
                 return {status: r.status, body: await r.text()};
               }""", [url, payload])
        if res["status"] in (403, 429):
            raise Blocked(f"{res['status']} @ {url}")
        return json.loads(res["body"])

    def close(self):
        """Sadece kendi sekmemizi kapatır; Chrome penceresi açık kalır."""
        try:
            if not self.page.is_closed():
                self.page.close()
        except Exception:  # noqa: BLE001
            pass
        self.pw.stop()
