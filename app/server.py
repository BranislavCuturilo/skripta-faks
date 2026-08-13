"""HTTP server nad standardnom bibliotekom.

Aplikacija je JSON API + staticka SPA ljuska. Nema template engine-a jer nema
zavisnosti: server servira `web/`, a renderovanje radi browser.
"""

import os
import socket
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import config, db, netinfo
from .http_util import (
    HttpError,
    Request,
    Response,
    error_response,
    file_response,
    json_response,
    parse_multipart,
    temp_directory,
)
from .router import router

# Uvoz puni ruter. Stoji ovde, a ne u run.py, jer server bez ruta odgovara 404
# na sve - a to ne izgleda kao "zaboravljen uvoz" nego kao pokvaren ruter.
from . import api  # noqa: E402,F401  - registruje rute

_STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "skripta-faks"
    sys_version = ""

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_PUT(self) -> None:
        self._dispatch("PUT")

    def do_PATCH(self) -> None:
        self._dispatch("PATCH")

    def do_DELETE(self) -> None:
        self._dispatch("DELETE")

    def do_HEAD(self) -> None:
        self._dispatch("GET", head_only=True)

    def log_message(self, fmt: str, *args) -> None:
        # Podrazumevani log je bucan i ide na stderr sa cudnim formatom.
        pass

    # ------------------------------------------------------------------

    def _dispatch(self, method: str, head_only: bool = False) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        request = None
        try:
            if path.startswith("/api/"):
                request = self._build_request(method, path, parsed.query)
                handler, params = router.resolve(method, path)
                request.params = params
                response = handler(request)
            elif path.startswith("/media/"):
                response = self._serve_media(path)
            else:
                response = self._serve_static(path)
        except HttpError as exc:
            response = error_response(exc.status, exc.message, exc.detail)
        except BrokenPipeError:
            return
        except Exception as exc:  # noqa: BLE001 - spoljna granica zahteva
            traceback.print_exc()
            response = error_response(500, "Interna greska aplikacije.", str(exc))
        finally:
            if request is not None:
                request.discard_files()

        self._send(response, head_only=head_only)

    def _build_request(self, method: str, path: str, query: str) -> Request:
        headers = {key.lower(): value for key, value in self.headers.items()}
        content_type = headers.get("content-type", "")
        length = int(headers.get("content-length") or 0)

        request = Request(
            method=method,
            path=path,
            raw_query=query,
            headers=headers,
            client_ip=self.client_address[0] if self.client_address else "",
        )

        if length > config.MAX_BODY_BYTES:
            raise HttpError(413, "Zahtev je prevelik.")

        if content_type.startswith("multipart/form-data"):
            request.form, request.files = parse_multipart(
                self.rfile, content_type, length, config.MAX_BODY_BYTES, temp_directory()
            )
        elif length:
            request.body = self.rfile.read(length)

        return request

    def _serve_static(self, path: str) -> Response:
        if path in ("/", ""):
            path = "/index.html"
        candidate = (config.WEB_DIR / path.lstrip("/")).resolve()
        try:
            candidate.relative_to(config.WEB_DIR.resolve())
        except ValueError:
            raise HttpError(404, "Ne postoji.") from None

        if not candidate.is_file():
            # SPA: nepoznata putanja bez tacke je ruta u browseru, ne fajl.
            if "." in Path(path).name:
                raise HttpError(404, "Ne postoji.")
            candidate = config.WEB_DIR / "index.html"
            if not candidate.is_file():
                raise HttpError(404, "Aplikacija nije instalirana ispravno (nema web/index.html).")

        body = candidate.read_bytes()
        content_type = _STATIC_TYPES.get(candidate.suffix.lower(), "application/octet-stream")
        cache = "no-store" if candidate.suffix.lower() == ".html" else "no-cache"
        return Response(
            status=200,
            headers={
                "Content-Type": content_type,
                "Cache-Control": cache,
                "X-Content-Type-Options": "nosniff",
            },
            body=body,
        )

    def _serve_media(self, path: str) -> Response:
        relative = path[len("/media/") :]
        if not relative:
            raise HttpError(404, "Ne postoji.")
        candidate = (config.DATA_DIR / relative).resolve()
        try:
            candidate.relative_to(config.DATA_DIR.resolve())
        except ValueError:
            raise HttpError(404, "Ne postoji.") from None
        return file_response(candidate, inline=True)

    def _send(self, response: Response, head_only: bool = False) -> None:
        headers = dict(response.headers)
        try:
            if response.stream is not None:
                self.send_response(response.status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.end_headers()
                if not head_only:
                    for chunk in response.stream():
                        self.wfile.write(chunk)
                return

            body = response.body or b""
            headers.setdefault("Content-Type", "text/plain; charset=utf-8")
            headers["Content-Length"] = str(len(body))
            self.send_response(response.status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            if not head_only and body:
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            return


class Server(ThreadingHTTPServer):
    daemon_threads = True
    # NIKAD True na Windows-u. Tamo SO_REUSEADDR ne znaci "preuzmi port koji je
    # u TIME_WAIT" kao na Unix-u, nego "dozvoli i drugom procesu da slusa na
    # istom portu". Posledica: dve aplikacije tiho dele port i zahtevi odlaze
    # cas jednoj cas drugoj. Izgleda kao pokvaren ruter, a nije.
    allow_reuse_address = os.name != "nt"

    def shutdown_request(self, request) -> None:  # noqa: D102
        super().shutdown_request(request)
        db.close_thread_connection()


def lan_address() -> str:
    """Zadrzano zbog run.py; pravi posao je u netinfo."""
    return netinfo.lan_address()


def find_free_port(preferred: int, attempts: int) -> int:
    """Prvi port koji STVARNO niko ne drzi.

    Probni soket namerno NEMA SO_REUSEADDR: sa njim `bind` na Windows-u uspeva i
    kad port vec neko koristi, pa bi provera uvek govorila "slobodno" i server
    bi se tiho podelio sa tudjom aplikacijom.
    """
    for offset in range(attempts):
        candidate = preferred + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if os.name == "nt":
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            try:
                probe.bind(("0.0.0.0", candidate))
                probe.listen(1)
            except OSError:
                continue
        return candidate
    raise RuntimeError(
        f"Nema slobodnog porta u opsegu {preferred}-{preferred + attempts - 1}. "
        "Zatvori aplikaciju koja ih drzi, ili promeni DEFAULT_PORT u app/config.py."
    )


def build(port: int, host: str = "0.0.0.0") -> Server:
    """Podrazumevano slusa na svim adresama - to je ono sto omogucava telefon.

    Testovi prosledjuju 127.0.0.1 da Windows ne bi pitao za dozvolu firewall-a
    na svakom pokretanju suite-a.
    """
    netinfo.RUNNING_PORT = port
    return Server((host, port), Handler)
