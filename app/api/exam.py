"""Rute za doslovan uvoz ispitnih pitanja (fiksna lista sa fakulteta)."""

from ..http_util import Request, Response, json_response
from ..router import router
from ..services import exam_import, jobs


@router.post("/api/categories/<int:category_id>/exam/preview")
def exam_preview(request: Request) -> Response:
    """Sta bi parser prepoznao - bez upisa, da korisnik vidi pre nego sto uveze."""
    return json_response(
        {"ok": True, **exam_import.preview(request.params["category_id"], request.data())}
    )


@router.post("/api/categories/<int:category_id>/exam/import")
def exam_import_questions(request: Request) -> Response:
    """mode=local: parser, odmah. mode=ai: Gemini prepis, posao u pozadini."""
    category_id = request.params["category_id"]
    options = request.data()
    if str(options.get("mode") or "local") == "ai":
        job = jobs.start(
            "exam_import",
            "Doslovan prepis ispitnih pitanja",
            lambda handle: exam_import.import_ai(category_id, options, handle),
        )
        return json_response({"ok": True, "job": job}, status=202)
    return json_response({"ok": True, **exam_import.import_local(category_id, options)})
