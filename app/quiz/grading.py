"""Ocenjivanje odgovora.

Sve sto se moze proveriti lokalno - proverava se lokalno. AI se zove samo kad
odgovor nije doslovan (kratak odgovor, esej, foto zadatak) ili kad treba
objasnjenje kakvo nije unapred napisano. To je razlika izmedju "svaki odgovor
kosta poziv" i "kosta samo ono sto stvarno mora".
"""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Callable

from .. import translit
from . import types as question_types


@dataclass
class Grade:
    is_correct: bool
    score: float
    needs_ai: bool = False
    feedback: str = ""
    correct_text: str = ""
    detail: dict = field(default_factory=dict)


_GRADERS: dict[str, Callable[[dict, dict], Grade]] = {}


def grader(key: str):
    def decorator(function: Callable[[dict, dict], Grade]) -> Callable[[dict, dict], Grade]:
        _GRADERS[key] = function
        return function

    return decorator


def grade(question: dict, payload: dict, answer: dict) -> Grade:
    function = _GRADERS.get(question["type"])
    if function is None:
        return Grade(is_correct=False, score=0.0, needs_ai=True)
    return function(payload, answer or {})


def normalize(value: str) -> str:
    """Poredjenje teksta koje prezivi pismo, padez, dijakritiku i interpunkciju."""
    value = translit.to_latin((value or "").strip()).lower()
    value = value.replace("đ", "dj")
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def _matches(given: str, accepted: list[str], case_sensitive: bool = False) -> bool:
    if case_sensitive:
        return given.strip() in [item.strip() for item in accepted]
    target = normalize(given)
    if not target:
        return False
    return any(normalize(item) == target for item in accepted)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


# --------------------------------------------------------------------------


@grader("mcq_single")
def _mcq_single(payload: dict, answer: dict) -> Grade:
    chosen = answer.get("index")
    correct = payload["correct_index"]
    ok = chosen is not None and int(chosen) == correct
    return Grade(
        is_correct=ok,
        score=1.0 if ok else 0.0,
        correct_text=payload["options"][correct],
    )


@grader("mcq_multi")
def _mcq_multi(payload: dict, answer: dict) -> Grade:
    correct = set(payload["correct_indices"])
    chosen = {int(item) for item in (answer.get("indices") or []) if str(item).lstrip("-").isdigit()}
    if not correct:
        return Grade(is_correct=False, score=0.0)

    hits = len(chosen & correct)
    misses = len(chosen - correct)
    score = _clamp((hits - misses) / len(correct))
    return Grade(
        is_correct=chosen == correct,
        score=score,
        correct_text=", ".join(payload["options"][index] for index in sorted(correct)),
        detail={"hits": hits, "wrong": misses},
    )


@grader("true_false")
def _true_false(payload: dict, answer: dict) -> Grade:
    given = answer.get("value")
    ok = given is not None and bool(given) == bool(payload["correct"])
    return Grade(is_correct=ok, score=1.0 if ok else 0.0,
                 correct_text="tacno" if payload["correct"] else "netacno")


@grader("fill_blank")
def _fill_blank(payload: dict, answer: dict) -> Grade:
    values = answer.get("values") or {}
    blanks = payload["blanks"]
    results = []
    for blank in blanks:
        given = str(values.get(str(blank["id"]), values.get(blank["id"], "")) or "")
        results.append(_matches(given, blank["accepted"], blank["case_sensitive"]))

    score = sum(results) / len(blanks) if blanks else 0.0
    correct_text = " / ".join(blank["accepted"][0] for blank in blanks)
    return Grade(
        is_correct=all(results),
        score=score,
        # Promasena praznina moze da bude sinonim koji nije predvidjen - to je
        # tacno ono sto AI treba da presudi, ali samo tada.
        needs_ai=not all(results),
        correct_text=correct_text,
        detail={"per_blank": results},
    )


@grader("cloze_dropdown")
def _cloze_dropdown(payload: dict, answer: dict) -> Grade:
    values = answer.get("values") or {}
    blanks = payload["blanks"]
    results = []
    for blank in blanks:
        given = values.get(str(blank["id"]), values.get(blank["id"]))
        results.append(given is not None and int(given) == blank["correct_index"])
    score = sum(results) / len(blanks) if blanks else 0.0
    return Grade(
        is_correct=all(results),
        score=score,
        correct_text=" / ".join(blank["options"][blank["correct_index"]] for blank in blanks),
        detail={"per_blank": results},
    )


@grader("short_answer")
def _short_answer(payload: dict, answer: dict) -> Grade:
    given = str(answer.get("text") or "")
    accepted = payload.get("accepted") or []
    correct_text = accepted[0] if accepted else " / ".join(payload.get("key_points") or [])

    if accepted and _matches(given, accepted, payload.get("case_sensitive", False)):
        return Grade(is_correct=True, score=1.0, correct_text=correct_text)
    if not given.strip():
        return Grade(is_correct=False, score=0.0, correct_text=correct_text)
    return Grade(is_correct=False, score=0.0, needs_ai=True, correct_text=correct_text)


@grader("long_answer")
def _long_answer(payload: dict, answer: dict) -> Grade:
    given = str(answer.get("text") or "")
    correct_text = payload.get("model_answer") or " / ".join(payload.get("key_points") or [])
    if not given.strip():
        return Grade(is_correct=False, score=0.0, correct_text=correct_text)
    return Grade(is_correct=False, score=0.0, needs_ai=True, correct_text=correct_text)


@grader("numeric")
def _numeric(payload: dict, answer: dict) -> Grade:
    unit = payload.get("unit") or ""
    correct_text = f"{_pretty(payload['value'])} {unit}".strip()
    raw = answer.get("value")
    if raw in (None, ""):
        return Grade(is_correct=False, score=0.0, correct_text=correct_text)
    try:
        given = float(str(raw).replace(",", "."))
    except (TypeError, ValueError):
        return Grade(is_correct=False, score=0.0, correct_text=correct_text)

    expected = float(payload["value"])
    tolerance = float(payload.get("tolerance") or 0)
    if payload.get("relative_tolerance"):
        tolerance = abs(expected) * tolerance
    ok = abs(given - expected) <= tolerance + 1e-9
    return Grade(is_correct=ok, score=1.0 if ok else 0.0, correct_text=correct_text)


@grader("match_pairs")
def _match_pairs(payload: dict, answer: dict) -> Grade:
    expected = payload["mapping"]
    given = answer.get("mapping") or []
    results = [
        index < len(given) and given[index] is not None and int(given[index]) == target
        for index, target in enumerate(expected)
    ]
    score = sum(results) / len(expected) if expected else 0.0
    correct_text = "; ".join(
        f"{payload['left'][index]} -> {payload['right'][target]}"
        for index, target in enumerate(expected)
    )
    return Grade(is_correct=all(results), score=score, correct_text=correct_text,
                 detail={"per_pair": results})


@grader("order_sequence")
def _order_sequence(payload: dict, answer: dict) -> Grade:
    expected = payload["correct_order"]
    given = [int(item) for item in (answer.get("order") or []) if str(item).lstrip("-").isdigit()]
    correct_text = " -> ".join(payload["items"][index] for index in expected)

    if given == expected:
        return Grade(is_correct=True, score=1.0, correct_text=correct_text)
    if len(given) != len(expected):
        return Grade(is_correct=False, score=0.0, correct_text=correct_text)

    # Delimican skor po broju ispravno uredjenih parova - blizu tacnog nije nula.
    total = 0
    right = 0
    for first in range(len(expected)):
        for second in range(first + 1, len(expected)):
            total += 1
            if given.index(expected[first]) < given.index(expected[second]):
                right += 1
    return Grade(is_correct=False, score=_clamp(right / total if total else 0), correct_text=correct_text)


@grader("odd_one_out")
def _odd_one_out(payload: dict, answer: dict) -> Grade:
    chosen = answer.get("index")
    correct = payload["correct_index"]
    ok = chosen is not None and int(chosen) == correct
    return Grade(is_correct=ok, score=1.0 if ok else 0.0, correct_text=payload["options"][correct])


@grader("image_match")
def _image_match(payload: dict, answer: dict) -> Grade:
    return _mcq_single(payload, answer)


@grader("image_label")
def _image_label(payload: dict, answer: dict) -> Grade:
    targets = payload["targets"]
    given = {str(item.get("id")): item for item in (answer.get("marks") or [])}
    results = []
    for target in targets:
        mark = given.get(str(target["id"]))
        if not mark:
            results.append(False)
            continue
        distance = ((float(mark.get("x", 0)) - target["x"]) ** 2
                    + (float(mark.get("y", 0)) - target["y"]) ** 2) ** 0.5
        results.append(distance <= target["radius"])
    score = sum(results) / len(targets) if targets else 0.0
    return Grade(
        is_correct=all(results),
        score=score,
        correct_text=", ".join(target["label"] for target in targets),
        detail={"per_target": results},
    )


@grader("work_it_out")
def _work_it_out(payload: dict, answer: dict) -> Grade:
    correct_text = f"{payload.get('final_answer', '')} {payload.get('unit', '')}".strip()
    has_input = bool(str(answer.get("text") or "").strip()) or bool(answer.get("photo_path"))
    if not has_input:
        return Grade(is_correct=False, score=0.0, correct_text=correct_text)
    return Grade(is_correct=False, score=0.0, needs_ai=True, correct_text=correct_text)


@grader("flashcard")
def _flashcard(payload: dict, answer: dict) -> Grade:
    knew = bool(answer.get("known"))
    return Grade(is_correct=knew, score=1.0 if knew else 0.0, correct_text=payload["back"])


def _pretty(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def correct_answer_text(question_type: str, payload: dict) -> str:
    """Tekst tacnog odgovora bez ocenjivanja - za prikaz i za AI prompt."""
    try:
        return grade({"type": question_type}, payload, {}).correct_text
    except (KeyError, IndexError, TypeError):
        return ""


def describe_answer(question_type: str, payload: dict, answer: dict) -> str:
    """Odgovor korisnika kao citljiv tekst - ulazi u prompt i u kes objasnjenja."""
    kind = question_types.get(question_type).answer_kind
    if kind == "choice":
        if "indices" in answer:
            options = payload.get("options") or []
            return ", ".join(
                options[int(index)] for index in answer["indices"] if 0 <= int(index) < len(options)
            )
        if "value" in answer:
            return "tacno" if answer["value"] else "netacno"
        index = answer.get("index")
        options = payload.get("options") or []
        if index is not None and 0 <= int(index) < len(options):
            return options[int(index)]
        if "values" in answer:
            return _describe_values(payload, answer["values"])
        return ""
    if kind == "text":
        if "values" in answer:
            return _describe_values(payload, answer["values"])
        return str(answer.get("text") or "")
    if kind == "number":
        return str(answer.get("value", ""))
    if kind == "order":
        items = payload.get("items") or []
        return " -> ".join(items[int(i)] for i in (answer.get("order") or []) if 0 <= int(i) < len(items))
    if kind == "pairs":
        if "mapping" in answer:
            left = payload.get("left") or []
            right = payload.get("right") or []
            pieces = []
            for index, target in enumerate(answer["mapping"] or []):
                if target is None or index >= len(left) or int(target) >= len(right):
                    continue
                pieces.append(f"{left[index]} -> {right[int(target)]}")
            return "; ".join(pieces)
        return str(answer.get("marks") or "")
    if kind == "photo":
        text = str(answer.get("text") or "")
        return text + (" [poslata slika resenja]" if answer.get("photo_path") else "")
    if kind == "self":
        return "znao sam" if answer.get("known") else "nisam znao"
    return ""


def _describe_values(payload: dict, values: dict) -> str:
    pieces = []
    for blank in payload.get("blanks") or []:
        given = values.get(str(blank["id"]), values.get(blank["id"], ""))
        if isinstance(given, int) and blank.get("options"):
            given = blank["options"][given] if 0 <= given < len(blank["options"]) else ""
        pieces.append(f"{blank['id']}: {given}")
    return ", ".join(pieces)
