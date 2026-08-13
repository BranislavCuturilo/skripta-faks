"""Rute za ucenje: sesija, sledece pitanje, odgovor, preskakanje, rezime."""

from .. import db
from ..http_util import HttpError, Request, Response, json_response
from ..quiz import scheduler
from ..router import router
from ..services import categories, settings_store, study


@router.post("/api/study/start")
def start_session(request: Request) -> Response:
    data = request.data()
    category_id = data.get("category_id")
    if not category_id:
        raise HttpError(400, "Nedostaje category_id.")
    return json_response({"ok": True, **study.start(int(category_id), data)})


@router.get("/api/study/<int:session_id>/next")
def next_question(request: Request) -> Response:
    return json_response({"ok": True, **study.next_question(request.params["session_id"])})


@router.post("/api/study/<int:session_id>/answer")
def answer_in_session(request: Request) -> Response:
    data = request.data()
    question_id = data.get("question_id")
    if not question_id:
        raise HttpError(400, "Nedostaje question_id.")
    result = study.answer(request.params["session_id"], int(question_id), data)
    return json_response({"ok": True, **result})


@router.post("/api/questions/<int:question_id>/answer")
def answer_standalone(request: Request) -> Response:
    """Odgovor van sesije - kad se pitanje otvori iz liste radi provere."""
    result = study.answer(None, request.params["question_id"], request.data())
    return json_response({"ok": True, **result})


@router.post("/api/study/<int:session_id>/skip")
def skip_question(request: Request) -> Response:
    data = request.data()
    question_id = data.get("question_id")
    if not question_id:
        raise HttpError(400, "Nedostaje question_id.")
    reason = str(data.get("reason") or "skip")
    if reason not in ("skip", "ignore_session", "ignore_forever"):
        raise HttpError(400, "Nepoznat razlog preskakanja.")
    return json_response(
        {"ok": True, **study.skip(request.params["session_id"], int(question_id), reason)}
    )


@router.post("/api/study/<int:session_id>/end")
def end_session(request: Request) -> Response:
    return json_response({"ok": True, "summary": study.end(request.params["session_id"])})


@router.get("/api/study/<int:session_id>/summary")
def session_summary(request: Request) -> Response:
    return json_response({"ok": True, "summary": study.summary(request.params["session_id"])})


@router.post("/api/study/photo/<int:question_id>")
def upload_answer_photo(request: Request) -> Response:
    """Slika resenja sa telefona - localhost je dostupan na LAN-u pa ovo radi."""
    upload = request.file("photo") or (request.files[0] if request.files else None)
    if not upload:
        raise HttpError(400, "Nema poslate slike.")
    path = study.store_answer_photo(upload, request.params["question_id"])
    request.files = [item for item in request.files if item is not upload]
    return json_response({"ok": True, "photo_path": path, "url": f"/media/{path}"})


@router.get("/api/categories/<int:category_id>/stats")
def category_stats(request: Request) -> Response:
    category_id = request.params["category_id"]
    include_subtree = request.query.get("subtree", "1") == "1"
    ids = categories.subtree_ids(category_id) if include_subtree else [category_id]
    aggressiveness = int(request.query.get("aggressiveness")
                         or settings_store.get("aggressiveness", 3))
    return json_response(
        {
            "ok": True,
            "stats": scheduler.stats(ids, aggressiveness),
            "recent_sessions": _recent_sessions(ids),
            "activity": _activity(ids),
        }
    )


def _recent_sessions(category_ids: list[int], limit: int = 10) -> list[dict]:
    marks = ", ".join("?" for _ in category_ids)
    return db.query(
        f"""
        SELECT * FROM study_session WHERE category_id IN ({marks})
        ORDER BY started_at DESC LIMIT ?
        """,
        [*category_ids, limit],
    )


def _activity(category_ids: list[int], days: int = 30) -> list[dict]:
    marks = ", ".join("?" for _ in category_ids)
    return db.query(
        f"""
        SELECT date(a.created_at) AS day,
               COUNT(*) AS asked,
               SUM(a.is_correct) AS correct,
               ROUND(AVG(a.score), 3) AS average_score
          FROM attempt a JOIN question q ON q.id = a.question_id
         WHERE q.category_id IN ({marks})
           AND a.created_at >= datetime('now', ?)
         GROUP BY day ORDER BY day
        """,
        [*category_ids, f"-{days} days"],
    )
