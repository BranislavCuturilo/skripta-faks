"""Deljenje izvucenog teksta na komade koji staju u jedan AI poziv.

Cilj je dogovoreni odnos: sto vise sadrzaja po pozivu, sto manje poziva. Zato je
komad velik (desetine hiljada znakova) i sece se na granici pasusa ili naslova,
nikad usred recenice - model koji dobije pola definicije napravi pola pitanja.
"""

import re

# Naslovi po kojima se prepoznaje "Lekcija 5" da bi korisnik mogao da kaze
# "uci se do lekcije 5" i da to nesto znaci.
_HEADING = re.compile(
    r"^\s*(?:"
    r"(?:lekcija|lekcije|poglavlje|glava|oblast|tema|predavanje|nedelja|deo|odeljak|"
    r"chapter|lecture|unit|section)\s*[:\-]?\s*\d+[.\)]?"
    r"|\d+(?:\.\d+)*\.?\s+[A-ZČĆŠŽĐ][^\n]{3,80}"
    r"|\[strana\s+\d+\]"
    r"|###\s+.+"
    r")\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def split(text: str, budget: int = 60000, overlap: int = 600) -> list[dict]:
    """Vrati listu komada: {ordinal, label, text, char_count}."""
    text = (text or "").strip()
    if not text:
        return []

    blocks = _blocks(text)
    chunks: list[dict] = []
    buffer: list[str] = []
    size = 0
    label = ""

    def flush() -> None:
        nonlocal buffer, size
        if not buffer:
            return
        body = "\n\n".join(buffer).strip()
        if body:
            chunks.append(
                {
                    "ordinal": len(chunks) + 1,
                    "label": label,
                    "text": body,
                    "char_count": len(body),
                }
            )
        buffer = []
        size = 0

    for block in blocks:
        if block["heading"] and size > budget * 0.55:
            flush()
        if block["heading"]:
            label = block["text"].strip()[:120]

        piece = block["text"]
        if len(piece) > budget:
            flush()
            for part in _hard_split(piece, budget, overlap):
                chunks.append(
                    {
                        "ordinal": len(chunks) + 1,
                        "label": label,
                        "text": part,
                        "char_count": len(part),
                    }
                )
            continue

        if size + len(piece) > budget:
            tail = "\n\n".join(buffer)[-overlap:] if overlap else ""
            flush()
            if tail.strip():
                buffer.append(tail.strip())
                size = len(tail)

        buffer.append(piece)
        size += len(piece) + 2

    flush()
    return chunks


def _blocks(text: str) -> list[dict]:
    result: list[dict] = []
    for raw in re.split(r"\n\s*\n", text):
        piece = raw.strip()
        if not piece:
            continue
        result.append({"text": piece, "heading": bool(_HEADING.match(piece.split("\n")[0]))})
    return result


def _hard_split(text: str, budget: int, overlap: int) -> list[str]:
    """Pasus veci od budzeta - seci po recenici, pa tek onda na silu."""
    sentences = re.split(r"(?<=[.!?…])\s+", text)
    parts: list[str] = []
    buffer = ""
    for sentence in sentences:
        if len(sentence) > budget:
            if buffer:
                parts.append(buffer)
                buffer = ""
            for index in range(0, len(sentence), budget):
                parts.append(sentence[index : index + budget])
            continue
        if len(buffer) + len(sentence) + 1 > budget:
            parts.append(buffer)
            buffer = buffer[-overlap:] if overlap else ""
        buffer = f"{buffer} {sentence}".strip()
    if buffer:
        parts.append(buffer)
    return [part.strip() for part in parts if part.strip()]


def outline(text: str, limit: int = 60) -> list[str]:
    """Naslovi u materijalu - da korisnik vidi sta uopste ima kad pise prompt."""
    found = [match.group(0).strip() for match in _HEADING.finditer(text or "")]
    seen: set[str] = set()
    result: list[str] = []
    for item in found:
        if item.lower().startswith("[strana"):
            continue
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
        if len(result) >= limit:
            break
    return result
