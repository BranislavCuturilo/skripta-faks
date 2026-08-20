"""Rute za samo-azuriranje aplikacije."""

from ..http_util import HttpError, Request, Response, json_response
from ..router import router
from ..services import jobs, updater


@router.get("/api/update/check")
def check(request: Request) -> Response:
    return json_response({"ok": True, "update": updater.check()})


@router.post("/api/update/download")
def download(request: Request) -> Response:
    """Preuzimanje ide kao posao u pozadini: ZIP je nekoliko megabajta, a na
    slaboj vezi bi jedan zahtev istekao pre kraja."""
    data = request.data()
    version = (data.get("version") or "").strip()
    url = (data.get("url") or "").strip()
    if not url:
        state = updater.check()
        version, url = state.get("latest") or "", state.get("download") or ""
    if not url:
        raise HttpError(400, "Nema adrese sa koje bi se skinula nova verzija.")

    def work(job: jobs.Job) -> dict:
        def progress(done: int, total: int) -> None:
            job.progress(done, total, f"Preuzeto {done // 1024} KB")

        job.log("Preuzimam novu verziju...")
        info = updater.prepare(version, url, progress)
        job.log("Spremno. Ugradnja ide pri sledecem pokretanju.")
        return info

    return json_response({"ok": True, "job": jobs.start("update", "Preuzimanje nove verzije", work)})


@router.post("/api/update/cancel")
def cancel(request: Request) -> Response:
    updater.discard()
    return json_response({"ok": True, "update": updater.check()})
