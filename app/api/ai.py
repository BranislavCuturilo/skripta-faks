"""Rute za AI: generisanje, poslovi, strategija, dopune, izgovor."""

from .. import db
from ..ai import gemini, tts
from ..http_util import HttpError, Request, Response, json_response
from ..router import router
from ..services import generation, jobs, notes, settings_store, strategy


# ----------------------------------------------------------------- generisanje


@router.post("/api/categories/<int:category_id>/generate/plan")
def generation_plan(request: Request) -> Response:
    return json_response(
        {"ok": True, "plan": generation.plan(request.params["category_id"], request.data())}
    )


@router.post("/api/categories/<int:category_id>/generate")
def generate_questions(request: Request) -> Response:
    """Pokrece posao u pozadini - vise poziva modelu traje minutima."""
    category_id = request.params["category_id"]
    options = request.data()
    plan = generation.plan(category_id, options)
    if not plan["total_calls"]:
        raise HttpError(400, "Nema materijala za generisanje. Prvo uploaduj fajlove.")

    job = jobs.start(
        "generate",
        f"Generisanje pitanja ({plan['total_calls']} poziva)",
        lambda handle: generation.run(category_id, options, handle),
    )
    return json_response({"ok": True, "job": job, "plan": plan}, status=202)


@router.post("/api/categories/<int:category_id>/generate/export")
def export_generation_prompt(request: Request) -> Response:
    """Prompt kao tekst - za Claude ili bilo koji drugi model."""
    return json_response(
        {"ok": True, **generation.export_prompt(request.params["category_id"], request.data())}
    )


@router.post("/api/categories/<int:category_id>/generate/import")
def import_generated(request: Request) -> Response:
    data = request.data()
    raw = data.get("text") or data.get("raw") or ""
    return json_response(
        {"ok": True, **generation.import_manual(request.params["category_id"], raw)}
    )


@router.get("/api/categories/<int:category_id>/runs")
def list_runs(request: Request) -> Response:
    rows = db.query(
        """
        SELECT id, provider, model, source_kind, status, requested_count, produced_count,
               rejected_count, duplicate_count, prompt_tokens, output_tokens, error,
               created_at, finished_at
          FROM generation_run WHERE category_id = ?
         ORDER BY created_at DESC LIMIT 50
        """,
        (request.params["category_id"],),
    )
    return json_response({"ok": True, "runs": rows})


# ---------------------------------------------------------------------- poslovi


@router.get("/api/jobs")
def list_jobs(request: Request) -> Response:
    return json_response({"ok": True, "jobs": jobs.listing()})


@router.get("/api/jobs/<str:job_id>")
def read_job(request: Request) -> Response:
    record = jobs.snapshot(request.params["job_id"])
    if not record:
        raise HttpError(404, "Posao ne postoji ili je istekao.")
    return json_response({"ok": True, "job": record})


@router.post("/api/jobs/<str:job_id>/cancel")
def cancel_job(request: Request) -> Response:
    return json_response({"ok": jobs.cancel(request.params["job_id"])})


# -------------------------------------------------------------------- strategija


@router.get("/api/categories/<int:category_id>/strategy")
def read_strategy(request: Request) -> Response:
    category_id = request.params["category_id"]
    return json_response(
        {
            "ok": True,
            "active": strategy.active(category_id),
            "history": strategy.history(category_id),
            "evidence": strategy.evidence(category_id),
            "misconceptions": strategy.misconceptions(category_id),
        }
    )


@router.post("/api/categories/<int:category_id>/strategy/refresh")
def refresh_strategy(request: Request) -> Response:
    return json_response({"ok": True, **strategy.refresh(request.params["category_id"])})


@router.post("/api/categories/<int:category_id>/strategy")
def write_strategy(request: Request) -> Response:
    """Rucna izmena strategije - korisnik uvek sme da pregazi predlog modela."""
    data = request.data()
    saved = strategy.save(
        request.params["category_id"],
        strategy.KIND_GENERATION,
        data.get("content") or {},
        rationale=str(data.get("rationale") or "Rucna izmena."),
        author="user",
    )
    return json_response({"ok": True, "strategy": saved})


@router.post("/api/strategy/<int:strategy_id>/revert")
def revert_strategy(request: Request) -> Response:
    return json_response({"ok": True, "strategy": strategy.revert(request.params["strategy_id"])})


@router.post("/api/misconceptions/<int:misconception_id>/resolve")
def resolve_misconception(request: Request) -> Response:
    resolved = str(request.data().get("resolved", True)).lower() not in ("0", "false", "ne")
    strategy.resolve_misconception(request.params["misconception_id"], resolved)
    return json_response({"ok": True})


# ------------------------------------------------------------------------ dopune


@router.get("/api/categories/<int:category_id>/notes")
def list_notes(request: Request) -> Response:
    return json_response({"ok": True, "notes": notes.list_for(request.params["category_id"])})


@router.post("/api/categories/<int:category_id>/notes")
def create_note(request: Request) -> Response:
    data = request.data()
    row = notes.create_manual(
        request.params["category_id"], data.get("title", ""), data.get("body", "")
    )
    return json_response({"ok": True, "note": row}, status=201)


@router.post("/api/categories/<int:category_id>/notes/generate")
def generate_note(request: Request) -> Response:
    gaps = request.data().get("gaps") or []
    return json_response({"ok": True, **notes.generate(request.params["category_id"], gaps)})


@router.delete("/api/notes/<int:note_id>")
def delete_note(request: Request) -> Response:
    notes.delete(request.params["note_id"])
    return json_response({"ok": True})


# ------------------------------------------------------------------------ modeli


@router.get("/api/models")
def list_models(request: Request) -> Response:
    api_key = settings_store.get("gemini_api_key", "")
    if not api_key:
        return json_response({"ok": False, "error": "Nije unet API kljuc.", "models": []})
    return json_response(gemini.probe(api_key))


@router.get("/api/ai/usage")
def ai_usage(request: Request) -> Response:
    return json_response(
        {
            "ok": True,
            "recent": db.query(
                """
                SELECT purpose, model, ok, http_status, duration_ms, prompt_chars,
                       prompt_tokens, output_tokens, error, created_at
                  FROM ai_call_log ORDER BY created_at DESC LIMIT 100
                """
            ),
            "totals": db.query(
                """
                SELECT purpose,
                       COUNT(*) AS calls,
                       SUM(ok) AS succeeded,
                       SUM(COALESCE(prompt_tokens, 0)) AS prompt_tokens,
                       SUM(COALESCE(output_tokens, 0)) AS output_tokens
                  FROM ai_call_log GROUP BY purpose ORDER BY calls DESC
                """
            ),
        }
    )


# ------------------------------------------------------------------------ izgovor


@router.get("/api/tts/voices")
def tts_voices(request: Request) -> Response:
    return json_response({"ok": True, "voices": tts.list_voices("")})


@router.post("/api/tts")
def speak(request: Request) -> Response:
    """Vrati WAV (Gemini glas) ili izgovori na zvucniku racunara (Windows)."""
    data = request.data()
    text = str(data.get("text") or "").strip()
    if not text:
        raise HttpError(400, "Nema teksta za izgovor.")

    engine = str(data.get("engine") or settings_store.get("tts_engine", "browser"))
    try:
        if engine == "windows":
            tts.speak_on_host(text, int(data.get("rate") or 0))
            return json_response({"ok": True, "engine": "windows"})

        audio = tts.synthesize(
            settings_store.get("gemini_api_key", ""),
            text,
            voice=str(data.get("voice") or settings_store.get("tts_voice", "")),
        )
    except gemini.AiError as exc:
        raise HttpError(502, exc.message) from None

    return Response(
        status=200,
        headers={
            "Content-Type": "audio/wav",
            "Content-Length": str(len(audio)),
            "Cache-Control": "no-store",
        },
        body=audio,
    )
