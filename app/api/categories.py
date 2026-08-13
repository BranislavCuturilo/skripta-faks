"""Rute za stablo kategorija."""

import shutil

from .. import config
from ..http_util import HttpError, Request, Response, json_response
from ..router import router
from ..services import categories


@router.get("/api/categories")
def list_categories(request: Request) -> Response:
    include_archived = request.query.get("archived") == "1"
    return json_response({"ok": True, "tree": categories.tree(include_archived)})


@router.post("/api/categories")
def create_category(request: Request) -> Response:
    data = request.data()
    parent_id = data.get("parent_id")
    node = categories.create(
        name=data.get("name", ""),
        parent_id=int(parent_id) if parent_id else None,
        description=data.get("description", ""),
        study_prompt=data.get("study_prompt", ""),
        color=data.get("color", ""),
    )
    return json_response({"ok": True, "category": node}, status=201)


@router.get("/api/categories/<int:category_id>")
def read_category(request: Request) -> Response:
    category_id = request.params["category_id"]
    node = categories.get(category_id)
    return json_response(
        {
            "ok": True,
            "category": node,
            "breadcrumb": categories.breadcrumb(category_id),
            "effective_prompt": categories.effective_study_prompt(category_id),
            "subtree_ids": categories.subtree_ids(category_id),
        }
    )


@router.patch("/api/categories/<int:category_id>")
def update_category(request: Request) -> Response:
    node = categories.update(request.params["category_id"], request.data())
    return json_response({"ok": True, "category": node})


@router.post("/api/categories/<int:category_id>/move")
def move_category(request: Request) -> Response:
    data = request.data()
    raw_parent = data.get("parent_id")
    parent_id = int(raw_parent) if raw_parent not in (None, "", "null") else None
    node = categories.move(request.params["category_id"], parent_id)
    return json_response({"ok": True, "category": node})


@router.post("/api/categories/<int:category_id>/archive")
def archive_category(request: Request) -> Response:
    archived = str(request.data().get("archived", True)).lower() not in ("0", "false", "ne")
    node = categories.archive(request.params["category_id"], archived)
    return json_response({"ok": True, "category": node})


@router.delete("/api/categories/<int:category_id>")
def delete_category(request: Request) -> Response:
    category_id = request.params["category_id"]
    if request.query.get("confirm") != "1":
        raise HttpError(400, "Brisanje trazi ?confirm=1 - uklanja i sve podkategorije i fajlove.")

    directories = [
        config.MATERIALS_DIR / categories.storage_dirname(child_id)
        for child_id in categories.subtree_ids(category_id)
    ]
    result = categories.delete(category_id)

    for directory in directories:
        if directory.is_dir():
            shutil.rmtree(directory, ignore_errors=True)

    return json_response(
        {"ok": True, "deleted": len(result["deleted_ids"]), "files": len(result["materials"])}
    )
