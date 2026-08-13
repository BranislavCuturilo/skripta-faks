"""Materijali: sta korisnik uploaduje i sta se od toga da procitati.

Fajl se uvek cuva u originalu. Ekstrakcija je izvedeni podatak i sme da se
ponovi kad god - zato `reprocess` postoji i zato original nikad ne diramo.
"""

import hashlib
import uuid
from pathlib import Path
from typing import Optional

from .. import config, db, extract
from ..extract import chunking
from ..http_util import HttpError, UploadedFile
from . import categories, settings_store


def get(material_id: int) -> dict:
    row = db.query_one("SELECT * FROM material WHERE id = ?", (material_id,))
    if not row:
        raise HttpError(404, "Materijal ne postoji.")
    return row


def list_for(category_id: int, include_subtree: bool = False) -> list[dict]:
    ids = categories.subtree_ids(category_id) if include_subtree else [category_id]
    marks = ", ".join("?" for _ in ids)
    return db.query(
        f"SELECT * FROM material WHERE category_id IN ({marks}) ORDER BY created_at DESC", ids
    )


def store_upload(category_id: int, upload: UploadedFile, note: str = "") -> dict:
    categories.get(category_id)

    name = (upload.filename or "").strip() or "fajl"
    extension = Path(name).suffix.lower()
    if extension not in config.ALLOWED_UPLOAD_EXT:
        upload.discard()
        raise HttpError(
            415,
            f"Format {extension or '(bez ekstenzije)'} nije podržan.",
            sorted(config.ALLOWED_UPLOAD_EXT),
        )
    if upload.size > config.MAX_UPLOAD_BYTES:
        upload.discard()
        raise HttpError(413, "Fajl je veći od dozvoljenog.")
    if upload.size == 0:
        upload.discard()
        raise HttpError(400, "Fajl je prazan.")

    digest = _sha256(upload.temp_path)
    existing = db.query_one(
        "SELECT * FROM material WHERE category_id = ? AND sha256 = ?", (category_id, digest)
    )
    if existing:
        upload.discard()
        return {**existing, "duplicate": True}

    directory = categories.storage_dirname(category_id)
    stored_name = f"{uuid.uuid4().hex}{extension}"
    relative = Path("materials") / directory / stored_name
    upload.move_to(config.DATA_DIR / relative)

    material_id = db.insert(
        "material",
        {
            "category_id": category_id,
            "filename": name,
            "stored_name": stored_name,
            "rel_path": relative.as_posix(),
            "mime": upload.content_type or "",
            "ext": extension,
            "size_bytes": upload.size,
            "sha256": digest,
            "kind": extract.kind_for(extension),
            "extraction_status": "pending",
            "user_note": note or "",
        },
    )
    return {**get(material_id), "duplicate": False}


def process(material_id: int) -> dict:
    """Izvuci tekst i iseci ga na komade. Idempotentno - brise stare komade."""
    material = get(material_id)
    path = config.DATA_DIR / material["rel_path"]
    if not path.is_file():
        db.update("material", material_id, {"extraction_status": "failed",
                                            "extraction_note": "Fajl nije pronadjen na disku."})
        return get(material_id)

    result = extract.extract(path)

    db.execute("DELETE FROM material_chunk WHERE material_id = ?", (material_id,))
    if result.text:
        _write_extracted(material_id, result.text)
        budget = int(settings_store.get("batch_char_budget", 60000))
        rows = [
            (material_id, chunk["ordinal"], chunk["label"], chunk["text"], chunk["char_count"])
            for chunk in chunking.split(result.text, budget=budget)
        ]
        db.executemany(
            """
            INSERT INTO material_chunk (material_id, ordinal, label, text, char_count)
            VALUES (?, ?, ?, ?, ?)
            """,
            rows,
        )

    db.update(
        "material",
        material_id,
        {
            "extraction_status": result.status,
            "extraction_method": result.method,
            "extraction_note": result.note,
            "quality_score": result.quality,
            "char_count": result.char_count,
            "page_count": result.page_count,
            "updated_at": _now(),
        },
    )
    return get(material_id)


def outline_for(material_id: int) -> list[str]:
    path = config.EXTRACTED_DIR / f"{material_id}.txt"
    if not path.is_file():
        return []
    return chunking.outline(path.read_text("utf-8", "replace"))


def preview(material_id: int, limit: int = 4000) -> str:
    path = config.EXTRACTED_DIR / f"{material_id}.txt"
    if not path.is_file():
        return ""
    return path.read_text("utf-8", "replace")[:limit]


def update_meta(material_id: int, values: dict) -> dict:
    get(material_id)
    allowed = {"user_note", "include_in_study", "filename"}
    changes = {key: values[key] for key in allowed if key in values}
    if "include_in_study" in changes:
        changes["include_in_study"] = 1 if str(changes["include_in_study"]).lower() not in ("0", "false", "ne") else 0
    if changes:
        changes["updated_at"] = _now()
        db.update("material", material_id, changes)
    return get(material_id)


def delete(material_id: int) -> None:
    material = get(material_id)
    db.execute("DELETE FROM material WHERE id = ?", (material_id,))
    for path in (config.DATA_DIR / material["rel_path"], config.EXTRACTED_DIR / f"{material_id}.txt"):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def chunks_for(category_ids: list[int], only_included: bool = True) -> list[dict]:
    """Svi tekstualni komadi kategorija - ulaz u generisanje pitanja."""
    if not category_ids:
        return []
    marks = ", ".join("?" for _ in category_ids)
    condition = "AND m.include_in_study = 1" if only_included else ""
    return db.query(
        f"""
        SELECT c.*, m.filename, m.category_id, m.kind
        FROM material_chunk c
        JOIN material m ON m.id = c.material_id
        WHERE m.category_id IN ({marks}) {condition}
        ORDER BY m.created_at, c.ordinal
        """,
        category_ids,
    )


def remote_materials(category_ids: list[int]) -> list[dict]:
    """Fajlovi koje lokalno nismo procitali - njih saljemo AI-u u originalu."""
    if not category_ids:
        return []
    marks = ", ".join("?" for _ in category_ids)
    return db.query(
        f"""
        SELECT * FROM material
        WHERE category_id IN ({marks})
          AND include_in_study = 1
          AND extraction_status IN ('remote_needed', 'pending', 'failed')
        ORDER BY created_at
        """,
        category_ids,
    )


def images_for(category_ids: list[int]) -> list[dict]:
    if not category_ids:
        return []
    marks = ", ".join("?" for _ in category_ids)
    return db.query(
        f"SELECT * FROM material WHERE category_id IN ({marks}) AND kind = 'image' ORDER BY created_at",
        category_ids,
    )


def _write_extracted(material_id: int, text: str) -> None:
    config.EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)
    (config.EXTRACTED_DIR / f"{material_id}.txt").write_text(text, "utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _now() -> str:
    return db.scalar("SELECT datetime('now')")
