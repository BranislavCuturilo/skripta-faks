"""Ugovor o formatu izmedju aplikacije i bilo kog modela.

Isti oblik vraca i Gemini i rucno zalepljen odgovor iz Claude-a. Zato je
parsiranje odvojeno od klijenta: uvoz iz drugog modela prolazi kroz tacno istu
proveru kao automatski poziv, i nema puta u bazu koji nije proveren.
"""

import hashlib
import json
import re
import unicodedata
from typing import Any

from ..quiz import types as question_types

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


class ContractError(ValueError):
    pass


def strip_fence(raw_text: str) -> str:
    """Ukloni ```json ograde - modeli ih dodaju i kad im se kaze da ne dodaju."""
    return _FENCE.sub("", (raw_text or "").strip())


def parse(raw_text: str) -> dict:
    """Tekst modela -> {questions: [...], notes: str, salvaged: bool}."""
    text = strip_fence(raw_text)
    if not text:
        raise ContractError("Model nije vratio nista.")

    salvaged = False
    try:
        payload = json.loads(text)
    except ValueError:
        payload, salvaged = _salvage(text)

    if isinstance(payload, list):
        payload = {"questions": payload}
    if not isinstance(payload, dict):
        raise ContractError("Odgovor nije JSON objekat ni lista.")

    items = payload.get("questions")
    if items is None:
        items = payload.get("pitanja") or payload.get("items")
    if not isinstance(items, list):
        raise ContractError("U odgovoru nema liste 'questions'.")

    return {
        "questions": items,
        "notes": str(payload.get("notes") or ""),
        "salvaged": salvaged,
    }


def validate_all(items: list) -> tuple[list[dict], list[dict]]:
    """Vrati (ispravna pitanja, odbijena sa razlogom). Jedno lose ne rusi ostala."""
    accepted: list[dict] = []
    rejected: list[dict] = []
    for position, item in enumerate(items, start=1):
        try:
            accepted.append(validate_one(item))
        except (question_types.InvalidQuestion, ContractError, TypeError, ValueError) as exc:
            rejected.append(
                {
                    "position": position,
                    "reason": str(exc),
                    "type": (item or {}).get("type") if isinstance(item, dict) else None,
                    "stem": str((item or {}).get("stem", ""))[:160] if isinstance(item, dict) else "",
                }
            )
    return accepted, rejected


def validate_one(item: Any) -> dict:
    if not isinstance(item, dict):
        raise ContractError("Stavka nije objekat.")

    question_type = str(item.get("type") or "").strip()
    if not question_types.exists(question_type):
        raise ContractError(f"Nepoznat tip pitanja: {question_type or '(prazno)'}")

    stem = str(item.get("stem") or item.get("question") or "").strip()
    if len(stem) < 5:
        raise ContractError("Tekst pitanja je prazan ili prekratak.")

    payload = item.get("payload")
    if not isinstance(payload, dict):
        # Neki modeli razliju polja po korenu umesto u payload.
        payload = {key: value for key, value in item.items() if key not in _TOP_LEVEL}
    normalized = question_types.normalize(question_type, payload)

    if question_type in ("fill_blank", "cloze_dropdown"):
        _check_blank_markers(stem, normalized)

    difficulty = item.get("difficulty", 2)
    try:
        difficulty = max(1, min(3, int(difficulty)))
    except (TypeError, ValueError):
        difficulty = 2

    variant_group = str(item.get("variant_group") or "").strip()
    return {
        "type": question_type,
        "stem": stem,
        "payload": normalized,
        "explanation": str(item.get("explanation") or "").strip(),
        "difficulty": difficulty,
        "topic": str(item.get("topic") or "").strip()[:120],
        "source_ref": str(item.get("source_ref") or "").strip()[:200],
        "variant_group": variant_group,
        "variant_index": _int_or(item.get("variant_index"), 0),
        "content_hash": content_hash(question_type, stem, normalized),
    }


_TOP_LEVEL = {
    "type", "stem", "question", "explanation", "difficulty", "topic",
    "source_ref", "variant_group", "variant_index", "payload",
}


def _check_blank_markers(stem: str, payload: dict) -> None:
    markers = set(re.findall(r"\{\{\s*(\d+)\s*\}\}", stem))
    if not markers:
        raise ContractError("Pitanje sa prazninama nema nijednu oznaku {{1}} u tekstu.")
    expected = {str(blank["id"]) for blank in payload["blanks"]}
    if not markers & expected:
        raise ContractError("Oznake praznina u tekstu ne odgovaraju definisanim prazninama.")


def content_hash(question_type: str, stem: str, payload: dict) -> str:
    """Otisak po kome se prepoznaje da je isto pitanje vec generisano.

    Namerno ignorise redosled ponudjenih odgovora - isto pitanje sa izmesanim
    opcijama nije novo pitanje, a model ga vraca stalno.
    """
    normalized_stem = _normalize_text(stem)
    signature: list[str] = [question_type, normalized_stem]

    for key in ("options", "items", "left", "right", "accepted", "key_points"):
        values = payload.get(key)
        if isinstance(values, list):
            signature.append(key + ":" + "|".join(sorted(_normalize_text(str(v)) for v in values)))

    for key in ("value", "correct", "back", "final_answer"):
        if key in payload:
            signature.append(f"{key}:{_normalize_text(str(payload[key]))}")

    return hashlib.sha256("".join(signature).encode("utf-8")).hexdigest()


def _normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.lower())
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _salvage(text: str) -> tuple[dict, bool]:
    """Odsecen odgovor (MAX_TOKENS) - spasi sve cele objekte iz niza.

    Bolje 18 upotrebljivih pitanja nego nijedno zato sto je 19. preseceno.
    """
    start = text.find("[")
    if start < 0:
        raise ContractError("Odgovor nije JSON i nema niz koji bi se spasao.")

    objects: list[Any] = []
    depth = 0
    in_string = False
    escaped = False
    begin = -1

    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                begin = index
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0 and begin >= 0:
                try:
                    objects.append(json.loads(text[begin : index + 1]))
                except ValueError:
                    pass
                begin = -1

    if not objects:
        raise ContractError("Odgovor je neispravan JSON i nista se nije dalo spasti.")
    return {"questions": objects}, True


def _int_or(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback
