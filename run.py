#!/usr/bin/env python3
"""Pokretac aplikacije. Dupli klik na START.bat zavrsi ovde."""

import sys
import threading
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Windows konzola je cp1252 i ubije proces na prvom c/c/s/z/dj. Ovo mora da se
# desi pre ijednog print-a.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

# Ugradnja preuzete verzije mora da se desi PRE uvoza ostatka aplikacije: posle
# uvoza je stari kod vec u memoriji, pa bi se do restarta izvrsavala verzija
# koja vise ne stoji na disku. Na Windows-u ovo obicno nema sta da nadje -
# tamo posao odradi azuriraj.bat, jos ranije.
from app.services import updater  # noqa: E402

_installed = updater.install_pending()
if _installed:
    print(f"  Ugradjena nova verzija: {_installed.get('version', '?')}")

from app import config, db, netinfo, server  # noqa: E402  - uvoz servera registruje i rute


BANNER = r"""
   _____ _   _______ _____ _____ _______ _____
  / ____| | / /  __ \_   _|  __ \__   __/ ____|
 | (___ | |/ /| |__) || | | |__) | | | | |___
  \___ \|   < |  _  / | | |  ___/  | |  \___ \
  ____) | |\ \| | \ \_| |_| |      | |  ____) |
 |_____/|_| \_\_|  \_\_____|_|      |_| |_____/    faks
"""


def main() -> int:
    print(BANNER)
    config.ensure_dirs()

    applied = db.init_db()
    if applied:
        print(f"  Baza: primenjeno migracija: {applied}")
    print(f"  Baza: {config.DB_PATH}")

    port = server.find_free_port(config.DEFAULT_PORT, config.PORT_SEARCH_RANGE)
    httpd = server.build(port)
    network = netinfo.info(port)
    local_url = network["local_url"]

    print()
    print(f"  Na ovom racunaru : {local_url}")
    if network["addresses"]:
        print(f"  Na telefonu      : {network['phone_url']}   (isti Wi-Fi)")
        for item in network["addresses"][1:]:
            note = f"   ({item['hint']})" if item["hint"] else ""
            print(f"                     {item['url']}{note}")
    else:
        print("  Na telefonu      : nema mrezne adrese - racunar nije na mrezi")
    print()
    print("  Iste adrese pisu i u aplikaciji, na pocetnom ekranu.")
    print("  Zaustavljanje: Ctrl+C, ili samo zatvori ovaj prozor.")
    print("-" * 64)
    threading.Timer(0.8, lambda: webbrowser.open(local_url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Gasim server...")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
