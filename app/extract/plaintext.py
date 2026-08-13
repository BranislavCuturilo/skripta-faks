"""Obicni tekstualni formati. Kodiranje se pogadja, ne pretpostavlja."""

from pathlib import Path

from . import ExtractionResult, quality_of

_ENCODINGS = ("utf-8-sig", "utf-8", "cp1250", "cp1252", "latin-1")

_SUBTITLE_EXT = {".srt", ".vtt"}


def extract(path: Path) -> ExtractionResult:
    raw = path.read_bytes()
    text = ""
    used = ""
    for encoding in _ENCODINGS:
        try:
            text = raw.decode(encoding)
            used = encoding
            break
        except UnicodeDecodeError:
            continue
    if not used:
        text = raw.decode("utf-8", "replace")
        used = "utf-8/replace"

    if path.suffix.lower() in _SUBTITLE_EXT:
        text = _strip_subtitle_timing(text)

    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    return ExtractionResult(
        status="local_ok" if text else "local_poor",
        method="plaintext",
        text=text,
        quality=quality_of(text),
        note=f"kodiranje: {used}",
    )


def _strip_subtitle_timing(text: str) -> str:
    """Iz transkripta predavanja treba recenica, ne tajming."""
    lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.isdigit():
            continue
        if "-->" in stripped:
            continue
        if stripped.upper().startswith(("WEBVTT", "NOTE ", "STYLE")):
            continue
        lines.append(stripped)
    return "\n".join(lines)
