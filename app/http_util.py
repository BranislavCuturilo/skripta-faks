"""Request/response sloj nad http.server.

Modul `cgi` je izbacen iz Pythona 3.13, pa multipart parsiramo sami. Parser je
streaming: delovi koji su fajlovi idu pravo na disk, nikad ceo snimak
predavanja u memoriju.
"""

import json
import mimetypes
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, Callable, Iterable, Optional
from urllib.parse import parse_qs, unquote


class HttpError(Exception):
    """Greska koju ruter pretvara u JSON odgovor sa datim statusom."""

    def __init__(self, status: int, message: str, detail: Any = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.detail = detail


@dataclass
class UploadedFile:
    field_name: str
    filename: str
    content_type: str
    temp_path: Path
    size: int

    def move_to(self, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(self.temp_path), str(destination))

    def discard(self) -> None:
        try:
            self.temp_path.unlink(missing_ok=True)
        except OSError:
            pass


@dataclass
class Request:
    method: str
    path: str
    raw_query: str
    headers: dict
    body: bytes = b""
    params: dict = field(default_factory=dict)
    form: dict = field(default_factory=dict)
    files: list[UploadedFile] = field(default_factory=list)
    client_ip: str = ""

    @property
    def query(self) -> dict:
        parsed = parse_qs(self.raw_query, keep_blank_values=True)
        return {key: values[0] for key, values in parsed.items()}

    @property
    def query_all(self) -> dict:
        return parse_qs(self.raw_query, keep_blank_values=True)

    def json(self) -> dict:
        """Telo kao JSON objekat. Validan JSON koji nije objekat je 400, ne 500."""
        if not self.body:
            return {}
        try:
            parsed = json.loads(self.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise HttpError(400, "Telo zahteva nije ispravan JSON.", str(exc)) from exc
        if not isinstance(parsed, dict):
            raise HttpError(400, "Telo zahteva mora da bude JSON objekat.")
        return parsed

    def data(self) -> dict:
        """Objedinjen ulaz: JSON telo ili multipart/urlencoded polja."""
        content_type = self.headers.get("content-type", "")
        if content_type.startswith("application/json"):
            return self.json()
        if self.form:
            return dict(self.form)
        if content_type.startswith("application/x-www-form-urlencoded"):
            parsed = parse_qs(self.body.decode("utf-8", "replace"), keep_blank_values=True)
            return {key: values[0] for key, values in parsed.items()}
        return {}

    def file(self, field_name: str) -> Optional[UploadedFile]:
        for item in self.files:
            if item.field_name == field_name:
                return item
        return None

    def discard_files(self) -> None:
        for item in self.files:
            item.discard()


@dataclass
class Response:
    status: int = 200
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    stream: Optional[Callable[[], Iterable[bytes]]] = None


def json_response(payload: Any, status: int = 200, headers: Optional[dict] = None) -> Response:
    body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    merged = {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store"}
    merged.update(headers or {})
    return Response(status=status, headers=merged, body=body)


def text_response(text: str, status: int = 200, content_type: str = "text/plain") -> Response:
    return Response(
        status=status,
        headers={"Content-Type": f"{content_type}; charset=utf-8"},
        body=text.encode("utf-8"),
    )


def error_response(status: int, message: str, detail: Any = None) -> Response:
    payload = {"ok": False, "error": message}
    if detail is not None:
        payload["detail"] = detail
    return json_response(payload, status=status)


def redirect(location: str, status: int = 302) -> Response:
    return Response(status=status, headers={"Location": location})


def file_response(path: Path, download_name: str = "", inline: bool = False) -> Response:
    if not path.is_file():
        raise HttpError(404, "Fajl ne postoji.")
    guessed = mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    # Media je isti origin kao aplikacija: uploadovan .html ili .svg posluzen
    # inline je skladisteni XSS. Inline dozvoljavamo samo tipovima koje sami
    # prikazujemo (slike, audio, video, pdf), sve ostalo ide kao attachment.
    inline_ok = guessed.startswith(("image/", "audio/", "video/")) or guessed == "application/pdf"
    disposition = "inline" if (inline and inline_ok) else "attachment"
    name = download_name or path.name
    safe_name = name.encode("ascii", "ignore").decode("ascii") or "download"

    size = path.stat().st_size

    def produce() -> Iterable[bytes]:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(64 * 1024)
                if not chunk:
                    return
                yield chunk

    return Response(
        status=200,
        headers={
            "Content-Type": guessed,
            "Content-Length": str(size),
            "Content-Disposition": f'{disposition}; filename="{safe_name}"',
            "X-Content-Type-Options": "nosniff",
        },
        stream=produce,
    )


# --------------------------------------------------------------------------
# multipart/form-data
# --------------------------------------------------------------------------

_CRLF = b"\r\n"
_READ_SIZE = 256 * 1024


def parse_multipart(
    stream: BinaryIO,
    content_type: str,
    content_length: int,
    max_bytes: int,
    temp_dir: Path,
) -> tuple[dict, list[UploadedFile]]:
    boundary = _boundary_from(content_type)
    if not boundary:
        raise HttpError(400, "multipart zahtev nema boundary.")
    if content_length > max_bytes:
        raise HttpError(413, "Zahtev je veci od dozvoljenog.")

    reader = _BoundedReader(stream, content_length)
    delimiter = b"--" + boundary
    fields: dict = {}
    files: list[UploadedFile] = []

    buffer = bytearray()

    def fill(minimum: int) -> bool:
        while len(buffer) < minimum:
            chunk = reader.read(_READ_SIZE)
            if not chunk:
                return False
            buffer.extend(chunk)
        return True

    # Preambula do prvog delimitera.
    while True:
        index = buffer.find(delimiter)
        if index >= 0:
            del buffer[: index + len(delimiter)]
            break
        if not fill(len(buffer) + 1):
            raise HttpError(400, "multipart telo je nepotpuno.")

    try:
        while True:
            if not fill(2):
                break
            marker = bytes(buffer[:2])
            if marker == b"--":
                break
            if marker != _CRLF:
                raise HttpError(400, "Neispravan multipart delimiter.")
            del buffer[:2]

            headers = _read_part_headers(buffer, fill)
            disposition = headers.get("content-disposition", "")
            name = _disposition_value(disposition, "name")
            filename = _disposition_value(disposition, "filename")
            if not name:
                raise HttpError(400, "multipart deo nema ime polja.")

            terminator = _CRLF + delimiter
            if filename:
                handle_path = temp_dir / f"upload-{uuid.uuid4().hex}.part"
                temp_dir.mkdir(parents=True, exist_ok=True)
                written = 0
                with handle_path.open("wb") as out:
                    for piece in _read_until(buffer, fill, terminator):
                        out.write(piece)
                        written += len(piece)
                files.append(
                    UploadedFile(
                        field_name=name,
                        filename=os.path.basename(filename.replace("\\", "/")),
                        content_type=headers.get("content-type", ""),
                        temp_path=handle_path,
                        size=written,
                    )
                )
            else:
                collected = bytearray()
                for piece in _read_until(buffer, fill, terminator):
                    collected.extend(piece)
                fields[name] = collected.decode("utf-8", "replace")

            del buffer[: len(terminator)]
    except Exception:
        for item in files:
            item.discard()
        raise

    return fields, files


def _read_until(buffer: bytearray, fill, terminator: bytes) -> Iterable[bytes]:
    """Vrati sadrzaj do terminatora; terminator ostaje na pocetku buffera."""
    keep = len(terminator)
    while True:
        index = buffer.find(terminator)
        if index >= 0:
            if index:
                yield bytes(buffer[:index])
                del buffer[:index]
            return
        # Terminator moze da bude presecen na granici citanja, pa zadrzi rep.
        if len(buffer) > keep:
            flush_to = len(buffer) - keep
            yield bytes(buffer[:flush_to])
            del buffer[:flush_to]
        if not fill(len(buffer) + 1):
            raise HttpError(400, "multipart deo je nepotpun.")


def _read_part_headers(buffer: bytearray, fill) -> dict:
    separator = _CRLF + _CRLF
    while True:
        index = buffer.find(separator)
        if index >= 0:
            raw = bytes(buffer[:index]).decode("utf-8", "replace")
            del buffer[: index + len(separator)]
            break
        if len(buffer) > 16 * 1024:
            raise HttpError(400, "Zaglavlja multipart dela su prevelika.")
        if not fill(len(buffer) + 1):
            raise HttpError(400, "multipart deo nema zaglavlja.")

    headers = {}
    for line in raw.split("\r\n"):
        if ":" in line:
            key, _, value = line.partition(":")
            headers[key.strip().lower()] = value.strip()
    return headers


def _boundary_from(content_type: str) -> bytes:
    for piece in content_type.split(";"):
        piece = piece.strip()
        if piece.lower().startswith("boundary="):
            value = piece[len("boundary=") :].strip().strip('"')
            return value.encode("utf-8")
    return b""


def _disposition_value(disposition: str, key: str) -> str:
    for piece in disposition.split(";"):
        piece = piece.strip()
        if not piece.lower().startswith(key.lower() + "="):
            continue
        value = piece[len(key) + 1 :].strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        return unquote(value)
    return ""


class _BoundedReader:
    """Cita najvise `limit` bajtova iz socket streama."""

    def __init__(self, stream: BinaryIO, limit: int):
        self._stream = stream
        self._remaining = limit

    def read(self, size: int) -> bytes:
        if self._remaining <= 0:
            return b""
        chunk = self._stream.read(min(size, self._remaining))
        self._remaining -= len(chunk)
        return chunk


def temp_directory() -> Path:
    path = Path(tempfile.gettempdir()) / "skripta-faks-uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path
