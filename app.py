"""FindHouseInNL masaüstü uygulaması (Windows kurulum dosyasının giriş noktası).

- Siyah komut penceresi yok: program arka planda çalışır, saatin yanında simgesi durur.
- Arayüz kendi penceresinde açılır (Edge'in "uygulama penceresi" modu, adres çubuğu yok).
- Veriler (ayarlar, ilanlar, tarayıcı profili) %LOCALAPPDATA%\\FindHouseInNL içinde durur;
  program güncellenince ya da kaldırılınca kaybolmaz.
- Zaten çalışıyorsa ikinci kopya açılmaz, sadece pencereyi öne getirir.

Geliştirici bilgisayarında da çalışır:  py app.py
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import urllib.request
import webbrowser
from pathlib import Path

PORT = 8000
URL = f"http://127.0.0.1:{PORT}"
FROZEN = getattr(sys, "frozen", False)
BUNDLE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
DATA = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "FindHouseInNL"


def already_running() -> bool:
    try:
        with urllib.request.urlopen(URL + "/api/stats", timeout=2) as r:
            return "total" in json.loads(r.read())
    except Exception:  # noqa: BLE001
        return False


def find_edge() -> str | None:
    env = os.environ
    for base in (env.get("PROGRAMFILES(X86)"), env.get("PROGRAMFILES"), env.get("LOCALAPPDATA")):
        if base:
            p = Path(base) / "Microsoft/Edge/Application/msedge.exe"
            if p.is_file():
                return str(p)
    return shutil.which("msedge")


def open_window() -> None:
    """Arayüzü adres çubuğu olmayan kendi penceresinde aç (olmazsa normal tarayıcıda)."""
    edge = find_edge()
    if edge:
        try:
            subprocess.Popen(
                [edge, f"--app={URL}", f"--user-data-dir={DATA / 'window'}", "--window-size=1320,880",
                 "--no-first-run", "--no-default-browser-check"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=0x08000000 if os.name == "nt" else 0)   # CREATE_NO_WINDOW
            return
        except OSError:
            pass
    webbrowser.open(URL)


def prepare_data_dir() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    example = BUNDLE / "config.example.yaml"
    if example.is_file():
        # her açılışta güncel örnek: yeni sürümle gelen siteler eski ayarlara otomatik eklenir
        shutil.copy2(example, DATA / "config.example.yaml")
        if not (DATA / "config.yaml").exists():
            shutil.copy2(example, DATA / "config.yaml")
    os.chdir(DATA)


def setup_logging() -> None:
    handlers: list[logging.Handler] = [logging.FileHandler(DATA / "log.txt", encoding="utf-8")]
    if sys.stderr is not None and not FROZEN:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%d.%m %H:%M:%S",
                        handlers=handlers)


def tray_image():
    from PIL import Image, ImageDraw
    s = 64
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((2, 2, s - 3, s - 3), radius=14, fill=(232, 89, 12, 255))
    d.polygon([(32, 13), (11, 31), (17, 31), (17, 51), (28, 51), (28, 39), (36, 39), (36, 51), (47, 51),
               (47, 31), (53, 31)], fill=(255, 255, 255, 255))
    return im


def main() -> None:
    if already_running():
        open_window()
        return
    prepare_data_dir()
    setup_logging()
    log = logging.getLogger("evbul")
    log.info("FindHouseInNL başlıyor (veri klasörü: %s)", DATA)

    sys.path.insert(0, str(BUNDLE))
    from evbul.core import load_config
    from evbul.db import DB
    from evbul.web import serve
    from run import worker

    cfg = load_config("config.yaml")
    wake, state = threading.Event(), {"scraping": False, "last_report": None}
    threading.Thread(target=worker, args=(cfg, "evbul.db", wake, state, cfg.get("interval_minutes", 10)),
                     daemon=True, name="tarama").start()
    server = threading.Thread(target=serve, args=(cfg, DB("evbul.db"), wake, state), kwargs={"port": PORT},
                              daemon=True, name="arayuz")
    server.start()

    # sunucu hazır olunca pencereyi aç
    def first_open():
        for _ in range(50):
            if already_running():
                break
            threading.Event().wait(0.2)
        open_window()
    threading.Thread(target=first_open, daemon=True).start()

    try:
        import pystray
    except ImportError:
        server.join()
        return

    def quit_app(icon, _item=None):
        icon.stop()
        os._exit(0)

    icon = pystray.Icon(
        "FindHouseInNL", tray_image(), "FindHouseInNL",
        menu=pystray.Menu(
            pystray.MenuItem("FindHouseInNL'i aç", lambda i, _: open_window(), default=True),
            pystray.MenuItem("Şimdi tara", lambda i, _: wake.set()),
            pystray.MenuItem("Veri klasörünü aç", lambda i, _: os.startfile(DATA) if os.name == "nt" else None),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Kapat", quit_app),
        ))
    icon.run()


if __name__ == "__main__":
    main()
