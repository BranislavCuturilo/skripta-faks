"""Rute za materijale: upload, obrada, pregled."""

from ..http_util import HttpError, Request, Response, json_response
from ..router import router
from ..services import categories, jobs, materials


@router.get("/api/categories/<int:category_id>/materials")
def list_materials(request: Request) -> Response:
    include_subtree = request.query.get("subtree") == "1"
    rows = materials.list_for(request.params["category_id"], include_subtree)
    return json_response({"ok": True, "materials": rows})


@router.post("/api/categories/<int:category_id>/materials")
def upload_materials(request: Request) -> Response:
    """Prima vise fajlova odjednom. Ekstrakcija ide u posao u pozadini - velika
    skripta se cita nekoliko sekundi i browser to ne treba da ceka."""
    category_id = request.params["category_id"]
    categories.get(category_id)

    if not request.files:
        raise HttpError(400, "Nema poslatih fajlova.")

    note = request.form.get("note", "")
    stored: list[dict] = []
    duplicates: list[dict] = []
    failures: list[dict] = []

    for upload in list(request.files):
        try:
            row = materials.store_upload(category_id, upload, note)
        except HttpError as exc:
            failures.append({"filename": upload.filename, "error": exc.message})
            continue
        (duplicates if row.get("duplicate") else stored).append(row)

    # store_upload je fajlove ili premestio ili odbacio; nema sta da se cisti.
    request.files = []

    pending = [row["id"] for row in stored]
    job = None
    if pending:
        job = jobs.start(
            "extract",
            f"Obrada {len(pending)} fajl(ova)",
            lambda handle: _process_all(handle, pending),
        )

    return json_response(
        {
            "ok": True,
            "stored": stored,
            "duplicates": duplicates,
            "failures": failures,
            "job": job,
        },
        status=201 if stored else 200,
    )


def _process_all(job, material_ids: list[int]) -> dict:
    done: list[dict] = []
    for index, material_id in enumerate(material_ids, start=1):
        if job.cancelled:
            break
        row = materials.get(material_id)
        job.progress(index - 1, len(material_ids), f"Citam: {row['filename']}")
        processed = materials.process(material_id)
        done.append(
            {
                "id": processed["id"],
                "filename": processed["filename"],
                "status": processed["extraction_status"],
                "method": processed["extraction_method"],
                "chars": processed["char_count"],
                "note": processed["extraction_note"],
            }
        )
    job.progress(len(material_ids), len(material_ids), "Obrada zavrsena.")
    return {"processed": done}


@router.get("/api/materials/<int:material_id>")
def read_material(request: Request) -> Response:
    material_id = request.params["material_id"]
    return json_response(
        {
            "ok": True,
            "material": materials.get(material_id),
            "outline": materials.outline_for(material_id),
            "preview": materials.preview(material_id),
        }
    )


@router.patch("/api/materials/<int:material_id>")
def update_material(request: Request) -> Response:
    row = materials.update_meta(request.params["material_id"], request.data())
    return json_response({"ok": True, "material": row})


@router.post("/api/materials/<int:material_id>/reprocess")
def reprocess_material(request: Request) -> Response:
    row = materials.process(request.params["material_id"])
    return json_response({"ok": True, "material": row})


@router.delete("/api/materials/<int:material_id>")
def delete_material(request: Request) -> Response:
    materials.delete(request.params["material_id"])
    return json_response({"ok": True})
