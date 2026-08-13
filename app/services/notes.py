"""AI dopune materijala.

Kad se u ucenju vidi rupa koja se ponavlja, model napise kratku dopunu bas za
te tacke. Dopuna je DODATNI sloj koji citas - originalni materijal se ne dira.
"""

import json
from typing import Optional

from .. import db
from ..ai import contract, gemini, prompts
from ..http_util import HttpError
from . import categories, materials, settings_store, strategy

MAX_MATERIAL_CHARS = 60000


def list_for(category_id: int, include_subtree: bool = True) -> list[dict]:
    ids = categories.subtree_ids(category_id) if include_subtree else [category_id]
    marks = ", ".join("?" for _ in ids)
    return db.query(
        f"SELECT * FROM material_note WHERE category_id IN ({marks}) ORDER BY created_at DESC",
        ids,
    )


def create_manual(category_id: int, title: str, body: str) -> dict:
    categories.get(category_id)
    note_id = db.insert(
        "material_note",
        {
            "category_id": category_id,
            "kind": "manual",
            "title": (title or "Beleska").strip()[:200],
            "body": body or "",
            "author": "user",
        },
    )
    return db.query_one("SELECT * FROM material_note WHERE id = ?", (note_id,))


def delete(note_id: int) -> None:
    if not db.query_one("SELECT id FROM material_note WHERE id = ?", (note_id,)):
        raise HttpError(404, "Beleska ne postoji.")
    db.execute("DELETE FROM material_note WHERE id = ?", (note_id,))


def generate(category_id: int, gaps: Optional[list[str]] = None) -> dict:
    """Napisi dopunu za tacke koje se ponavljaju kao greska."""
    categories.get(category_id)
    api_key = settings_store.get("gemini_api_key", "")
    if not api_key:
        raise HttpError(400, "Nije unet Gemini API kljuc.")

    if not gaps:
        gaps = [item["label"] for item in strategy.misconceptions(category_id, limit=10)]
        evidence = strategy.evidence(category_id)
        gaps.extend(
            f"{item['topic']} (uspesnost {item['average_score']})"
            for item in (evidence.get("weakest_topics") or [])[:5]
        )
    gaps = [item for item in gaps if str(item).strip()][:15]
    if not gaps:
        raise HttpError(
            400,
            "Jos nema dovoljno podataka o greskama. Uradi nekoliko sesija pa probaj ponovo.",
        )

    ids = categories.subtree_ids(category_id)
    chunks = materials.chunks_for(ids)
    if not chunks:
        raise HttpError(400, "Nema procitanog gradiva u ovoj kategoriji.")

    material = ""
    for chunk in chunks:
        if len(material) + chunk["char_count"] > MAX_MATERIAL_CHARS:
            break
        material += f"\n\n=== {chunk['filename']} ===\n{chunk['text']}"

    prompt = prompts.build_material_note_prompt(
        category_path=" / ".join(node["name"] for node in categories.breadcrumb(category_id)),
        material=material,
        gaps=gaps,
        language=settings_store.get("ui_language", "sr"),
    )
    result = gemini.generate(
        api_key,
        settings_store.get("model_standard"),
        prompt,
        system="Ti si tutor koji pise sazete dopune gradiva. Odgovaras iskljucivo JSON-om.",
        json_output=True,
        temperature=0.5,
        purpose="material_note",
    )

    try:
        payload = json.loads(contract.strip_fence(result["text"]))
    except ValueError as exc:
        raise HttpError(502, f"Model nije vratio ispravan JSON: {exc}") from None
    if not isinstance(payload, dict) or not str(payload.get("body") or "").strip():
        raise HttpError(502, "Model nije vratio tekst dopune.")

    note_id = db.insert(
        "material_note",
        {
            "category_id": category_id,
            "kind": "gap_fill",
            "title": str(payload.get("title") or "Dopuna gradiva").strip()[:200],
            "body": str(payload["body"]).strip(),
            "author": "ai",
        },
    )
    return {
        "note": db.query_one("SELECT * FROM material_note WHERE id = ?", (note_id,)),
        "gaps": gaps,
    }
