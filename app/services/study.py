"""Sesija ucenja: izbor pitanja, ocenjivanje, objasnjenja.

Objasnjenje se placa AI pozivom samo kad mora. Kod ponudjenih odgovora vec
postoji napisano objasnjenje iz generisanja. Kod dopune recenice, kratkog i
duzeg odgovora ga nema unapred - tada se zove model, i odgovor se upisuje u
`explanation_cache`, pa isti pogresan odgovor drugi put ne kosta nista.
"""

import hashlib
import json
from typing import Any, Optional

from .. import config, db, translit
from ..ai import gemini, prompts
from ..http_util import HttpError
from ..quiz import grading, scheduler
from ..quiz import types as question_types
from . import ai_models, categories, questions, settings_store, strategy

GRADE_TIMEOUT_S = 30.0
GRADE_TIMEOUT_PHOTO_S = 90.0
GRADE_MAX_ATTEMPTS = 2


def start(category_id: int, options: Optional[dict] = None) -> dict:
    options = options or {}
    categories.get(category_id)

    include_subtree = str(options.get("include_subtree", True)).lower() not in ("0", "false", "ne")
    aggressiveness = int(options.get("aggressiveness") or settings_store.get("aggressiveness", 3))
    length = max(1, min(200, int(options.get("length") or settings_store.get("session_length", 20))))
    mode = str(options.get("mode") or "adaptive")
    type_filter = options.get("type_filter") or []
    if isinstance(type_filter, str):
        type_filter = [item.strip() for item in type_filter.split(",") if item.strip()]
    origin_filter = str(options.get("origin_filter") or "").strip()
    if origin_filter not in ("", "ai", "exam"):
        raise HttpError(400, "Nepoznat filter porekla pitanja.")

    ids = categories.subtree_ids(category_id) if include_subtree else [category_id]
    available = scheduler.pick(
        ids, limit=length, aggressiveness=aggressiveness, type_filter=type_filter, mode=mode,
        origin=origin_filter,
    )
    if not available:
        raise HttpError(
            400,
            "Nema pitanja za učenje u ovoj kategoriji. Generiši ih iz materijala, "
            "ili ublaži filter.",
        )

    session_id = db.insert(
        "study_session",
        {
            "category_id": category_id,
            "include_subtree": 1 if include_subtree else 0,
            "mode": mode,
            "aggressiveness": aggressiveness,
            "type_filter": ",".join(type_filter),
            "origin_filter": origin_filter,
            "planned_count": len(available),
        },
    )
    return {
        "session": db.query_one("SELECT * FROM study_session WHERE id = ?", (session_id,)),
        "planned": len(available),
        "stats": scheduler.stats(ids, aggressiveness),
    }


def next_question(session_id: int) -> dict:
    session = _session(session_id)
    if session["ended_at"]:
        raise HttpError(400, "Sesija je zavrsena.")

    ids = _session_categories(session)
    picked = scheduler.pick(
        ids,
        limit=1,
        aggressiveness=session["aggressiveness"],
        session_id=session_id,
        type_filter=[item for item in (session["type_filter"] or "").split(",") if item],
        mode=session["mode"],
        origin=session.get("origin_filter") or "",
    )
    remaining = max(0, session["planned_count"] - session["asked_count"])
    if not picked or remaining <= 0:
        return {"done": True, "summary": summary(session_id)}

    question = questions.get(picked[0]["id"], with_answer=False)
    return {
        "done": False,
        "question": question,
        "remaining": remaining,
        "asked": session["asked_count"],
        "correct": session["correct_count"],
    }


def answer(session_id: Optional[int], question_id: int, payload: dict) -> dict:
    """Oceni odgovor. Lokalno kad god moze, AI samo kad mora."""
    question = questions.get(question_id)
    session = _session(session_id) if session_id else None
    aggressiveness = session["aggressiveness"] if session else settings_store.get("aggressiveness", 3)

    given = payload.get("answer") or {}
    if payload.get("photo_path"):
        given = {**given, "photo_path": payload["photo_path"]}

    result = grading.grade(question, question["payload"], given)
    answer_text = grading.describe_answer(question["type"], question["payload"], given)
    answer_hash = hashlib.sha256(
        f"{question_id}|{grading.normalize(answer_text)}".encode("utf-8")
    ).hexdigest()

    graded_by = "local"
    feedback = ""
    misconception = ""

    if result.needs_ai:
        cached = db.query_one(
            "SELECT * FROM explanation_cache WHERE question_id = ? AND answer_hash = ?",
            (question_id, answer_hash),
        )
        if cached:
            result.is_correct = bool(cached["is_correct"])
            result.score = float(cached["score"])
            feedback = cached["feedback"]
            misconception = cached["misconception"]
            graded_by = "cache"
        else:
            verdict = _ask_ai(question, answer_text, given)
            if verdict is not None:
                result.is_correct = verdict["is_correct"]
                result.score = verdict["score"]
                feedback = verdict["feedback"]
                misconception = verdict["misconception"]
                graded_by = "ai"
                db.execute(
                    """
                    INSERT INTO explanation_cache
                        (question_id, answer_hash, is_correct, score, feedback, misconception)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(question_id, answer_hash) DO NOTHING
                    """,
                    (question_id, answer_hash, 1 if verdict["is_correct"] else 0,
                     verdict["score"], verdict["feedback"], verdict["misconception"]),
                )
            else:
                feedback = (
                    "Odgovor nije mogao da se proveri automatski (nema AI kljuca ili poziv nije "
                    "uspeo). Uporedi sam sa tacnim odgovorom ispod."
                )

    if not feedback:
        feedback = question["explanation"]

    attempt_id = db.insert(
        "attempt",
        {
            "question_id": question_id,
            "session_id": session_id,
            "answer": json.dumps(given, ensure_ascii=False),
            "answer_hash": answer_hash,
            "is_correct": 1 if result.is_correct else 0,
            "score": result.score,
            "graded_by": graded_by,
            "feedback": feedback,
            "misconception": misconception,
            "response_ms": int(payload.get("response_ms") or 0),
        },
    )

    progress = scheduler.record(question_id, result.score, aggressiveness)
    if misconception:
        strategy.record_misconception(
            question["category_id"], misconception, topic=question["topic"]
        )

    if session:
        db.execute(
            """
            UPDATE study_session
               SET asked_count = asked_count + 1,
                   correct_count = correct_count + ?
             WHERE id = ?
            """,
            (1 if result.is_correct else 0, session_id),
        )

    return {
        "attempt_id": attempt_id,
        "is_correct": result.is_correct,
        "score": round(result.score, 3),
        "graded_by": graded_by,
        "feedback": feedback,
        "misconception": misconception,
        "correct_text": result.correct_text,
        "explanation": question["explanation"],
        "payload": question["payload"],
        "detail": result.detail,
        "progress": progress,
    }


def skip(session_id: int, question_id: int, reason: str = "skip") -> dict:
    """Preskoci pitanje. `reason` razdvaja 'ne sada' od 'nikad vise'."""
    _session(session_id)
    questions.get(question_id, with_answer=False)
    db.execute(
        """
        INSERT INTO session_skip (session_id, question_id, reason) VALUES (?, ?, ?)
        ON CONFLICT(session_id, question_id) DO UPDATE SET reason = excluded.reason
        """,
        (session_id, question_id, reason[:40]),
    )
    if reason == "ignore_forever":
        questions.set_meta(question_id, {"ignored": True})
    return {"ok": True}


def end(session_id: int) -> dict:
    _session(session_id)
    db.execute(
        "UPDATE study_session SET ended_at = datetime('now') WHERE id = ? AND ended_at IS NULL",
        (session_id,),
    )
    return summary(session_id)


def summary(session_id: int) -> dict:
    session = _session(session_id)
    rows = db.query(
        """
        SELECT a.*, q.stem, q.type, q.topic
          FROM attempt a JOIN question q ON q.id = a.question_id
         WHERE a.session_id = ? ORDER BY a.created_at
        """,
        (session_id,),
    )
    wrong = [row for row in rows if not row["is_correct"]]
    return {
        "session": session,
        "asked": len(rows),
        "correct": sum(1 for row in rows if row["is_correct"]),
        "average_score": round(sum(row["score"] for row in rows) / len(rows), 3) if rows else 0,
        "wrong": [
            {
                "question_id": row["question_id"],
                "stem": row["stem"],
                "type": row["type"],
                "topic": row["topic"],
                "feedback": row["feedback"],
            }
            for row in wrong
        ],
        "by_type": _group(rows, "type"),
        "by_topic": _group(rows, "topic"),
    }


def store_answer_photo(upload, question_id: int) -> str:
    """Slika resenja sa telefona. Vraca putanju koja ide u ocenjivanje."""
    from pathlib import Path

    extension = Path(upload.filename or "").suffix.lower()
    if extension not in config.IMAGE_EXT:
        upload.discard()
        raise HttpError(415, "Dozvoljene su samo slike.")
    if upload.size > 20 * 1024 * 1024:
        upload.discard()
        raise HttpError(413, "Slika je prevelika (max 20 MB).")

    import uuid

    relative = Path("answers") / f"q{question_id}-{uuid.uuid4().hex}{extension}"
    upload.move_to(config.DATA_DIR / relative)
    return relative.as_posix()


def _ask_ai(question: dict, answer_text: str, given: dict) -> Optional[dict]:
    api_key = settings_store.get("gemini_api_key", "")
    if not api_key:
        return None

    photo_path = given.get("photo_path")
    files = None
    if photo_path:
        full = config.DATA_DIR / photo_path
        if full.is_file():
            files = [{"path": str(full), "mime_type": ""}]

    kind = question_types.get(question["type"]).grading
    tier = "strong" if kind == "ai" and photo_path else "standard"

    prompt = prompts.build_grading_prompt(
        question_type=question["type"],
        stem=question["stem"],
        payload=question["payload"],
        answer_text=answer_text,
        language=settings_store.get("ui_language", "sr"),
        has_photo=bool(photo_path),
    )
    try:
        result = ai_models.generate(
            tier,
            prompt,
            api_key=api_key,
            system=prompts.SYSTEM_GRADE,
            files=files,
            json_output=True,
            temperature=0.2,
            max_output_tokens=4096,
            purpose="grade",
            # Student ceka pred ekranom. Foto-postupak sme da razmisli i da
            # traje duze; tekst ne - posle toga je bolje reci "uporedi sam"
            # nego drzati spinner dva minuta kroz cetiri pokusaja.
            thinking="" if photo_path else "low",
            timeout_s=GRADE_TIMEOUT_PHOTO_S if photo_path else GRADE_TIMEOUT_S,
            max_attempts=GRADE_MAX_ATTEMPTS,
        )
    except gemini.AiError:
        # Ocenjivanje ne sme da obori odgovor: pozivalac tada prikaze tacan
        # odgovor i kaze da automatska provera nije uspela.
        return None

    from ..ai import contract

    try:
        payload = json.loads(contract.strip_fence(result["text"]))
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None

    try:
        score = max(0.0, min(1.0, float(payload.get("score", 0))))
    except (TypeError, ValueError):
        score = 0.0
    # Isto pravilo kao za pitanja: objasnjenje ne sme da bude pola-pola.
    script = translit.script_for_language(settings_store.get("ui_language", "sr"))
    return {
        "is_correct": bool(payload.get("is_correct")) and score >= 0.8,
        "score": score,
        "feedback": translit.enforce(str(payload.get("feedback") or "").strip(), script),
        "misconception": translit.enforce(str(payload.get("misconception") or "").strip()[:160], script),
    }


def _session(session_id: int) -> dict:
    row = db.query_one("SELECT * FROM study_session WHERE id = ?", (session_id,))
    if not row:
        raise HttpError(404, "Sesija ne postoji.")
    return row


def _session_categories(session: dict) -> list[int]:
    if session["include_subtree"]:
        return categories.subtree_ids(session["category_id"])
    return [session["category_id"]]


def _group(rows: list[dict], key: str) -> list[dict]:
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = row.get(key) or "(bez oznake)"
        bucket = buckets.setdefault(name, {"name": name, "asked": 0, "correct": 0})
        bucket["asked"] += 1
        bucket["correct"] += 1 if row["is_correct"] else 0
    return sorted(buckets.values(), key=lambda item: item["asked"], reverse=True)
