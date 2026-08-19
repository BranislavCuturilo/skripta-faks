"""Srpska latinica <-> cirilica.

Model dobije "pisi latinicom" i vrati pola pitanja latinicom, pola cirilicom -
narocito kad je gradivo cirilicno. Uputstvo u promptu pomaze, ali ne garantuje
nista; garantuje tek ovo: svaki tekst koji ulazi u bazu prodje kroz
`enforce(text, script)` i izadje u jednom pismu.

Cirilica -> latinica je bezbedna u oba smera znacenja: svako cirilicno slovo
u latinicnom tekstu je greska, i preslikavanje je 1:1. Latinica -> cirilica
NIJE: "H2O", "kg", "x", "Windows" smeju da ostanu latinicom i u cirilicnom
tekstu. Zato `to_cyrillic` radi po recima i preskace ono sto lici na formulu,
jedinicu, skracenicu ili stranu rec.
"""

import re
from typing import Any, Optional

# Kljuc u podesavanjima ("question_language") -> pismo koje se namece.
SCRIPT_FOR_LANGUAGE = {"sr": "latin", "sr-cyrl": "cyrillic"}

_CYR_TO_LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "ђ": "đ", "е": "e", "ж": "ž",
    "з": "z", "и": "i", "ј": "j", "к": "k", "л": "l", "љ": "lj", "м": "m", "н": "n",
    "њ": "nj", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "ћ": "ć", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "č", "џ": "dž", "ш": "š",
    # Ruska/makedonska slova koja model ume da ubaci u srpski tekst.
    "й": "j", "ы": "i", "э": "e", "ю": "ju", "я": "ja", "ё": "jo", "щ": "šč", "ъ": "", "ь": "",
    "ѓ": "đ", "ќ": "ć", "ѕ": "dz", "ў": "u", "є": "je", "і": "i", "ї": "ji", "ґ": "g",
}
for _lower, _latin in list(_CYR_TO_LAT.items()):
    _CYR_TO_LAT[_lower.upper()] = _latin.capitalize() if len(_latin) > 1 else _latin.upper()

# Digrafi moraju pre pojedinacnih slova.
_LAT_DIGRAPHS = (("dž", "џ"), ("lj", "љ"), ("nj", "њ"), ("Dž", "Џ"), ("DŽ", "Џ"),
                 ("Lj", "Љ"), ("LJ", "Љ"), ("Nj", "Њ"), ("NJ", "Њ"))
_LAT_TO_CYR = {
    "a": "а", "b": "б", "c": "ц", "č": "ч", "ć": "ћ", "d": "д", "đ": "ђ", "e": "е",
    "f": "ф", "g": "г", "h": "х", "i": "и", "j": "ј", "k": "к", "l": "л", "m": "м",
    "n": "н", "o": "о", "p": "п", "r": "р", "s": "с", "š": "ш", "t": "т", "u": "у",
    "v": "в", "z": "з", "ž": "ж",
}
for _lower, _cyr in list(_LAT_TO_CYR.items()):
    _LAT_TO_CYR[_lower.upper()] = _cyr.upper()

_CYRILLIC_RE = re.compile(r"[Ѐ-ӿ]")
_LATIN_SR_RE = re.compile(r"[A-Za-zČĆŽŠĐčćžšđ]")
# Rec koja se sme preslikati u cirilicu: samo slova srpske latinice, sa
# eventualnim apostrofom/crticom unutra. Sve drugo (brojevi, x/y/w/q, mesano
# sa simbolima) ostaje kako jeste.
_WORD_RE = re.compile(r"[A-Za-zČĆŽŠĐčćžšđ]+(?:['’\-][A-Za-zČĆŽŠĐčćžšđ]+)*")
_FOREIGN_LETTERS = set("wWqQxXyY")


def has_cyrillic(text: str) -> bool:
    return bool(_CYRILLIC_RE.search(text or ""))


def has_latin(text: str) -> bool:
    return bool(_LATIN_SR_RE.search(text or ""))


def is_mixed(text: str) -> bool:
    return has_cyrillic(text) and has_latin(text)


def to_latin(text: str) -> str:
    """Svako cirilicno slovo u latinicu. Bezbedno i 1:1."""
    if not text or not has_cyrillic(text):
        return text or ""
    out: list[str] = []
    for index, char in enumerate(text):
        latin = _CYR_TO_LAT.get(char, char)
        # "ЉУБАВ" je "LJUBAV", a "Љубав" je "Ljubav": dvoslovni digraf prati
        # velicinu susednog slova.
        if len(latin) > 1 and char.isupper():
            following = text[index + 1] if index + 1 < len(text) else ""
            preceding = text[index - 1] if index else ""
            neighbour = following if following.isalpha() else preceding
            if neighbour.isupper():
                latin = latin.upper()
        out.append(latin)
    return "".join(out)


def to_cyrillic(text: str) -> str:
    """Latinicne reci u cirilicu, uz izuzetke za formule, jedinice i strane reci."""
    if not text or not has_latin(text):
        return text or ""
    return _WORD_RE.sub(_word_to_cyrillic, text)


def _word_to_cyrillic(match: "re.Match[str]") -> str:
    word = match.group(0)
    if any(char in _FOREIGN_LETTERS for char in word):
        return word
    # Zalepljeno za cifru ("H2O", "x1", "3D") je formula ili oznaka.
    source, start, end = match.string, match.start(), match.end()
    if (start and source[start - 1].isdigit()) or (end < len(source) and source[end].isdigit()):
        return word
    # Kratke skracenice velikim slovima (PDF, SQL, DNK) i jedno slovo (x, A, i)
    # ostaju - to su oznake, ne reci. Izuzetak: srpski veznici i predlozi od
    # jednog slova ("i", "a", "u", "o", "s", "k") su reci.
    if len(word) == 1:
        return _LAT_TO_CYR.get(word, word) if word in "iauoskIAUOSK" else word
    if word.isupper() and len(word) <= 4:
        return word
    for latin, cyrillic in _LAT_DIGRAPHS:
        word = word.replace(latin, cyrillic)
    return "".join(_LAT_TO_CYR.get(char, char) for char in word)


def enforce(text: str, script: Optional[str]) -> str:
    """Tekst u zadatom pismu. `script` je 'latin', 'cyrillic' ili None (ne diraj)."""
    if script == "latin":
        return to_latin(text)
    if script == "cyrillic":
        return to_cyrillic(text)
    return text or ""


def enforce_deep(value: Any, script: Optional[str]) -> Any:
    """Isto, rekurzivno kroz dict/list - za ceo payload pitanja."""
    if not script:
        return value
    if isinstance(value, str):
        return enforce(value, script)
    if isinstance(value, list):
        return [enforce_deep(item, script) for item in value]
    if isinstance(value, dict):
        return {key: enforce_deep(item, script) for key, item in value.items()}
    return value


def script_for_language(language: str) -> Optional[str]:
    return SCRIPT_FOR_LANGUAGE.get((language or "").strip().lower())
