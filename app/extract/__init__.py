"""Ekstrakcija teksta iz uploadovanih materijala.

Hibrid, po dogovoru: prvo lokalno, bez ijedne biblioteke. Ako lokalno ne da
upotrebljiv tekst - skenirani PDF, slika, snimak - fajl se oznaci za slanje u
Gemini Files API i original ide tamo. Odluka se cuva na materijalu, pa se u UI
vidi kojim je putem svaki fajl obradjen.
"""

from dataclasses import dataclass, field
from pathlib import Path

from .. import config

# Ispod ovoliko znakova po strani PDF se smatra skeniranim, ne tekstualnim.
MIN_CHARS_PER_PAGE = 120
MIN_QUALITY = 0.55


@dataclass
class ExtractionResult:
    status: str          # local_ok | local_poor | remote_needed | failed
    method: str          # plaintext | ooxml | pdf_text | none
    text: str = ""
    page_count: int | None = None
    quality: float = 0.0
    note: str = ""
    pages: list[str] = field(default_factory=list)

    @property
    def char_count(self) -> int:
        return len(self.text)


def kind_for(extension: str) -> str:
    extension = extension.lower()
    if extension in config.PLAIN_TEXT_EXT:
        return "text"
    if extension in config.OOXML_EXT:
        return "document"
    if extension in config.PDF_EXT:
        return "pdf"
    if extension in config.IMAGE_EXT:
        return "image"
    if extension in config.AUDIO_EXT:
        return "audio"
    if extension in config.VIDEO_EXT:
        return "video"
    return "other"


def extract(path: Path) -> ExtractionResult:
    from . import ooxml, pdf, plaintext

    extension = path.suffix.lower()
    kind = kind_for(extension)

    if kind == "text":
        return plaintext.extract(path)
    if kind == "document":
        return ooxml.extract(path)
    if kind == "pdf":
        return pdf.extract(path)
    if kind in ("image", "audio", "video"):
        return ExtractionResult(
            status="remote_needed",
            method="none",
            note=f"{kind}: sadrzaj cita AI direktno iz originala.",
        )
    return ExtractionResult(
        status="remote_needed",
        method="none",
        note=f"Format {extension or '?'} se ne cita lokalno; original ide AI-u.",
    )


def quality_of(text: str, page_count: int | None = None) -> float:
    """Grubа ocena da li je izvuceni tekst tekst, a ne smece iz font tabela.

    Pravi tekst ima razmake, slova i recenice normalne duzine. CID font bez
    ToUnicode mape da niz simbola bez razmaka - to hocemo da uhvatimo.
    """
    if not text:
        return 0.0

    total = len(text)
    letters = sum(1 for char in text if char.isalpha())
    spaces = sum(1 for char in text if char.isspace())
    junk = sum(1 for char in text if char == "�" or (ord(char) < 32 and char not in "\n\r\t"))

    letter_ratio = letters / total
    space_ratio = spaces / total
    junk_ratio = junk / total

    words = [word for word in text.split() if word]
    if not words:
        return 0.0
    average_word = sum(len(word) for word in words) / len(words)
    word_score = 1.0 if 2.0 <= average_word <= 14.0 else 0.3

    score = (
        min(letter_ratio / 0.55, 1.0) * 0.4
        + min(space_ratio / 0.12, 1.0) * 0.3
        + word_score * 0.3
        - junk_ratio * 2.0
    )

    if page_count and page_count > 0 and total / page_count < MIN_CHARS_PER_PAGE:
        score *= 0.4

    return max(0.0, min(1.0, score))
