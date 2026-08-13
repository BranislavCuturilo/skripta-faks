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

from app import config, db, server  # noqa: E402  - uvoz servera registruje i rute


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
    local_url = f"http://localhost:{port}"
    phone_url = f"http://{server.lan_address()}:{port}"

    print()
    print(f"  Na ovom racunaru : {local_url}")
    print(f"  Na telefonu      : {phone_url}   (isti Wi-Fi)")
    print()
    print("  Zaustavljanje: Ctrl+C, ili samo zatvori ovaj prozor.")
    print("-" * 64)

    httpd = server.build(port)
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
