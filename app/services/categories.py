"""Kategorije: samo-referentno stablo bez ogranicenja dubine.

Predmet je kategorija, kolokvijum je podkategorija, oblast unutar kolokvijuma je
opet podkategorija - u nedogled. Ucenje na cvoru podrazumeva ceo podstablo ispod
njega, pa "Matematika 2" ispituje i iz svih kolokvijuma.
"""

import re
import unicodedata
from typing import Any, Optional

from .. import db
from ..http_util import HttpError

_TRANSLIT = {
    "č": "c", "ć": "c", "š": "s", "ž": "z", "đ": "dj",
    "Č": "C", "Ć": "C", "Š": "S", "Ž": "Z", "Đ": "Dj",
}


def slugify(value: str) -> str:
    for source, target in _TRANSLIT.items():
        value = value.replace(source, target)
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return value or "kategorija"


def get(category_id: int) -> dict:
    row = db.query_one("SELECT * FROM category WHERE id = ?", (category_id,))
    if not row:
        raise HttpError(404, "Kategorija ne postoji.")
    return row


def list_all(include_archived: bool = False) -> list[dict]:
    where = "" if include_archived else "WHERE archived_at IS NULL"
    return db.query(f"SELECT * FROM category {where} ORDER BY parent_id, position, name")


def tree(include_archived: bool = False) -> list[dict]:
    """Stablo sa brojacima, spremno za prikaz u sidebar-u."""
    rows = list_all(include_archived)
    counts = _counters()

    nodes: dict[int, dict] = {}
    for row in rows:
        node = dict(row)
        node["children"] = []
        node.update(counts.get(row["id"], _empty_counter()))
        nodes[row["id"]] = node

    roots: list[dict] = []
    for node in nodes.values():
        parent = nodes.get(node["parent_id"]) if node["parent_id"] else None
        if parent is not None:
            parent["children"].append(node)
        else:
            roots.append(node)

    for node in nodes.values():
        node["children"].sort(key=lambda item: (item["position"], item["name"].lower()))
        _roll_up(node)
    roots.sort(key=lambda item: (item["position"], item["name"].lower()))
    return roots


def _roll_up(node: dict) -> dict:
    totals = {
        "total_questions": node["own_questions"],
        "total_materials": node["own_materials"],
        "total_due": node["own_due"],
    }
    for child in node["children"]:
        child_totals = _roll_up(child)
        for key in totals:
            totals[key] += child_totals[key]
    node.update(totals)
    return totals


def _empty_counter() -> dict:
    return {"own_questions": 0, "own_materials": 0, "own_due": 0}


def _counters() -> dict[int, dict]:
    result: dict[int, dict] = {}

    for row in db.query(
        """
        SELECT q.category_id AS cid, COUNT(*) AS n
        FROM question q
        LEFT JOIN question_meta m ON m.question_id = q.id
        WHERE q.state = 'active' AND m.deleted_at IS NULL AND m.ignored_at IS NULL
        GROUP BY q.category_id
        """
    ):
        result.setdefault(row["cid"], _empty_counter())["own_questions"] = row["n"]

    for row in db.query("SELECT category_id AS cid, COUNT(*) AS n FROM material GROUP BY category_id"):
        result.setdefault(row["cid"], _empty_counter())["own_materials"] = row["n"]

    for row in db.query(
        """
        SELECT s.category_id AS cid, COUNT(*) AS n
        FROM question_schedule s
        JOIN question q ON q.id = s.question_id
        LEFT JOIN question_meta m ON m.question_id = q.id
        WHERE s.due_at <= datetime('now') AND q.state = 'active'
              AND m.deleted_at IS NULL AND m.ignored_at IS NULL
        GROUP BY s.category_id
        """
    ):
        result.setdefault(row["cid"], _empty_counter())["own_due"] = row["n"]

    return result


def ancestors(category_id: int) -> list[dict]:
    """Od korena do roditelja. Nosi seen-set jer je ciklus u self-FK stablu petlja."""
    chain: list[dict] = []
    seen: set[int] = set()
    current = get(category_id)
    while current["parent_id"]:
        if current["parent_id"] in seen:
            break
        seen.add(current["parent_id"])
        current = db.query_one("SELECT * FROM category WHERE id = ?", (current["parent_id"],))
        if not current:
            break
        chain.append(current)
    chain.reverse()
    return chain


def breadcrumb(category_id: int) -> list[dict]:
    return [*ancestors(category_id), get(category_id)]


def subtree_ids(category_id: int, include_self: bool = True) -> list[int]:
    """Svi potomci, BFS sa seen-setom umesto rekurzivnog CTE-a koji bi na
    ciklusu vrteo zauvek."""
    edges: dict[Optional[int], list[int]] = {}
    for row in db.query("SELECT id, parent_id FROM category"):
        edges.setdefault(row["parent_id"], []).append(row["id"])

    result: list[int] = [category_id] if include_self else []
    seen: set[int] = {category_id}
    queue = list(edges.get(category_id, []))
    while queue:
        current = queue.pop(0)
        if current in seen:
            continue
        seen.add(current)
        result.append(current)
        queue.extend(edges.get(current, []))
    return result


def effective_study_prompt(category_id: int) -> str:
    """Sta se uci: uputstva roditelja pa svoje, spojena redom.

    Predmet nosi "gradivo se uci na srpskom, oznake iz skripte", kolokvijum
    dodaje "samo lekcije 1-5". Oba vaze.
    """
    pieces: list[str] = []
    for node in breadcrumb(category_id):
        text = (node["study_prompt"] or "").strip()
        if text:
            pieces.append(f"[{node['name']}] {text}")
    return "\n\n".join(pieces)


def create(
    name: str,
    parent_id: Optional[int] = None,
    description: str = "",
    study_prompt: str = "",
    color: str = "",
) -> dict:
    name = (name or "").strip()
    if not name:
        raise HttpError(400, "Naziv kategorije je obavezan.")
    if parent_id:
        get(parent_id)

    position = db.scalar(
        "SELECT COALESCE(MAX(position), 0) + 1 FROM category WHERE parent_id IS ?",
        (parent_id,),
        default=1,
    )
    new_id = db.insert(
        "category",
        {
            "parent_id": parent_id,
            "name": name,
            "slug": _unique_slug(name, parent_id),
            "description": description or "",
            "study_prompt": study_prompt or "",
            "color": color or "",
            "position": position,
        },
    )
    return get(new_id)


def update(category_id: int, values: dict) -> dict:
    current = get(category_id)
    allowed = {"name", "description", "study_prompt", "color", "position"}
    changes = {key: values[key] for key in allowed if key in values}

    if "name" in changes:
        changes["name"] = (changes["name"] or "").strip()
        if not changes["name"]:
            raise HttpError(400, "Naziv kategorije je obavezan.")
        if changes["name"] != current["name"]:
            changes["slug"] = _unique_slug(changes["name"], current["parent_id"], skip_id=category_id)

    if changes:
        changes["updated_at"] = _now()
        db.update("category", category_id, changes)
    return get(category_id)


def move(category_id: int, new_parent_id: Optional[int]) -> dict:
    get(category_id)
    if new_parent_id is not None:
        if new_parent_id == category_id:
            raise HttpError(400, "Kategorija ne moze da bude sama sebi roditelj.")
        if new_parent_id in subtree_ids(category_id):
            raise HttpError(400, "Kategorija ne moze da se premesti u sopstveni podstablo.")
        get(new_parent_id)

    node = get(category_id)
    db.update(
        "category",
        category_id,
        {
            "parent_id": new_parent_id,
            "slug": _unique_slug(node["name"], new_parent_id, skip_id=category_id),
            "updated_at": _now(),
        },
    )
    return get(category_id)


def archive(category_id: int, archived: bool = True) -> dict:
    get(category_id)
    db.update(
        "category",
        category_id,
        {"archived_at": _now() if archived else None, "updated_at": _now()},
    )
    return get(category_id)


def delete(category_id: int) -> dict:
    """Brise kategoriju sa celim podstablom. Fajlove na disku brise pozivalac."""
    get(category_id)
    ids = subtree_ids(category_id)
    materials = db.query(
        f"SELECT id, rel_path FROM material WHERE category_id IN ({_marks(ids)})", ids
    )
    db.execute("DELETE FROM category WHERE id = ?", (category_id,))
    return {"deleted_ids": ids, "materials": materials}


def storage_dirname(category_id: int) -> str:
    node = get(category_id)
    return f"{node['id']}-{node['slug']}"


def _unique_slug(name: str, parent_id: Optional[int], skip_id: Optional[int] = None) -> str:
    base = slugify(name)
    candidate = base
    counter = 2
    while True:
        clash = db.query_one(
            "SELECT id FROM category WHERE parent_id IS ? AND slug = ? AND id IS NOT ?",
            (parent_id, candidate, skip_id),
        )
        if not clash:
            return candidate
        candidate = f"{base}-{counter}"
        counter += 1


def _marks(values: list) -> str:
    return ", ".join("?" for _ in values) or "NULL"


def _now() -> str:
    return db.scalar("SELECT datetime('now')")
