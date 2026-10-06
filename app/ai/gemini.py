"""Gemini klijent na urllib.

Kljuc ide u zaglavlje `x-goog-api-key`, nikad u URL - URL zavrsava u porukama o
greskama i u logovima, a kljuc tamo nema sta da trazi. Iz istog razloga se u
`ai_call_log` upisuju samo model, trajanje i status, nikad telo ni kljuc.
"""

import base64
import json
import mimetypes
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

from .. import db
from . import models

# Poslednja linija odbrane, nezavisna od konfiguracije: kad je postavljeno,
# nijedan poziv ne izlazi iz procesa. Testovi ga pale u run_tests.py, pa suite
# ne moze da potrosi kvotu ni da posalje ijedan bajt gradiva na internet.
NETWORK_BLOCKED_ENV = "SKRIPTA_BLOCK_NETWORK"

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
UPLOAD_URL = "https://generativelanguage.googleapis.com/upload/v1beta/files"

# Iznad ovoga fajl ide kroz Files API umesto inline u telo zahteva.
INLINE_LIMIT_BYTES = 4 * 1024 * 1024

RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 4
DEFAULT_TIMEOUT_S = 300.0


class AiError(Exception):
    def __init__(self, message: str, status: Optional[int] = None, retryable: bool = False):
        super().__init__(message)
        self.message = message
        self.status = status
        self.retryable = retryable


def generate(
    api_key: str,
    model: str,
    prompt: str,
    *,
    system: str = "",
    files: Optional[list[dict]] = None,
    json_output: bool = True,
    temperature: float = 0.7,
    max_output_tokens: int = 32768,
    purpose: str = "generate",
    thinking: str = "",
    timeout_s: float = DEFAULT_TIMEOUT_S,
    max_attempts: int = MAX_ATTEMPTS,
) -> dict:
    """Jedan poziv modelu. Vraca {text, prompt_tokens, output_tokens, model}.

    Podrazumevano je strpljivo (dug timeout, vise pokusaja) - za poslove u
    pozadini. Ono sto student ceka pred ekranom zadaje `timeout_s`,
    `max_attempts` i `thinking="low"`.
    """
    if not api_key:
        raise AiError("Nije unet Gemini API kljuc (Podesavanja -> AI).")

    parts: list[dict] = [{"text": prompt}]
    for item in files or []:
        parts.append(_file_part(item))

    body: dict[str, Any] = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_output_tokens,
        },
    }
    if json_output:
        body["generationConfig"]["responseMimeType"] = "application/json"
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    thinking_config = models.thinking_config(model, thinking)
    if thinking_config:
        body["generationConfig"]["thinkingConfig"] = thinking_config

    url = f"{BASE_URL}/models/{model}:generateContent"
    started = time.monotonic()
    error_text = ""
    status_code = None
    try:
        try:
            payload = _post_json(url, api_key, body, timeout_s, max_attempts)
        except AiError as exc:
            # Model koji ne zna za to polje vraca 400 - sporiji odgovor je
            # bolji od nikakvog, pa jos jednom bez njega.
            if not (thinking_config and exc.status == 400 and "thinking" in exc.message.lower()):
                raise
            del body["generationConfig"]["thinkingConfig"]
            payload = _post_json(url, api_key, body, timeout_s, max_attempts)
        text = _first_text(payload)
        usage = payload.get("usageMetadata") or {}
        result = {
            "text": text,
            "model": model,
            "prompt_tokens": usage.get("promptTokenCount"),
            "output_tokens": usage.get("candidatesTokenCount"),
            "finish_reason": _finish_reason(payload),
        }
        return result
    except AiError as exc:
        error_text = exc.message
        status_code = exc.status
        raise
    finally:
        _log_call(
            purpose=purpose,
            model=model,
            ok=not error_text,
            status=status_code,
            duration_ms=int((time.monotonic() - started) * 1000),
            prompt_chars=len(prompt),
            error=error_text,
        )


def call_model(api_key: str, model: str, body: dict) -> dict:
    """Sirov poziv modelu - za rezime koji ne vracaju tekst (npr. TTS)."""
    if not api_key:
        raise AiError("Nije unet Gemini API kljuc (Podesavanja -> AI).")
    return _post_json(f"{BASE_URL}/models/{model}:generateContent", api_key, body)


def probe(api_key: str) -> dict:
    """Najjeftinija provera kljuca: spisak modela."""
    try:
        payload = _request("GET", f"{BASE_URL}/models?pageSize=100", api_key)
    except AiError as exc:
        return {"ok": False, "error": exc.message, "status": exc.status}

    models = []
    for item in payload.get("models") or []:
        name = (item.get("name") or "").replace("models/", "")
        methods = item.get("supportedGenerationMethods") or []
        if "generateContent" in methods and name:
            models.append(
                {
                    "name": name,
                    "label": item.get("displayName") or name,
                    "input_limit": item.get("inputTokenLimit"),
                    "output_limit": item.get("outputTokenLimit"),
                }
            )
    models.sort(key=lambda item: item["name"])
    return {"ok": True, "models": models, "count": len(models)}


def upload_file(api_key: str, path: Path, display_name: str = "") -> dict:
    """Files API, resumable protokol. Fajl na Google-u zivi 48h."""
    if not path.is_file():
        raise AiError(f"Fajl ne postoji: {path.name}")
    size = path.stat().st_size
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    start = urllib.request.Request(
        UPLOAD_URL,
        method="POST",
        data=json.dumps({"file": {"display_name": display_name or path.name}}).encode("utf-8"),
        headers={
            "x-goog-api-key": api_key,
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(size),
            "X-Goog-Upload-Header-Content-Type": mime,
            "Content-Type": "application/json",
        },
    )
    with _open(start) as response:
        session_url = response.headers.get("X-Goog-Upload-URL")
    if not session_url:
        raise AiError("Files API nije vratio adresu za upload.")

    finish = urllib.request.Request(
        session_url,
        method="POST",
        data=path.read_bytes(),
        headers={
            "Content-Length": str(size),
            "X-Goog-Upload-Offset": "0",
            "X-Goog-Upload-Command": "upload, finalize",
        },
    )
    with _open(finish) as response:
        payload = json.loads(response.read().decode("utf-8"))

    info = payload.get("file") or {}
    if not info.get("uri"):
        raise AiError("Files API nije vratio URI fajla.")
    return {
        "uri": info["uri"],
        "name": info.get("name", ""),
        "mime_type": info.get("mimeType", mime),
        "expires_at": info.get("expirationTime", ""),
        "state": info.get("state", ""),
    }


def wait_until_active(api_key: str, file_name: str, timeout_s: float = 90.0) -> bool:
    """Video i audio Google obradjuje pre nego sto smeju da se koriste."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        payload = _request("GET", f"{BASE_URL}/{file_name}", api_key)
        state = payload.get("state", "")
        if state == "ACTIVE":
            return True
        if state == "FAILED":
            return False
        time.sleep(2.0)
    return False


def _file_part(item: dict) -> dict:
    """Mali fajl ide inline (jedan poziv manje), veliki preko Files API-ja."""
    if item.get("uri"):
        return {"file_data": {"mime_type": item.get("mime_type", ""), "file_uri": item["uri"]}}

    path = Path(item["path"])
    mime = item.get("mime_type") or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return {
        "inline_data": {
            "mime_type": mime,
            "data": base64.b64encode(path.read_bytes()).decode("ascii"),
        }
    }


def _post_json(
    url: str, api_key: str, body: dict,
    timeout_s: float = DEFAULT_TIMEOUT_S, max_attempts: int = MAX_ATTEMPTS,
) -> dict:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    return _request("POST", url, api_key, data, timeout_s, max_attempts)


def _request(
    method: str, url: str, api_key: str, data: Optional[bytes] = None,
    timeout_s: float = DEFAULT_TIMEOUT_S, max_attempts: int = MAX_ATTEMPTS,
) -> dict:
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json; charset=utf-8"}
    request = urllib.request.Request(url, method=method, data=data, headers=headers)

    delay = 1.5
    last: Optional[AiError] = None
    for attempt in range(max_attempts):
        try:
            with _open(request, timeout_s) as response:
                return json.loads(response.read().decode("utf-8"))
        except AiError as exc:
            last = exc
            if not exc.retryable or attempt == max_attempts - 1:
                raise
            time.sleep(delay)
            delay *= 2
    raise last or AiError("Poziv nije uspeo.")


def _open(request: urllib.request.Request, timeout_s: float = DEFAULT_TIMEOUT_S):
    if os.environ.get(NETWORK_BLOCKED_ENV):
        raise AiError("Mrezni pozivi su blokirani (SKRIPTA_BLOCK_NETWORK).", status=0)
    try:
        return urllib.request.urlopen(request, timeout=timeout_s)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            payload = json.loads(exc.read().decode("utf-8"))
            detail = (payload.get("error") or {}).get("message", "")
        except Exception:  # noqa: BLE001 - telo greske sme da bude bilo sta
            detail = ""
        raise AiError(
            _friendly(exc.code, detail),
            status=exc.code,
            retryable=exc.code in RETRY_STATUSES,
        ) from None
    except urllib.error.URLError as exc:
        raise AiError(f"Nema veze sa internetom ili je Google nedostupan ({exc.reason}).",
                      retryable=True) from None
    except TimeoutError:
        raise AiError("Poziv je istekao (timeout).", retryable=True) from None


def _friendly(status: int, detail: str) -> str:
    """Poruka iz koje se vidi STA da se uradi, ne samo da nesto ne valja.

    401 i 403 su ovde najvazniji: Google gasi stari tip kljuca ("standard") i
    prelazi na "auth" kljuceve. Neogranicen standard kljuc se vec odbija, a od
    septembra 2026 odbijaju se svi. Bez ove napomene korisnik vidi samo
    "kljuc nije prihvacen" i misli da ga je pogresno prekopirao.
    """
    messages = {
        400: ("Zahtev nije prihvaćen. Najčešće znači da je materijal prevelik za jedan poziv "
              "— smanji broj znakova gradiva po pozivu u Podešavanjima."),
        401: ("API ključ nije prihvaćen. Ako je stariji, verovatno je standard ključ — Google "
              "ih gasi i svi prestaju da rade tokom septembra 2026. Napravi novi na "
              "aistudio.google.com/api-keys; novi su automatski auth ključevi i rade dalje."),
        403: ("Ključ nema pravo pristupa. Ili je standard ključ koji se više ne prihvata "
              "(napravi novi na aistudio.google.com/api-keys), ili taj model nije dostupan "
              "tvom nalogu."),
        404: ("Traženi model ne postoji za ovaj ključ — verovatno je penzionisan. "
              "Otvori Podešavanja i pritisni Osveži spisak modela."),
        429: ("Prešao si besplatnu kvotu za sada. Sačekaj minut-dva pa probaj ponovo, "
              "ili spusti model na brži i jeftiniji."),
        500: "Greška na Google-ovoj strani. Probaj ponovo za koji minut.",
        503: "Model je trenutno preopterećen. Probaj ponovo za koji minut.",
    }
    base = messages.get(status, f"Poziv nije uspeo (HTTP {status}).")
    return f"{base} {detail}".strip() if detail else base


def _first_text(payload: dict) -> str:
    candidates = payload.get("candidates") or []
    if not candidates:
        feedback = payload.get("promptFeedback") or {}
        blocked = feedback.get("blockReason")
        if blocked:
            raise AiError(f"Model je odbio da odgovori ({blocked}).")
        raise AiError("Model nije vratio nijedan odgovor.")
    parts = ((candidates[0].get("content") or {}).get("parts")) or []
    return "".join(part.get("text", "") for part in parts).strip()


def _finish_reason(payload: dict) -> str:
    candidates = payload.get("candidates") or []
    return candidates[0].get("finishReason", "") if candidates else ""


def _log_call(
    purpose: str,
    model: str,
    ok: bool,
    status: Optional[int],
    duration_ms: int,
    prompt_chars: int,
    error: str,
) -> None:
    try:
        db.insert(
            "ai_call_log",
            {
                "purpose": purpose,
                "provider": "gemini",
                "model": model,
                "ok": 1 if ok else 0,
                "http_status": status,
                "duration_ms": duration_ms,
                "prompt_chars": prompt_chars,
                "error": error[:500],
            },
        )
    except Exception:  # noqa: BLE001 - log nikad ne sme da obori poziv
        pass
