"""Rute za podesavanja, ukljucujuci unos i proveru AI kljuca."""

from ..http_util import HttpError, Request, Response, json_response
from ..router import router
from ..services import ai_models, settings_store


@router.get("/api/settings")
def read_settings(request: Request) -> Response:
    return json_response({"ok": True, "settings": settings_store.public_settings()})


@router.patch("/api/settings")
def write_settings(request: Request) -> Response:
    data = request.data()
    if not isinstance(data, dict) or not data:
        raise HttpError(400, "Nema nicega za izmenu.")
    settings_store.set_many(data)
    return json_response({"ok": True, "settings": settings_store.public_settings()})


@router.delete("/api/settings/api-key")
def delete_api_key(request: Request) -> Response:
    settings_store.set_value("gemini_api_key", "")
    return json_response({"ok": True, "settings": settings_store.public_settings()})


@router.post("/api/settings/test-key")
def test_api_key(request: Request) -> Response:
    """Proba kljuc jednim najjeftinijim pozivom, da korisnik ne otkrije problem
    tek usred generisanja."""
    from ..ai import gemini

    data = request.data()
    key = (data.get("gemini_api_key") or "").strip() or settings_store.get("gemini_api_key", "")
    if not key:
        raise HttpError(400, "Nema unetog API kljuca.")

    result = gemini.probe(key)
    if not result["ok"]:
        return json_response({"ok": False, **result})

    if data.get("save"):
        settings_store.set_value("gemini_api_key", key)
        # Odmah razresi modele: bez ovoga bi prvi pravi poziv otisao na naziv
        # koji ovaj kljuc mozda uopste nema.
        report = ai_models.refresh(key)
        return json_response({"ok": True, **result, "models_refreshed": report.get("ok", False),
                              "changes": report.get("changes", []),
                              "status": ai_models.status()})

    return json_response({"ok": True, **result})
