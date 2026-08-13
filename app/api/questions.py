"""Rute za pitanja: pregled, izmena, beleske i flagovi."""

from ..http_util import Request, Response, json_response
from ..router import router
from ..services import categories, questions


@router.get("/api/categories/<int:category_id>/questions")
def list_questions(request: Request) -> Response:
    category_id = request.params["category_id"]
    query = request.query
    ids = (
        categories.subtree_ids(category_id)
        if query.get("subtree", "1") == "1"
        else [category_id]
    )
    result = questions.list_for(
        ids,
        search=query.get("q", ""),
        question_type=query.get("type", ""),
        flag=query.get("flag", ""),
        include_deleted=query.get("deleted") == "1",
        include_ignored=query.get("ignored", "1") == "1",
        limit=max(1, min(500, int(query.get("limit") or 100))),
        offset=max(0, int(query.get("offset") or 0)),
    )
    return json_response(
        {"ok": True, **result, "type_counts": questions.type_counts(ids)}
    )


@router.get("/api/questions/<int:question_id>")
def read_question(request: Request) -> Response:
    question_id = request.params["question_id"]
    return json_response(
        {
            "ok": True,
            "question": questions.get(question_id),
            "variants": questions.variants_of(question_id),
        }
    )


@router.patch("/api/questions/<int:question_id>")
def edit_question(request: Request) -> Response:
    row = questions.edit(request.params["question_id"], request.data())
    return json_response({"ok": True, "question": row})


@router.post("/api/questions/<int:question_id>/meta")
def set_question_meta(request: Request) -> Response:
    """Beleska i flagovi: proveriti, provera u fajlu, nebitno, ignorisi, obrisi."""
    row = questions.set_meta(request.params["question_id"], request.data())
    return json_response({"ok": True, "question": row})


@router.delete("/api/questions/<int:question_id>")
def purge_question(request: Request) -> Response:
    questions.purge(request.params["question_id"])
    return json_response({"ok": True})
