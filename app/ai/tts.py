"""Izgovor teksta.

Tri puta, sva tri bez ijedne biblioteke:

1. browser (Web Speech API) - podrazumevan, radi i na telefonu, ne trosi kvotu;
   ceo posao je u frontendu i ovaj modul ga ne dodiruje
2. Windows govor - `System.Speech` kroz PowerShell, cuje se na zvucniku racunara
   na kom server radi
3. Gemini TTS - prirodniji glas, ali trosi kvotu i trazi internet

Gemini vraca sirov PCM (L16, 24 kHz, mono). Browser to ne ume da pusti, pa mu
ovde dodajemo WAV zaglavlje - `wave` je u standardnoj biblioteci.
"""

import base64
import io
import json
import re
import subprocess
import wave

from . import gemini

DEFAULT_VOICE = "Kore"
DEFAULT_MODEL = "gemini-2.5-flash-preview-tts"

_SAMPLE_RATE = 24000
_MAX_CHARS = 4000


def synthesize(api_key: str, text: str, voice: str = "", model: str = "") -> bytes:
    """Vrati WAV bajtove koje browser moze direktno da pusti."""
    text = (text or "").strip()[:_MAX_CHARS]
    if not text:
        raise gemini.AiError("Nema teksta za izgovor.")

    body = {
        "contents": [{"role": "user", "parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {"voiceName": voice or DEFAULT_VOICE}
                }
            },
        },
    }
    payload = gemini.call_model(api_key, model or DEFAULT_MODEL, body)

    inline = _first_audio(payload)
    raw = base64.b64decode(inline["data"])
    return _to_wav(raw, _rate_from(inline.get("mimeType", "")))


def _first_audio(payload: dict) -> dict:
    for candidate in payload.get("candidates") or []:
        for part in ((candidate.get("content") or {}).get("parts")) or []:
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                return inline
    raise gemini.AiError("Model nije vratio zvuk. Proveri da li kljuc ima pristup TTS modelu.")


def _rate_from(mime: str) -> int:
    found = re.search(r"rate=(\d+)", mime or "")
    return int(found.group(1)) if found else _SAMPLE_RATE


def _to_wav(pcm: bytes, sample_rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm)
    return buffer.getvalue()


def speak_on_host(text: str, rate: int = 0) -> None:
    """Izgovor na zvucniku racunara na kom server radi (Windows).

    Tekst ide kroz stdin, ne kroz komandnu liniju - inace bi navodnik ili
    apostrof u pitanju bio ubacivanje komande.
    """
    script = (
        "$ErrorActionPreference='Stop';"
        "Add-Type -AssemblyName System.Speech;"
        "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        f"$s.Rate={max(-10, min(10, int(rate)))};"
        "$t=[Console]::In.ReadToEnd();"
        "$s.Speak($t);"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            input=text.encode("utf-8"),
            capture_output=True,
            timeout=120,
            check=True,
        )
    except FileNotFoundError:
        raise gemini.AiError("PowerShell nije dostupan - izgovor na racunaru radi samo na Windows-u.") from None
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or b"").decode("utf-8", "replace")[:300]
        raise gemini.AiError(f"Windows govor nije uspeo: {detail}") from None
    except subprocess.TimeoutExpired:
        raise gemini.AiError("Izgovor je trajao predugo i prekinut je.") from None


def list_voices(api_key: str) -> list[dict]:
    """Ugradjeni Gemini glasovi. Spisak je fiksan na strani modela."""
    names = [
        ("Zephyr", "vedar"), ("Puck", "razigran"), ("Charon", "dubok"),
        ("Kore", "neutralan"), ("Fenrir", "hrapav"), ("Leda", "mlad"),
        ("Orus", "cvrst"), ("Aoede", "prozracan"), ("Callirrhoe", "opusten"),
        ("Autonoe", "svetao"), ("Enceladus", "sapatan"), ("Iapetus", "jasan"),
    ]
    return [{"name": name, "hint": hint} for name, hint in names]
