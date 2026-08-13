"""Registar tipova pitanja.

Tip je kljuc u registru, ne grana u if-u: dodavanje novog tipa je jedan unos
ovde plus jedan renderer u frontendu. AI dobija bas ovaj katalog u promptu, pa
sto je registar tacniji, to je generisani JSON blizi upotrebljivom.

`validate` normalizuje ono sto model vrati i baca ValueError na neupotrebljivo.
Bolje odbaciti pitanje pri uvozu nego ga prikazati polomljenog usred ucenja.
"""

from dataclasses import dataclass, field
from typing import Any, Callable


class InvalidQuestion(ValueError):
    pass


@dataclass(frozen=True)
class QuestionType:
    key: str
    label: str
    hint: str
    answer_kind: str
    grading: str
    validate: Callable[[str, dict], dict]
    needs_image: bool = False
    ai_instructions: str = ""
    example: dict = field(default_factory=dict)


_REGISTRY: dict[str, QuestionType] = {}


def register(question_type: QuestionType) -> QuestionType:
    _REGISTRY[question_type.key] = question_type
    return question_type


def get(key: str) -> QuestionType:
    try:
        return _REGISTRY[key]
    except KeyError:
        raise InvalidQuestion(f"Nepoznat tip pitanja: {key}") from None


def exists(key: str) -> bool:
    return key in _REGISTRY


def all_types() -> list[QuestionType]:
    return list(_REGISTRY.values())


def keys() -> list[str]:
    return list(_REGISTRY)


def catalog() -> list[dict]:
    return [
        {
            "key": item.key,
            "label": item.label,
            "hint": item.hint,
            "answer_kind": item.answer_kind,
            "grading": item.grading,
            "needs_image": item.needs_image,
        }
        for item in _REGISTRY.values()
    ]


def normalize(question_type: str, payload: dict) -> dict:
    return get(question_type).validate(question_type, payload or {})


# --------------------------------------------------------------------------
# pomocni validatori
# --------------------------------------------------------------------------


def _texts(payload: dict, key: str, minimum: int, maximum: int = 12) -> list[str]:
    raw = payload.get(key)
    if not isinstance(raw, list):
        raise InvalidQuestion(f"Polje '{key}' mora da bude lista.")
    values = [str(item).strip() for item in raw if str(item).strip()]
    if len(values) < minimum:
        raise InvalidQuestion(f"Polje '{key}' mora da ima bar {minimum} stavki.")
    return values[:maximum]


def _index(payload: dict, key: str, size: int) -> int:
    try:
        value = int(payload[key])
    except (KeyError, TypeError, ValueError):
        raise InvalidQuestion(f"Polje '{key}' mora da bude ceo broj.") from None
    if not 0 <= value < size:
        raise InvalidQuestion(f"Polje '{key}' pokazuje van opsega.")
    return value


def _indices(payload: dict, key: str, size: int, minimum: int = 1) -> list[int]:
    raw = payload.get(key)
    if not isinstance(raw, list):
        raise InvalidQuestion(f"Polje '{key}' mora da bude lista brojeva.")
    values = []
    for item in raw:
        try:
            number = int(item)
        except (TypeError, ValueError):
            raise InvalidQuestion(f"Polje '{key}' sadrzi vrednost koja nije broj.") from None
        if not 0 <= number < size:
            raise InvalidQuestion(f"Polje '{key}' pokazuje van opsega.")
        values.append(number)
    unique = sorted(set(values))
    if len(unique) < minimum:
        raise InvalidQuestion(f"Polje '{key}' mora da ima bar {minimum} vrednost.")
    return unique


def _flag(payload: dict, key: str, fallback: bool = False) -> bool:
    value = payload.get(key, fallback)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "da", "yes", "on")


def _image(payload: dict) -> dict:
    """Slika je referenca na uploadovani materijal, nikad spoljni URL."""
    raw = payload.get("image") or {}
    if not isinstance(raw, dict):
        raise InvalidQuestion("Polje 'image' mora da bude objekat.")
    material_id = raw.get("material_id")
    path = str(raw.get("path") or "").strip()
    if not material_id and not path:
        raise InvalidQuestion("Pitanje sa slikom mora da nosi 'image.material_id' ili 'image.path'.")
    image = {"caption": str(raw.get("caption") or "").strip()}
    if material_id:
        image["material_id"] = int(material_id)
    if path:
        image["path"] = path
    if raw.get("page"):
        image["page"] = int(raw["page"])
    return image


# --------------------------------------------------------------------------
# tipovi
# --------------------------------------------------------------------------


def _mcq_single(key: str, payload: dict) -> dict:
    options = _texts(payload, "options", 2, 8)
    return {
        "options": options,
        "correct_index": _index(payload, "correct_index", len(options)),
        "shuffle": _flag(payload, "shuffle", True),
        "option_notes": [str(item) for item in (payload.get("option_notes") or [])][: len(options)],
    }


def _mcq_multi(key: str, payload: dict) -> dict:
    options = _texts(payload, "options", 3, 10)
    return {
        "options": options,
        "correct_indices": _indices(payload, "correct_indices", len(options)),
        "shuffle": _flag(payload, "shuffle", True),
        "option_notes": [str(item) for item in (payload.get("option_notes") or [])][: len(options)],
    }


def _true_false(key: str, payload: dict) -> dict:
    if "correct" not in payload:
        raise InvalidQuestion("Polje 'correct' je obavezno.")
    return {"correct": _flag(payload, "correct")}


def _fill_blank(key: str, payload: dict) -> dict:
    raw = payload.get("blanks")
    if not isinstance(raw, list) or not raw:
        raise InvalidQuestion("Polje 'blanks' mora da bude neprazna lista.")
    blanks = []
    for position, item in enumerate(raw, start=1):
        if isinstance(item, str):
            item = {"accepted": [item]}
        accepted = [str(value).strip() for value in (item.get("accepted") or []) if str(value).strip()]
        if not accepted:
            raise InvalidQuestion(f"Praznina {position} nema nijedan prihvatljiv odgovor.")
        blanks.append(
            {
                "id": int(item.get("id") or position),
                "accepted": accepted,
                "case_sensitive": _flag(item, "case_sensitive", False),
                "hint": str(item.get("hint") or "").strip(),
            }
        )
    return {"blanks": blanks, "strict_order": _flag(payload, "strict_order", True)}


def _cloze_dropdown(key: str, payload: dict) -> dict:
    raw = payload.get("blanks")
    if not isinstance(raw, list) or not raw:
        raise InvalidQuestion("Polje 'blanks' mora da bude neprazna lista.")
    blanks = []
    for position, item in enumerate(raw, start=1):
        options = _texts(item, "options", 2, 8)
        blanks.append(
            {
                "id": int(item.get("id") or position),
                "options": options,
                "correct_index": _index(item, "correct_index", len(options)),
            }
        )
    return {"blanks": blanks}


def _short_answer(key: str, payload: dict) -> dict:
    accepted = [str(item).strip() for item in (payload.get("accepted") or []) if str(item).strip()]
    key_points = [str(item).strip() for item in (payload.get("key_points") or []) if str(item).strip()]
    if not accepted and not key_points:
        raise InvalidQuestion("Kratak odgovor mora da nosi 'accepted' ili 'key_points'.")
    return {
        "accepted": accepted,
        "key_points": key_points,
        "case_sensitive": _flag(payload, "case_sensitive", False),
    }


def _long_answer(key: str, payload: dict) -> dict:
    key_points = [str(item).strip() for item in (payload.get("key_points") or []) if str(item).strip()]
    if not key_points:
        raise InvalidQuestion("Duzi odgovor mora da nosi 'key_points' po kojima se ocenjuje.")
    return {
        "key_points": key_points,
        "model_answer": str(payload.get("model_answer") or "").strip(),
        "min_points": int(payload.get("min_points") or max(1, len(key_points) // 2)),
    }


def _numeric(key: str, payload: dict) -> dict:
    try:
        value = float(payload["value"])
    except (KeyError, TypeError, ValueError):
        raise InvalidQuestion("Polje 'value' mora da bude broj.") from None
    tolerance = payload.get("tolerance", 0)
    try:
        tolerance = abs(float(tolerance))
    except (TypeError, ValueError):
        tolerance = 0.0
    return {
        "value": value,
        "tolerance": tolerance,
        "relative_tolerance": _flag(payload, "relative_tolerance", False),
        "unit": str(payload.get("unit") or "").strip(),
    }


def _match_pairs(key: str, payload: dict) -> dict:
    left = _texts(payload, "left", 2, 10)
    right = _texts(payload, "right", 2, 12)
    mapping = payload.get("mapping")
    if not isinstance(mapping, list) or len(mapping) != len(left):
        raise InvalidQuestion("Polje 'mapping' mora da ima tacno onoliko stavki koliko i 'left'.")
    pairs = []
    for position, item in enumerate(mapping):
        try:
            target = int(item)
        except (TypeError, ValueError):
            raise InvalidQuestion("Polje 'mapping' sadrzi vrednost koja nije broj.") from None
        if not 0 <= target < len(right):
            raise InvalidQuestion("Polje 'mapping' pokazuje van desne kolone.")
        pairs.append(target)
    return {"left": left, "right": right, "mapping": pairs}


def _order_sequence(key: str, payload: dict) -> dict:
    items = _texts(payload, "items", 3, 12)
    raw = payload.get("correct_order")
    if not isinstance(raw, list) or len(raw) != len(items):
        raise InvalidQuestion("Polje 'correct_order' mora da bude permutacija stavki.")
    order = []
    for item in raw:
        try:
            order.append(int(item))
        except (TypeError, ValueError):
            raise InvalidQuestion("Polje 'correct_order' sadrzi vrednost koja nije broj.") from None
    if sorted(order) != list(range(len(items))):
        raise InvalidQuestion("Polje 'correct_order' nije permutacija indeksa stavki.")
    return {"items": items, "correct_order": order}


def _odd_one_out(key: str, payload: dict) -> dict:
    options = _texts(payload, "options", 3, 8)
    return {
        "options": options,
        "correct_index": _index(payload, "correct_index", len(options)),
        "rule": str(payload.get("rule") or "").strip(),
    }


def _image_match(key: str, payload: dict) -> dict:
    options = _texts(payload, "options", 2, 8)
    return {
        "image": _image(payload),
        "options": options,
        "correct_index": _index(payload, "correct_index", len(options)),
    }


def _image_label(key: str, payload: dict) -> dict:
    raw = payload.get("targets")
    if not isinstance(raw, list) or not raw:
        raise InvalidQuestion("Polje 'targets' mora da bude neprazna lista.")
    targets = []
    for position, item in enumerate(raw, start=1):
        label = str(item.get("label") or "").strip()
        if not label:
            raise InvalidQuestion(f"Meta {position} nema naziv.")
        targets.append(
            {
                "id": int(item.get("id") or position),
                "label": label,
                "x": float(item.get("x") or 0),
                "y": float(item.get("y") or 0),
                "radius": float(item.get("radius") or 0.08),
            }
        )
    return {"image": _image(payload), "targets": targets}


def _work_it_out(key: str, payload: dict) -> dict:
    return {
        "final_answer": str(payload.get("final_answer") or "").strip(),
        "expected_steps": [
            str(item).strip() for item in (payload.get("expected_steps") or []) if str(item).strip()
        ],
        "allow_photo": _flag(payload, "allow_photo", True),
        "unit": str(payload.get("unit") or "").strip(),
    }


def _flashcard(key: str, payload: dict) -> dict:
    back = str(payload.get("back") or "").strip()
    if not back:
        raise InvalidQuestion("Kartica mora da ima poledjinu ('back').")
    return {"back": back}


register(QuestionType(
    key="mcq_single", label="Zaokruži tačan odgovor", grading="local", answer_kind="choice",
    hint="Jedno pitanje, više ponuđenih, tačno jedan tačan.", validate=_mcq_single,
    ai_instructions="options: 4-5 ponudjenih; correct_index: indeks tacnog; distraktori moraju biti uverljivi i tipicne greske, ne ocigledno pogresni.",
))
register(QuestionType(
    key="mcq_multi", label="Zaokruži sve tačne", grading="local", answer_kind="choice",
    hint="Više tačnih odgovora; delimično tačan nosi delimičan skor.", validate=_mcq_multi,
    ai_instructions="correct_indices: lista indeksa svih tacnih (bar 1, ne svi).",
))
register(QuestionType(
    key="true_false", label="Tačno ili netačno", grading="local", answer_kind="choice",
    hint="Tvrdnja koju treba oceniti.", validate=_true_false,
    ai_instructions="stem je tvrdnja, ne pitanje. correct: true/false.",
))
register(QuestionType(
    key="fill_blank", label="Dopuni rečenicu", grading="hybrid", answer_kind="text",
    hint="U tekstu stoje praznine {{1}}, {{2}} koje korisnik popunjava.", validate=_fill_blank,
    ai_instructions="U 'stem' upisi praznine kao {{1}}, {{2}}. Za svaku prazninu navedi sve prihvatljive oblike u 'accepted' (padezi, sinonimi, skracenice).",
))
register(QuestionType(
    key="cloze_dropdown", label="Dopuni izborom", grading="local", answer_kind="choice",
    hint="Praznine u tekstu, ali sa padajućom listom umesto kucanja.", validate=_cloze_dropdown,
    ai_instructions="U 'stem' upisi praznine kao {{1}}. Svaka praznina nosi 3-4 opcije i correct_index.",
))
register(QuestionType(
    key="short_answer", label="Kratak odgovor", grading="hybrid", answer_kind="text",
    hint="Jedna reč ili rečenica; ako nije doslovno pogođeno, ocenjuje AI.", validate=_short_answer,
    ai_instructions="accepted: doslovni prihvatljivi odgovori. key_points: sta odgovor mora da sadrzi da bi bio tacan.",
))
register(QuestionType(
    key="long_answer", label="Napiši rešenje / objasni", grading="ai", answer_kind="text",
    hint="Duži odgovor koji AI ocenjuje po ključnim tačkama.", validate=_long_answer,
    ai_instructions="key_points: 3-6 tacaka po kojima se ocenjuje. model_answer: kako izgleda pun odgovor.",
))
register(QuestionType(
    key="numeric", label="Brojčani odgovor", grading="local", answer_kind="number",
    hint="Rezultat kao broj, sa dozvoljenom tolerancijom.", validate=_numeric,
    ai_instructions="value: tacan broj. tolerance: dozvoljeno odstupanje. unit: merna jedinica ako postoji.",
))
register(QuestionType(
    key="match_pairs", label="Poveži parove", grading="local", answer_kind="pairs",
    hint="Leva kolona se povezuje sa desnom.", validate=_match_pairs,
    ai_instructions="left i right kao liste; mapping[i] je indeks u 'right' koji odgovara left[i]. U 'right' smes dodati 1-2 viska.",
))
register(QuestionType(
    key="order_sequence", label="Poređaj redosled", grading="local", answer_kind="order",
    hint="Koraci ili događaji koje treba poređati.", validate=_order_sequence,
    ai_instructions="items u izmesanom redosledu; correct_order je permutacija indeksa u tacnom redosledu.",
))
register(QuestionType(
    key="odd_one_out", label="Koji ne pripada", grading="local", answer_kind="choice",
    hint="Jedan pojam odudara od ostalih po nekom pravilu.", validate=_odd_one_out,
    ai_instructions="rule: pravilo po kome ostali pripadaju zajedno.",
))
register(QuestionType(
    key="image_match", label="Poveži sa slikom", grading="local", answer_kind="choice",
    hint="Prikazuje se slika iz materijala, bira se šta je na njoj.", validate=_image_match,
    needs_image=True,
    ai_instructions="image.material_id je id materijala koji je slika; koristi samo materijale koje si dobio u kontekstu.",
))
register(QuestionType(
    key="image_label", label="Označi na slici", grading="local", answer_kind="pairs",
    hint="Klikom se označavaju delovi slike.", validate=_image_label, needs_image=True,
    ai_instructions="targets nose label i priblizne koordinate x,y kao udeo sirine/visine (0-1).",
))
register(QuestionType(
    key="work_it_out", label="Uradi zadatak", grading="ai", answer_kind="photo",
    hint="Rešiš na papiru, slikaš telefonom, AI proverava postupak.", validate=_work_it_out,
    ai_instructions="final_answer: konacan rezultat. expected_steps: koraci postupka koji moraju da se vide.",
))
register(QuestionType(
    key="flashcard", label="Kartica (sam se ocenjuješ)", grading="self", answer_kind="self",
    hint="Setiš se odgovora, okreneš karticu i kažeš da li si znao.", validate=_flashcard,
    ai_instructions="stem je prednja strana, back je poledjina. Kratko, jedan pojam.",
))
