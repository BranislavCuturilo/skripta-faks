"""Prepoznavanje istog pitanja.

`content_hash` hvata samo bajt-isto pitanje: dovoljno je da model promeni jedan
pogresan ponudjeni odgovor, doda zarez ili napise "Koji organ proizvodi
insulin?" umesto "Koji organ proizvodi hormon insulin?" - i isto pitanje
ulazi drugi put. Ovde je pravilo ono koje student oseti:

    isto pitanje = ISTI NACIN ODGOVARANJA (tip)
                 + ISTI TACAN ODGOVOR
                 + skoro ISTI TEKST (`STEM_SIMILARITY`, i iste brojke)

Isto gradivo pitano drugim tipom (jednom zaokruzi, drugi put dopuni) nije
duplikat - to je druga provera znanja. Pogresni ponudjeni odgovori ne ulaze u
poredjenje: ako je pitanje i tacan odgovor isti, studentu je to isto pitanje.

Prag je namerno visok. Promasen duplikat je smetnja; obrisano pitanje koje je
zapravo bilo drugacije je gubitak.

Nov tip pitanja dobija unos u `_ANSWER_KEYS`. Bez njega se nikad ne proglasava
duplikatom - bezbedno, ali bez zastite (pinovano testom koji gleda registar).
"""

import re
from difflib import SequenceMatcher
from typing import Any, Iterable, Optional

from . import grading

STEM_SIMILARITY = 0.85

_BLANK = re.compile(r"\{\{\s*\d+\s*\}\}")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def answer_key(question_type: str, payload: dict) -> Optional[tuple]:
    """Tacan odgovor kao vrednost koja se poredi. None = ne poredi se nikad."""
    try:
        return _ANSWER_KEYS[question_type](payload)
    except (KeyError, IndexError, TypeError, ValueError):
        # Tip bez kljuca ili stari red sa polomljenim payload-om: bolje ga
        # nikad ne proglasiti duplikatom nego pogresno.
        return None


def stem_text(stem: str) -> str:
    return grading.normalize(_BLANK.sub(" ___ ", stem or ""))


class Index:
    """Pitanja po (tip, tacan odgovor), da se tekst poredi samo unutar grupe.

    Bez grupisanja bi provera uz svako generisanje bila svako-sa-svakim preko
    celog predmeta.
    """

    def __init__(self, questions: Iterable[dict] = ()):
        self._groups: dict[tuple, list[tuple[str, tuple, Any]]] = {}
        for question in questions:
            self.add(question)

    def add(self, question: dict) -> None:
        key = _group_key(question)
        if key is None:
            return
        text = stem_text(question.get("stem", ""))
        self._groups.setdefault(key, []).append((text, _numbers(text), question))

    def match(self, question: dict) -> Optional[dict]:
        """Prvo vec poznato pitanje koje je isto kao ovo, ili None."""
        key = _group_key(question)
        if key is None:
            return None
        text = stem_text(question.get("stem", ""))
        if not text:
            return None
        numbers = _numbers(text)
        for other_text, other_numbers, other in self._groups.get(key, []):
            if numbers == other_numbers and _similar(text, other_text):
                return other
        return None


def _group_key(question: dict) -> Optional[tuple]:
    question_type = str(question.get("type") or "")
    answer = answer_key(question_type, question.get("payload") or {})
    return None if answer is None else (question_type, answer)


def _numbers(text: str) -> tuple:
    # "Izracunaj 2+2" i "Izracunaj 1+3" imaju isti odgovor i skoro isti tekst,
    # a nisu isti zadatak. Brojevi u tekstu moraju da se poklope.
    return tuple(_NUMBER.findall(text))


def _similar(first: str, second: str) -> bool:
    if first == second:
        return True
    matcher = SequenceMatcher(None, first, second, autojunk=False)
    # Gornje granice su jeftine; puno poredjenje samo kad one ne iskljuce par.
    return (
        matcher.real_quick_ratio() >= STEM_SIMILARITY
        and matcher.quick_ratio() >= STEM_SIMILARITY
        and matcher.ratio() >= STEM_SIMILARITY
    )


def _norm(value: Any) -> str:
    return grading.normalize(str(value))


def _image_ref(payload: dict) -> tuple:
    image = payload.get("image") or {}
    return (image.get("material_id"), image.get("path"))


def _option(payload: dict, index_key: str = "correct_index") -> str:
    return _norm(payload["options"][int(payload[index_key])])


_ANSWER_KEYS = {
    "mcq_single": lambda p: ("option", _option(p)),
    "odd_one_out": lambda p: ("option", _option(p)),
    "image_match": lambda p: ("option", _image_ref(p), _option(p)),
    "mcq_multi": lambda p: (
        "options", frozenset(_norm(p["options"][int(i)]) for i in p["correct_indices"])),
    "true_false": lambda p: ("bool", bool(p["correct"])),
    # Prvi prihvatljiv oblik je "pravi" odgovor; ostali su padezi i sinonimi
    # koje model ne navodi uvek isto.
    "fill_blank": lambda p: ("blanks", tuple(_norm(b["accepted"][0]) for b in p["blanks"])),
    "cloze_dropdown": lambda p: (
        "blanks", tuple(_norm(b["options"][int(b["correct_index"])]) for b in p["blanks"])),
    "short_answer": lambda p: (
        ("text", _norm(p["accepted"][0])) if p.get("accepted")
        else ("points", frozenset(_norm(k) for k in p["key_points"]))),
    "long_answer": lambda p: ("points", frozenset(_norm(k) for k in p["key_points"])),
    "numeric": lambda p: ("number", float(p["value"]), _norm(p.get("unit") or "")),
    "match_pairs": lambda p: ("pairs", frozenset(
        (_norm(p["left"][i]), _norm(p["right"][int(target)])) for i, target in enumerate(p["mapping"]))),
    "order_sequence": lambda p: ("order", tuple(_norm(p["items"][int(i)]) for i in p["correct_order"])),
    "image_label": lambda p: (
        "labels", _image_ref(p), frozenset(_norm(t["label"]) for t in p["targets"])),
    "work_it_out": lambda p: ("result", _norm(p.get("final_answer") or ""), _norm(p.get("unit") or "")),
    "flashcard": lambda p: ("back", _norm(p["back"])),
}
