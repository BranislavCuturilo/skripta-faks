"""Rute za predloge nadogradnje aplikacije."""

from .. import config
from ..http_util import HttpError, Request, Response, json_response
from ..router import router
from ..services import jobs, proposals


@router.get("/api/proposals")
def list_proposals(request: Request) -> Response:
    return json_response(
        {
            "ok": True,
            "proposals": proposals.list_all(),
            "context_ready": config.CONTEXT_FILE.is_file(),
            "folder": str(config.PROPOSALS_DIR),
        }
    )


@router.post("/api/proposals")
def create_proposal(request: Request) -> Response:
    """Poziv modelu traje i po pola minuta, pa ide u posao u pozadini."""
    text = str(request.data().get("request") or "").strip()
    if len(text) < 15:
        raise HttpError(400, "Opiši malo detaljnije šta ti fali — bar rečenicu-dve.")

    job = jobs.start(
        "proposal",
        "Pišem predlog nadogradnje",
        lambda handle: _write(handle, text),
    )
    return json_response({"ok": True, "job": job}, status=202)


def _write(job, text: str) -> dict:
    job.progress(0, 2, "Čitam mapu projekta...")
    proposals.context_text()
    job.progress(1, 2, "Model razmišlja o izmeni...")
    result = proposals.create(text)
    job.progress(2, 2, "Predlog je zapisan.")
    return result


@router.post("/api/proposals/manual")
def create_manual_proposal(request: Request) -> Response:
    data = request.data()
    return json_response(
        {"ok": True, **proposals.create_manual(data.get("title", ""), data.get("body", ""))},
        status=201,
    )


@router.get("/api/proposals/context")
def read_context(request: Request) -> Response:
    return json_response(
        {
            "ok": True,
            "text": proposals.context_text(),
            "path": str(config.CONTEXT_FILE),
        }
    )


@router.post("/api/proposals/context/refresh")
def refresh_context(request: Request) -> Response:
    if not proposals.regenerate_context():
        raise HttpError(
            500,
            "Mapa nije mogla da se izgradi. Pokreni `python mapa.py` u folderu aplikacije "
            "i pogledaj šta piše.",
        )
    return json_response({"ok": True, "text": proposals.context_text()})


@router.get("/api/proposals/<str:slug>")
def read_proposal(request: Request) -> Response:
    return json_response({"ok": True, **proposals.read(request.params["slug"])})


@router.delete("/api/proposals/<str:slug>")
def delete_proposal(request: Request) -> Response:
    proposals.delete(request.params["slug"])
    return json_response({"ok": True})
