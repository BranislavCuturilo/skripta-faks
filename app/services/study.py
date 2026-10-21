"""Sesija ucenja: izbor pitanja, ocenjivanje, objasnjenja.

Objasnjenje se placa AI pozivom samo kad mora. Kod ponudjenih odgovora vec
postoji napisano objasnjenje iz generisanja. Kod dopune recenice, kratkog i
duzeg odgovora ga nema unapred - tada ocenjuje model, i ocena se upisuje u
`explanation_cache`, pa isti pogresan odgovor drugi put ne kosta nista.

U sesiji se model NE zove posle svakog takvog odgovora. Odgovor se sacuva kao
`graded_by = 'pending'`, korisnik ide dalje, a `review` na kraju ocenjuje sve
koji cekaju jednim pozivom i uz to pise zakljucak o celoj sesiji. Poziv po
odgovoru je kostao kvotu i pucao usred ucenja; jedan poziv na kraju moze da
padne samo jednom, i tada odgovori i dalje cekaju - nista se ne gubi.
"""

import hashlib
import json
import threading
from typing import Any, Optional

from .. import config, db, translit
from ..ai import contract, gemini, prompts
from ..http_util import HttpError
from ..quiz import grading, scheduler
from ..quiz import types as question_types
from . import ai_models, categories, questions, settings_store, strategy

GRADE_TIMEOUT_S = 30.0
GRADE_TIMEOUT_PHOTO_S = 90.0
GRADE_MAX_ATTEMPTS = 2

# Pregled sesije nosi sve odgovore i izvod iz skripte, pa sme duze od ocene
# jednog odgovora - ali student i dalje ceka na rezimeu, ne u pozadini.
REVIEW_TIMEOUT_S = 120.0
REVIEW_TIMEOUT_PHOTO_S = 180.0
REVIEW_MAX_ATTEMPTS = 2

# Sesije koje model upravo pregleda. Dupli klik ili dva taba ne smeju da oba
# ocene iste odgovore - raspored bi tada upisao isti odgovor dvaput.
_reviewing: set[int] = set()
_review_lock = threading.Lock()


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
    """Oceni odgovor. Lokalno kad god moze; AI u sesiji tek na kraju, van nje odmah."""
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
        elif session:
            # Ne zove se model sada: odgovor ceka da ga `review` oceni zajedno
            # sa ostalima iz sesije, jednim pozivom.
            graded_by = grading.PENDING
        else:
            verdict = _ask_ai(question, answer_text, given)
            if verdict is not None:
                result.is_correct = verdict["is_correct"]
                result.score = verdict["score"]
                feedback = verdict["feedback"]
                misconception = verdict["misconception"]
                graded_by = "ai"
                _remember(question_id, answer_hash, verdict)
            else:
                feedback = (
                    "Odgovor nije mogao da se proveri automatski (nema AI kljuca ili poziv nije "
                    "uspeo). Uporedi sam sa tacnim odgovorom ispod."
                )

    pending = graded_by == grading.PENDING
    if not feedback and not pending:
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

    # Odgovor koji ceka jos nema ocenu - raspored se upisuje tek kad je dobije,
    # inace bi svaki tekstualni odgovor prvo bio kaznjen kao netacan.
    progress = {} if pending else scheduler.record(question_id, result.score, aggressiveness)
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
        "pending": pending,
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
    """Rezime sesije: tabela svih odgovora, ono sto ceka ocenu, i AI zakljucak."""
    session = _session(session_id)
    rows = _session_attempts(session_id)
    graded = [row for row in rows if row["graded_by"] != grading.PENDING]
    wrong = [row for row in graded if not row["is_correct"]]
    return {
        "session": session,
        "asked": len(rows),
        "correct": sum(1 for row in graded if row["is_correct"]),
        "pending": len(rows) - len(graded),
        "average_score": round(sum(row["score"] for row in graded) / len(graded), 3) if graded else 0,
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
        "answers": [
            {
                "question_id": row["question_id"],
                "stem": row["stem"],
                "type": row["type"],
                "topic": row["topic"],
                "answer_text": row["answer_text"],
                "correct_text": row["correct_text"],
                "is_correct": bool(row["is_correct"]),
                "score": round(row["score"], 3),
                "graded_by": row["graded_by"],
                "feedback": row["feedback"],
                "misconception": row["misconception"],
                "note": row["note"],
            }
            for row in rows
        ],
        "review": db.json_field(session, "review", None) or None,
        "by_type": _group(graded, "type"),
        "by_topic": _group(graded, "topic"),
    }


def review(session_id: int) -> dict:
    """AI pregled sesije: svi odgovori koji cekaju, jednim pozivom, plus zakljucak.

    Ponovni poziv je bezbedan: ocenjuje samo ono sto i dalje ceka, a kad nista
    ne ceka i zakljucak vec postoji, vraca rezime bez ijednog poziva.
    """
    _session(session_id)
    with _review_lock:
        if session_id in _reviewing:
            raise HttpError(409, "AI već pregleda ovu sesiju — sačekaj da završi.")
        _reviewing.add(session_id)
    try:
        _review(session_id)
    finally:
        with _review_lock:
            _reviewing.discard(session_id)
    return summary(session_id)


def _review(session_id: int) -> None:
    session = _session(session_id)
    rows = _session_attempts(session_id)
    if not rows:
        raise HttpError(400, "U ovoj sesiji još nema odgovora za pregled.")
    pending = [row for row in rows if row["graded_by"] == grading.PENDING]
    if not pending and session["review"]:
        return

    api_key = settings_store.get("gemini_api_key", "")
    if not api_key:
        raise HttpError(
            400,
            "Nije unet AI ključ (Podešavanja → AI). Odgovori su sačuvani i čekaju ocenu.",
        )

    items = []
    files = []
    for number, row in enumerate(pending, start=1):
        photo = 0
        photo_path = row["answer"].get("photo_path")
        if photo_path and (config.DATA_DIR / photo_path).is_file():
            files.append({"path": str(config.DATA_DIR / photo_path), "mime_type": ""})
            photo = len(files)
        items.append({
            "n": number,
            "row": row,
            "type": row["type"],
            "stem": row["stem"],
            "payload": row["payload"],
            "answer_text": row["answer_text"],
            "photo": photo,
        })

    prompt = prompts.build_review_prompt(
        category_path=" / ".join(
            node["name"] for node in categories.breadcrumb(session["category_id"])
        ),
        pending=items,
        graded=[row for row in rows if row["graded_by"] != grading.PENDING],
        material=_review_material([row["question_id"] for row in pending]),
        language=settings_store.get("ui_language", "sr"),
    )
    try:
        result = ai_models.generate(
            "strong" if files else "standard",
            prompt,
            api_key=api_key,
            system=prompts.SYSTEM_REVIEW,
            files=files or None,
            json_output=True,
            temperature=0.2,
            purpose="review",
            # Isto pravilo kao `_ask_ai`: tekst sa malo razmisljanja, postupak
            # sa slike normalno. Izlaz ostaje na podrazumevanom velikom
            # budzetu - ocena dvadeset odgovora ne sme da bude odsecena.
            thinking="" if files else "low",
            timeout_s=REVIEW_TIMEOUT_PHOTO_S if files else REVIEW_TIMEOUT_S,
            max_attempts=REVIEW_MAX_ATTEMPTS,
        )
    except gemini.AiError as exc:
        raise HttpError(502, f"{exc.message} Odgovori su sačuvani i čekaju — pokušaj ponovo.") from None

    data = _parse_review(result["text"])
    verdicts: dict[int, dict] = {}
    for raw in data.get("results") or []:
        if not isinstance(raw, dict):
            continue
        try:
            verdicts[int(raw.get("n"))] = raw
        except (TypeError, ValueError):
            continue

    # Svaki odgovor u svojoj transakciji: ocena, kes, raspored i brojac idu
    # zajedno. Odgovor koji model preskoci ostaje da ceka sledeci pregled.
    for item in items:
        raw = verdicts.get(item["n"])
        if raw is not None:
            with db.transaction():
                _apply_review(session, item["row"], _verdict(raw))

    conclusion = _conclusion(data, result.get("model", ""))
    if conclusion:
        db.execute(
            "UPDATE study_session SET review = ? WHERE id = ?",
            (json.dumps(conclusion, ensure_ascii=False), session_id),
        )


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

    try:
        payload = json.loads(contract.strip_fence(result["text"]))
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    return _verdict(payload)


def _verdict(payload: dict) -> dict:
    """Ocena modela -> oblik koji se upisuje. Isto za jedan odgovor i za pregled sesije."""
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


def _remember(question_id: int, answer_hash: str, verdict: dict) -> None:
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


def _apply_review(session: dict, row: dict, verdict: dict) -> None:
    """Upisi ocenu odgovora koji je cekao - sve sto `answer` tada nije uradio."""
    db.execute(
        """
        UPDATE attempt
           SET is_correct = ?, score = ?, graded_by = 'ai', feedback = ?, misconception = ?
         WHERE id = ? AND graded_by = ?
        """,
        (1 if verdict["is_correct"] else 0, verdict["score"],
         verdict["feedback"] or row["explanation"], verdict["misconception"],
         row["id"], grading.PENDING),
    )
    _remember(row["question_id"], row["answer_hash"], verdict)
    scheduler.record(row["question_id"], verdict["score"], session["aggressiveness"])
    if verdict["misconception"]:
        strategy.record_misconception(
            row["category_id"], verdict["misconception"], topic=row["topic"]
        )
    if verdict["is_correct"]:
        db.execute(
            "UPDATE study_session SET correct_count = correct_count + 1 WHERE id = ?",
            (session["id"],),
        )


def _parse_review(text: str) -> dict:
    unreadable = HttpError(
        502,
        "AI je vratio odgovor koji ne može da se pročita. Odgovori su sačuvani i čekaju — "
        "pokušaj ponovo.",
    )
    cleaned = contract.strip_fence(text)
    try:
        data = json.loads(cleaned)
    except ValueError:
        # Odsecen odgovor: cele ocene se spasavaju, zakljucak je izgubljen.
        try:
            return {"results": contract.salvage_objects(cleaned)}
        except contract.ContractError:
            raise unreadable from None
    if not isinstance(data, dict):
        raise unreadable
    return data


def _conclusion(data: dict, model: str) -> dict:
    """Zakljucak sesije iz odgovora modela; prazan dict kad ga model nije dao."""
    script = translit.script_for_language(settings_store.get("ui_language", "sr"))

    def lines(key: str) -> list[str]:
        raw = data.get(key)
        if not isinstance(raw, list):
            return []
        return [translit.enforce(str(item).strip(), script) for item in raw if str(item).strip()][:8]

    content = {
        "conclusion": translit.enforce(str(data.get("conclusion") or "").strip(), script),
        "strengths": lines("strengths"),
        "gaps": lines("gaps"),
        "next_steps": lines("next_steps"),
    }
    if not any(content.values()):
        return {}
    return {**content, "model": model, "created_at": db.scalar("SELECT datetime('now')")}


def _review_material(question_ids: list[int]) -> str:
    """Izvod iz skripte iz kog su ova pitanja pravljena - merilo za ocenu.

    Isti komadi koji su otisli modelu pri generisanju, pa ovo ne salje napolje
    nista sto vec nije poslato. Pitanje bez generisanja (ispitna baza) nema
    izvod i ocenjuje se po ocekivanom odgovoru.
    """
    if not question_ids:
        return ""
    marks = ", ".join("?" for _ in question_ids)
    runs = db.query(
        f"""
        SELECT DISTINCT r.chunk_ids
          FROM question q JOIN generation_run r ON r.id = q.generation_run_id
         WHERE q.id IN ({marks})
        """,
        question_ids,
    )
    chunk_ids = sorted({int(item) for run in runs for item in db.json_field(run, "chunk_ids", [])})
    if not chunk_ids:
        return ""

    rows = db.query(
        f"""
        SELECT c.label, c.text, m.filename
          FROM material_chunk c JOIN material m ON m.id = c.material_id
         WHERE c.id IN ({", ".join("?" for _ in chunk_ids)})
         ORDER BY c.material_id, c.ordinal
        """,
        chunk_ids,
    )
    budget = int(settings_store.get("batch_char_budget", 60000) or 60000)
    pieces: list[str] = []
    used = 0
    for row in rows:
        source = row["filename"] + (f" - {row['label']}" if row["label"] else "")
        block = f"[{source}]\n{row['text']}"
        if used + len(block) > budget:
            break
        pieces.append(block)
        used += len(block)
    return "\n\n".join(pieces)


def _session_attempts(session_id: int) -> list[dict]:
    """Svi odgovori sesije redom, sa pitanjem, tekstom odgovora i tacnim odgovorom."""
    rows = db.query(
        """
        SELECT a.*, q.stem, q.type, q.topic, q.explanation, q.category_id,
               q.payload AS question_payload, COALESCE(m.note, '') AS note
          FROM attempt a
          JOIN question q ON q.id = a.question_id
          LEFT JOIN question_meta m ON m.question_id = q.id
         WHERE a.session_id = ?
         ORDER BY a.created_at, a.id
        """,
        (session_id,),
    )
    for row in rows:
        row["payload"] = db.json_field(row, "question_payload")
        row["answer"] = db.json_field(row, "answer")
        row["correct_text"] = grading.correct_answer_text(row["type"], row["payload"])
        try:
            row["answer_text"] = grading.describe_answer(row["type"], row["payload"], row["answer"])
        except (KeyError, IndexError, TypeError, ValueError):
            # Pitanje je posle odgovora prepravljeno (manje ponudjenih...) -
            # odgovor se vise ne da procitati, ali red u tabeli ostaje.
            row["answer_text"] = ""
    return rows


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
