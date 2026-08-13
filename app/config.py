"""Putanje i podrazumevane vrednosti. Jedino mesto koje zna gde sta stoji."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "skripta.db"
MATERIALS_DIR = DATA_DIR / "materials"
EXTRACTED_DIR = DATA_DIR / "extracted"
ANSWERS_DIR = DATA_DIR / "answers"
EXPORTS_DIR = DATA_DIR / "exports"

WEB_DIR = BASE_DIR / "web"

# Predlozi za nadogradnju aplikacije. Za razliku od data/, ovo JESTE u gitu -
# to je i poenta: predlog se nosi u Claude i zavrsi kao izmena koda.
PROPOSALS_DIR = BASE_DIR / "predlozi"
CONTEXT_FILE = PROPOSALS_DIR / "KONTEKST-ZA-AI.md"


def use_proposals_dir(path) -> None:
    """Premesti folder sa predlozima.

    Odvojeno od `use_data_dir`, jer `predlozi/` nije korisnicki podatak nego deo
    repozitorijuma. Postoji da testovi ne bi pisali u pravi folder projekta.
    """
    global PROPOSALS_DIR, CONTEXT_FILE
    PROPOSALS_DIR = Path(path).resolve()
    CONTEXT_FILE = PROPOSALS_DIR / "KONTEKST-ZA-AI.md"
    PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)


def use_data_dir(path) -> None:
    """Premesti sve podatke u drugi folder.

    Postoji zbog testova: suite nikad ne sme da pise u pravu bazu, a jedina
    zastita koja se ne moze zaboraviti je ta da test odmah na startu pokaze
    negde drugde.
    """
    global DATA_DIR, DB_PATH, MATERIALS_DIR, EXTRACTED_DIR, ANSWERS_DIR, EXPORTS_DIR
    DATA_DIR = Path(path).resolve()
    DB_PATH = DATA_DIR / "skripta.db"
    MATERIALS_DIR = DATA_DIR / "materials"
    EXTRACTED_DIR = DATA_DIR / "extracted"
    ANSWERS_DIR = DATA_DIR / "answers"
    EXPORTS_DIR = DATA_DIR / "exports"
    ensure_dirs()

DEFAULT_PORT = 8077
PORT_SEARCH_RANGE = 20

# Gornja granica na jedan HTTP body. Upload ide u komadima pa 64 MB pokriva
# i najveci pojedinacni fajl koji ocekujemo (snimak predavanja).
MAX_BODY_BYTES = 64 * 1024 * 1024

MAX_UPLOAD_BYTES = 64 * 1024 * 1024

# Prosirenja koja umemo lokalno da procitamo, po ruti ekstrakcije.
PLAIN_TEXT_EXT = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".srt", ".vtt"}
OOXML_EXT = {".docx", ".xlsx", ".pptx"}
PDF_EXT = {".pdf"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".heic"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".avi"}

# Sve sto korisnik sme da uploaduje. Deny-list nema smisla ovde: fajlovi se
# nikad ne serviraju nazad kao HTML, uvek kao attachment ili kroz ekstrakciju.
ALLOWED_UPLOAD_EXT = (
    PLAIN_TEXT_EXT | OOXML_EXT | PDF_EXT | IMAGE_EXT | AUDIO_EXT | VIDEO_EXT
    | {".doc", ".xls", ".ppt", ".rtf", ".odt", ".epub"}
)


def ensure_dirs() -> None:
    for path in (DATA_DIR, MATERIALS_DIR, EXTRACTED_DIR, ANSWERS_DIR, EXPORTS_DIR):
        path.mkdir(parents=True, exist_ok=True)


if os.environ.get("SKRIPTA_DATA_DIR"):
    use_data_dir(os.environ["SKRIPTA_DATA_DIR"])

if os.environ.get("SKRIPTA_PROPOSALS_DIR"):
    use_proposals_dir(os.environ["SKRIPTA_PROPOSALS_DIR"])
