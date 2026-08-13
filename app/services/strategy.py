"""Adaptivna strategija: kako sistem menja nacin na koji te ispituje.

Ovo je ono "app menja sam sebe" - i granica je namerno ostra. Menja se SADRZAJ
U BAZI koji ulazi u sledeci prompt: raspodela tipova, tezina, teme u fokusu,
profil gresaka. Kod aplikacije se ne dira nikad.

Svaka verzija se cuva. Na ekranu se vidi sta je promenjeno i zasto, i svaka se
vraca jednim klikom - inace bi sistem tiho odlutao i ne bi se znalo kada.
"""

import json
from typing import Any, Optional

from .. import db
from ..ai import contract, gemini, prompts
from ..http_util import HttpError
from . import ai_models, categories, settings_store

KIND_GENERATION = "generation"


def active(category_id: Optional[int], kind: str = KIND_GENERATION) -> dict:
    """Strategija kategorije, sa padom na roditelja pa na globalnu."""
    chain: list[Optional[int]] = []
    if category_id:
        chain = [node["id"] for node in reversed(categories.breadcrumb(category_id))]
    chain.append(None)

    for candidate in chain:
        row = db.query_one(
            """
            SELECT * FROM strategy
             WHERE category_id IS ? AND kind = ? AND active = 1
             ORDER BY version DESC LIMIT 1
            """,
            (candidate, kind),
        )
        if row:
            return {**row, "content": db.json_field(row, "content")}
    return {"id": None, "category_id": category_id, "kind": kind, "content": {}, "version": 0}


def save(
    category_id: Optional[int],
    kind: str,
    content: dict,
    rationale: str = "",
    author: str = "system",
) -> dict:
    version = db.scalar(
        "SELECT COALESCE(MAX(version), 0) + 1 FROM strategy WHERE category_id IS ? AND kind = ?",
        (category_id, kind),
        default=1,
    )
    db.execute(
        "UPDATE strategy SET active = 0 WHERE category_id IS ? AND kind = ?", (category_id, kind)
    )
    strategy_id = db.insert(
        "strategy",
        {
            "category_id": category_id,
            "kind": kind,
            "version": version,
            "content": json.dumps(content, ensure_ascii=False),
            "rationale": rationale,
            "author": author,
            "active": 1,
        },
    )
    row = db.query_one("SELECT * FROM strategy WHERE id = ?", (strategy_id,))
    return {**row, "content": db.json_field(row, "content")}


def history(category_id: Optional[int], kind: str = KIND_GENERATION, limit: int = 30) -> list[dict]:
    rows = db.query(
        """
        SELECT * FROM strategy WHERE category_id IS ? AND kind = ?
        ORDER BY version DESC LIMIT ?
        """,
        (category_id, kind, limit),
    )
    return [{**row, "content": db.json_field(row, "content")} for row in rows]


def revert(strategy_id: int) -> dict:
    row = db.query_one("SELECT * FROM strategy WHERE id = ?", (strategy_id,))
    if not row:
        raise HttpError(404, "Verzija strategije ne postoji.")
    return save(
        row["category_id"],
        row["kind"],
        db.json_field(row, "content"),
        rationale=f"Vraceno na verziju {row['version']}.",
        author="user",
    )


# --------------------------------------------------------------------------
# profil gresaka
# --------------------------------------------------------------------------


def misconceptions(category_id: int, limit: int = 20) -> list[dict]:
    ids = categories.subtree_ids(category_id)
    marks = ", ".join("?" for _ in ids)
    return db.query(
        f"""
        SELECT * FROM misconception
         WHERE category_id IN ({marks}) AND resolved_at IS NULL
         ORDER BY evidence_count DESC, last_seen_at DESC LIMIT ?
        """,
        [*ids, limit],
    )


def record_misconception(category_id: int, label: str, description: str = "", topic: str = "") -> None:
    label = (label or "").strip()[:160]
    if not label:
        return
    db.execute(
        """
        INSERT INTO misconception (category_id, label, description, topic)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(category_id, label) DO UPDATE SET
            evidence_count = evidence_count + 1,
            last_seen_at   = datetime('now'),
            resolved_at    = NULL,
            description    = CASE WHEN excluded.description <> '' THEN excluded.description
                                  ELSE misconception.description END
        """,
        (category_id, label, description[:500], topic[:120]),
    )


def resolve_misconception(misconception_id: int, resolved: bool = True) -> None:
    db.execute(
        "UPDATE misconception SET resolved_at = ? WHERE id = ?",
        (db.scalar("SELECT datetime('now')") if resolved else None, misconception_id),
    )


# --------------------------------------------------------------------------
# dokazi i samo-azuriranje
# --------------------------------------------------------------------------


def evidence(category_id: int, attempt_limit: int = 400) -> dict:
    """Sazetak dosadasnjeg ucenja - ulaz u prompt kojim sistem menja strategiju."""
    ids = categories.subtree_ids(category_id)
    marks = ", ".join("?" for _ in ids)

    by_type = db.query(
        f"""
        SELECT q.type,
               COUNT(*) AS attempts,
               ROUND(AVG(a.score), 3) AS average_score
          FROM attempt a JOIN question q ON q.id = a.question_id
         WHERE q.category_id IN ({marks})
         GROUP BY q.type ORDER BY attempts DESC
        """,
        ids,
    )
    by_topic = db.query(
        f"""
        SELECT COALESCE(NULLIF(q.topic, ''), '(bez teme)') AS topic,
               COUNT(*) AS attempts,
               ROUND(AVG(a.score), 3) AS average_score
          FROM attempt a JOIN question q ON q.id = a.question_id
         WHERE q.category_id IN ({marks})
         GROUP BY topic HAVING attempts >= 2
         ORDER BY average_score ASC LIMIT 25
        """,
        ids,
    )
    by_difficulty = db.query(
        f"""
        SELECT q.difficulty, COUNT(*) AS attempts, ROUND(AVG(a.score), 3) AS average_score
          FROM attempt a JOIN question q ON q.id = a.question_id
         WHERE q.category_id IN ({marks})
         GROUP BY q.difficulty ORDER BY q.difficulty
        """,
        ids,
    )
    repeated = db.query(
        f"""
        SELECT a.misconception AS label, COUNT(*) AS times
          FROM attempt a JOIN question q ON q.id = a.question_id
         WHERE q.category_id IN ({marks}) AND COALESCE(a.misconception, '') <> ''
         GROUP BY a.misconception ORDER BY times DESC LIMIT 15
        """,
        ids,
    )
    skipped = db.query(
        f"""
        SELECT q.type, COUNT(*) AS times FROM session_skip k
          JOIN question q ON q.id = k.question_id
         WHERE q.category_id IN ({marks})
         GROUP BY q.type ORDER BY times DESC LIMIT 10
        """,
        ids,
    )
    totals = db.query_one(
        f"""
        SELECT COUNT(*) AS attempts, ROUND(AVG(a.score), 3) AS average_score
          FROM attempt a JOIN question q ON q.id = a.question_id
         WHERE q.category_id IN ({marks})
        """,
        ids,
    ) or {}

    return {
        "category": categories.get(category_id)["name"],
        "totals": totals,
        "by_type": by_type,
        "weakest_topics": by_topic,
        "by_difficulty": by_difficulty,
        "repeated_misconceptions": repeated,
        "skipped_types": skipped,
        "known_misconceptions": [
            {"label": item["label"], "count": item["evidence_count"]}
            for item in misconceptions(category_id)
        ],
        "attempt_sample_limit": attempt_limit,
    }


def refresh(category_id: int, min_attempts: int = 15) -> dict:
    """Pozovi model da predlozi novu strategiju i sacuvaj je kao novu verziju."""
    data = evidence(category_id)
    attempts = int((data.get("totals") or {}).get("attempts") or 0)
    if attempts < min_attempts:
        return {
            "ok": False,
            "skipped": True,
            "reason": f"Premalo podataka ({attempts} od {min_attempts} odgovora).",
        }

    api_key = settings_store.get("gemini_api_key", "")
    path = " / ".join(node["name"] for node in categories.breadcrumb(category_id))

    prompt = prompts.build_strategy_prompt(
        category_path=path,
        evidence=data,
        language=settings_store.get("ui_language", "sr"),
    )
    result = ai_models.generate(
        "standard",
        prompt,
        api_key=api_key,
        system="Ti si metodicar koji podesava nacin ispitivanja. Odgovaras iskljucivo JSON-om.",
        json_output=True,
        temperature=0.4,
        purpose="strategy",
    )

    try:
        payload = json.loads(contract.strip_fence(result["text"]))
    except ValueError as exc:
        raise HttpError(502, f"Model nije vratio ispravan JSON: {exc}") from None
    if not isinstance(payload, dict):
        raise HttpError(502, "Model nije vratio objekat.")

    for item in payload.get("misconceptions") or []:
        if isinstance(item, dict):
            record_misconception(
                category_id, item.get("label", ""), item.get("description", ""), item.get("topic", "")
            )

    content = {
        "type_mix": _clean_type_mix(payload.get("type_mix")),
        "difficulty_bias": _clamp_bias(payload.get("difficulty_bias")),
        "focus_topics": _string_list(payload.get("focus_topics")),
        "avoid_topics": _string_list(payload.get("avoid_topics")),
        "generation_note": str(payload.get("generation_note") or "").strip()[:1200],
    }
    saved = save(
        category_id,
        KIND_GENERATION,
        content,
        rationale=str(payload.get("rationale") or "").strip()[:2000],
        author="ai",
    )
    return {"ok": True, "strategy": saved, "evidence": data}


def _clean_type_mix(value: Any) -> dict:
    from ..quiz import types as question_types

    if not isinstance(value, dict):
        return {}
    result = {}
    for key, weight in value.items():
        if not question_types.exists(str(key)):
            continue
        try:
            number = max(0, min(20, int(weight)))
        except (TypeError, ValueError):
            continue
        if number:
            result[str(key)] = number
    return result


def _clamp_bias(value: Any) -> int:
    try:
        return max(-1, min(1, int(value)))
    except (TypeError, ValueError):
        return 0


def _string_list(value: Any, limit: int = 15) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip()[:120] for item in value if str(item).strip()][:limit]
