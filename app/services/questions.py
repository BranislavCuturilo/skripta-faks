"""Pitanja: upis iz generisanja, citanje, korisnikove beleske i flagovi.

Beleska i flagovi zive u `question_meta`, odvojeno od samog pitanja. Kad AI
regenerise ili prepravi pitanje, ono sto je korisnik zapisao mora da ostane.
"""

import json
from typing import Any, Optional

from .. import db
from ..ai import contract
from ..http_util import HttpError
from ..quiz import grading, scheduler
from ..quiz import types as question_types

FLAG_FIELDS = {"flag_review", "flag_check_source", "flag_irrelevant", "flag_wrong", "pinned"}


def get(question_id: int, with_answer: bool = True) -> dict:
    row = db.query_one(
        """
        SELECT q.*,
               m.note, m.flag_review, m.flag_check_source, m.flag_irrelevant,
               m.flag_wrong, m.ignored_at, m.deleted_at, m.pinned,
               s.mastery, s.seen_count, s.correct_count, s.due_at, s.streak, s.lapses
          FROM question q
          LEFT JOIN question_meta m     ON m.question_id = q.id
          LEFT JOIN question_schedule s ON s.question_id = q.id
         WHERE q.id = ?
        """,
        (question_id,),
    )
    if not row:
        raise HttpError(404, "Pitanje ne postoji.")
    return hydrate(row, with_answer=with_answer)


def hydrate(row: dict, with_answer: bool = True) -> dict:
    """Red iz baze -> oblik koji frontend crta. Bez tacnog odgovora dok se pita."""
    payload = db.json_field(row, "payload")
    item = {
        "id": row["id"],
        "category_id": row["category_id"],
        "type": row["type"],
        "stem": row["stem"],
        "difficulty": row["difficulty"],
        "topic": row["topic"],
        "source_ref": row["source_ref"],
        "variant_group": row["variant_group"],
        "variant_index": row["variant_index"],
        "state": row["state"],
        "created_at": row.get("created_at"),
        "note": row.get("note") or "",
        "flags": {key: bool(row.get(key)) for key in FLAG_FIELDS},
        "ignored": bool(row.get("ignored_at")),
        "deleted": bool(row.get("deleted_at")),
        "progress": {
            "mastery": round(float(row.get("mastery") or 0), 3),
            "seen": int(row.get("seen_count") or 0),
            "correct": int(row.get("correct_count") or 0),
            "streak": int(row.get("streak") or 0),
            "lapses": int(row.get("lapses") or 0),
            "due_at": row.get("due_at"),
        },
        "presentation": _presentation(row["type"], payload),
    }
    if with_answer:
        item["payload"] = payload
        item["explanation"] = row["explanation"]
        item["correct_text"] = grading.correct_answer_text(row["type"], payload)
    return item


def _presentation(question_type: str, payload: dict) -> dict:
    """Ono sto se sme poslati pre nego sto korisnik odgovori."""
    visible: dict[str, Any] = {}
    for key in ("options", "items", "left", "right", "unit", "targets"):
        if key in payload:
            visible[key] = payload[key]
    if "image" in payload:
        visible["image"] = _resolve_image(payload["image"])

    if question_type == "image_label":
        visible["targets"] = [
            {"id": target["id"], "label": target["label"]} for target in payload.get("targets", [])
        ]
    if question_type in ("fill_blank", "cloze_dropdown"):
        visible["blanks"] = [
            {
                "id": blank["id"],
                "hint": blank.get("hint", ""),
                **({"options": blank["options"]} if "options" in blank else {}),
            }
            for blank in payload.get("blanks", [])
        ]
    if question_type == "work_it_out":
        visible["allow_photo"] = payload.get("allow_photo", True)
    if question_type == "flashcard":
        # Jedini tip kod koga poledjina sme napolje pre ocenjivanja: korisnik se
        # ocenjuje sam, pa "znao sam / nisam znao" nema smisla dok odgovor ne
        # vidi. Za svaki drugi tip ovde i dalje ne izlazi nista sto ga odaje.
        visible["back"] = payload.get("back", "")
    visible["answer_kind"] = question_types.get(question_type).answer_kind
    return visible


def _resolve_image(image: dict) -> dict:
    """Slika je referenca na materijal; browseru treba URL, ne id."""
    resolved = {"caption": image.get("caption", "")}
    path = image.get("path") or ""
    if not path and image.get("material_id"):
        row = db.query_one("SELECT rel_path FROM material WHERE id = ?", (image["material_id"],))
        path = row["rel_path"] if row else ""
    if path:
        resolved["url"] = f"/media/{path}"
    return resolved


def insert_many(
    category_id: int, run_id: Optional[int], items: list[dict], author: str = "ai"
) -> dict:
    """Upisi provalidirana pitanja, preskacuci ona koja vec postoje."""
    existing = {
        row["content_hash"]
        for row in db.query(
            "SELECT content_hash FROM question WHERE category_id = ?", (category_id,)
        )
    }
    inserted: list[int] = []
    duplicates = 0

    for item in items:
        if item["content_hash"] in existing:
            duplicates += 1
            continue
        existing.add(item["content_hash"])
        question_id = db.insert(
            "question",
            {
                "category_id": category_id,
                "generation_run_id": run_id,
                "type": item["type"],
                "stem": item["stem"],
                "payload": json.dumps(item["payload"], ensure_ascii=False),
                "explanation": item["explanation"],
                "difficulty": item["difficulty"],
                "topic": item["topic"],
                "source_ref": item["source_ref"],
                "content_hash": item["content_hash"],
                "variant_group": item["variant_group"],
                "variant_index": item["variant_index"],
            },
        )
        db.execute("INSERT INTO question_meta (question_id) VALUES (?)", (question_id,))
        scheduler.ensure_schedule(question_id, category_id)
        inserted.append(question_id)

    return {"inserted": inserted, "inserted_count": len(inserted), "duplicates": duplicates}


def list_for(
    category_ids: list[int],
    *,
    search: str = "",
    question_type: str = "",
    flag: str = "",
    include_deleted: bool = False,
    include_ignored: bool = True,
    limit: int = 200,
    offset: int = 0,
) -> dict:
    if not category_ids:
        return {"items": [], "total": 0}

    conditions = [f"q.category_id IN ({', '.join('?' for _ in category_ids)})"]
    params: list = list(category_ids)

    if not include_deleted:
        conditions.append("COALESCE(m.deleted_at, '') = ''")
    if not include_ignored:
        conditions.append("COALESCE(m.ignored_at, '') = ''")
    if question_type:
        conditions.append("q.type = ?")
        params.append(question_type)
    if flag in FLAG_FIELDS:
        conditions.append(f"COALESCE(m.{flag}, 0) = 1")
    if flag == "ignored":
        conditions.append("COALESCE(m.ignored_at, '') <> ''")
    if flag == "noted":
        conditions.append("COALESCE(m.note, '') <> ''")
    if search:
        conditions.append("(q.stem LIKE ? OR q.topic LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])

    where = " AND ".join(conditions)
    total = db.scalar(
        f"""
        SELECT COUNT(*) FROM question q
        LEFT JOIN question_meta m ON m.question_id = q.id
        WHERE {where}
        """,
        params,
        default=0,
    )
    rows = db.query(
        f"""
        SELECT q.*, m.note, m.flag_review, m.flag_check_source, m.flag_irrelevant,
               m.flag_wrong, m.ignored_at, m.deleted_at, m.pinned,
               s.mastery, s.seen_count, s.correct_count, s.due_at, s.streak, s.lapses
          FROM question q
          LEFT JOIN question_meta m     ON m.question_id = q.id
          LEFT JOIN question_schedule s ON s.question_id = q.id
         WHERE {where}
         ORDER BY q.created_at DESC, q.id DESC
         LIMIT ? OFFSET ?
        """,
        [*params, limit, offset],
    )
    return {"items": [hydrate(row) for row in rows], "total": total}


def variants_of(question_id: int) -> list[dict]:
    question = db.query_one("SELECT variant_group FROM question WHERE id = ?", (question_id,))
    if not question or not question["variant_group"]:
        return []
    rows = db.query(
        "SELECT * FROM question WHERE variant_group = ? ORDER BY variant_index",
        (question["variant_group"],),
    )
    return [hydrate(row) for row in rows]


def set_meta(question_id: int, values: dict) -> dict:
    get(question_id, with_answer=False)
    db.execute("INSERT INTO question_meta (question_id) VALUES (?) ON CONFLICT DO NOTHING",
               (question_id,))

    changes: dict[str, Any] = {}
    if "note" in values:
        changes["note"] = str(values["note"] or "")[:4000]
    for key in FLAG_FIELDS:
        if key in values:
            changes[key] = 1 if _truthy(values[key]) else 0
    if "ignored" in values:
        changes["ignored_at"] = _now() if _truthy(values["ignored"]) else None
    if "deleted" in values:
        changes["deleted_at"] = _now() if _truthy(values["deleted"]) else None

    if changes:
        changes["updated_at"] = _now()
        db.update("question_meta", question_id, changes, id_column="question_id")
    return get(question_id)


def edit(question_id: int, values: dict) -> dict:
    """Rucna ispravka pitanja. Ponovo prolazi kroz isti ugovor kao AI izlaz."""
    current = get(question_id)
    candidate = {
        "type": values.get("type", current["type"]),
        "stem": values.get("stem", current["stem"]),
        "payload": values.get("payload", current["payload"]),
        "explanation": values.get("explanation", current["explanation"]),
        "difficulty": values.get("difficulty", current["difficulty"]),
        "topic": values.get("topic", current["topic"]),
        "source_ref": values.get("source_ref", current["source_ref"]),
    }
    try:
        validated = contract.validate_one(candidate)
    except (contract.ContractError, question_types.InvalidQuestion) as exc:
        raise HttpError(400, f"Izmena nije ispravna: {exc}") from None

    db.update(
        "question",
        question_id,
        {
            "type": validated["type"],
            "stem": validated["stem"],
            "payload": json.dumps(validated["payload"], ensure_ascii=False),
            "explanation": validated["explanation"],
            "difficulty": validated["difficulty"],
            "topic": validated["topic"],
            "source_ref": validated["source_ref"],
            "content_hash": validated["content_hash"],
            "updated_at": _now(),
        },
    )
    return get(question_id)


def purge(question_id: int) -> None:
    """Trajno brisanje. 'deleted' flag je meko brisanje i vraca se."""
    get(question_id, with_answer=False)
    db.execute("DELETE FROM question WHERE id = ?", (question_id,))


def existing_stems(category_ids: list[int], limit: int = 200) -> list[str]:
    if not category_ids:
        return []
    marks = ", ".join("?" for _ in category_ids)
    rows = db.query(
        f"""
        SELECT stem FROM question
         WHERE category_id IN ({marks}) AND state = 'active'
         ORDER BY created_at DESC LIMIT ?
        """,
        [*category_ids, limit],
    )
    return [row["stem"] for row in rows]


def type_counts(category_ids: list[int]) -> dict:
    if not category_ids:
        return {}
    marks = ", ".join("?" for _ in category_ids)
    rows = db.query(
        f"""
        SELECT q.type, COUNT(*) AS n FROM question q
        LEFT JOIN question_meta m ON m.question_id = q.id
        WHERE q.category_id IN ({marks}) AND q.state = 'active'
              AND COALESCE(m.deleted_at, '') = ''
        GROUP BY q.type
        """,
        category_ids,
    )
    return {row["type"]: row["n"] for row in rows}


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "da", "yes", "on")


def _now() -> str:
    return db.scalar("SELECT datetime('now')")
