"""Generisanje pitanja iz materijala.

Optimizacija je bila izricit zahtev: sto vise sadrzaja po pozivu, sto manje
poziva. Zato jedan poziv nosi ceo komad gradiva do budzeta znakova i trazi
desetine pitanja odjednom, umesto pitanja po pitanja.

Fajlovi koje lokalno nismo procitali (slike, skenirani PDF, snimci) idu u
zaseban poziv preko Files API-ja, u originalu.

Isti put postoji i rucno: `export_prompt` da tekst odnesеs u Claude, pa
`import_manual` da odgovor vratis - kroz potpuno istu proveru.
"""

import json
from typing import Any, Optional

from .. import config, db, translit
from ..ai import contract, gemini, prompts
from ..http_util import HttpError
from . import ai_models, categories, materials, questions, settings_store, strategy
from .jobs import Job

# Koliko originalnih fajlova ide u jedan poziv - vise od ovoga i zahtev pukne.
FILES_PER_CALL = 4

def resolve_model(tier: str) -> str:
    """Naziv se ne cita iz konstante nego se razresava - vidi services/ai_models.py."""
    return ai_models.for_tier(tier)


def question_script() -> Optional[str]:
    """Pismo koje se namece svakom pitanju pre upisa ('latin', 'cyrillic' ili None).

    Model dobije uputstvo u promptu, ali ga ne postuje uvek - vraca pola
    latinicom, pola cirilicom kad je gradivo cirilicno. Ovo je garancija.
    """
    return translit.script_for_language(settings_store.get("question_language", "sr"))


def plan(category_id: int, options: Optional[dict] = None) -> dict:
    """Sta bi se poslalo - da korisnik vidi obim pre nego sto potrosi kvotu."""
    options = _options(options)
    ids = _target_ids(category_id, options["include_subtree"])

    chunks = materials.chunks_for(ids)
    remote = [
        item for item in materials.remote_materials(ids)
        if item["kind"] in ("image", "audio", "video", "pdf", "document")
    ]
    text_batches = _pack(chunks, options["char_budget"])
    file_batches = [remote[index : index + FILES_PER_CALL] for index in range(0, len(remote), FILES_PER_CALL)]

    if options["max_calls"]:
        text_batches = text_batches[: options["max_calls"]]

    total_chars = sum(batch["char_count"] for batch in text_batches)
    return {
        "category_id": category_id,
        "categories": ids,
        "chunks": len(chunks),
        "text_calls": len(text_batches),
        "file_calls": len(file_batches),
        "total_calls": len(text_batches) + len(file_batches),
        "total_chars": total_chars,
        "approx_tokens": int(total_chars / 3.6),
        "remote_files": [
            {"id": item["id"], "filename": item["filename"], "kind": item["kind"],
             "reason": item["extraction_note"]}
            for item in remote
        ],
        "questions_expected": (len(text_batches) + len(file_batches)) * options["count_per_call"],
        "model": resolve_model(options["tier"]),
        "batches": [
            {"index": index + 1, "chars": batch["char_count"], "sources": batch["sources"]}
            for index, batch in enumerate(text_batches)
        ],
    }


def build_prompt_for_batch(category_id: int, batch_text: str, options: dict) -> tuple[str, str]:
    ids = _target_ids(category_id, options["include_subtree"])
    active = strategy.active(category_id).get("content") or {}

    allowed = options["allowed_types"] or None
    type_mix = options.get("type_mix") or active.get("type_mix") or None
    note_pieces = [active.get("generation_note", ""), options.get("extra_instructions", "")]
    focus = active.get("focus_topics") or []
    if focus:
        note_pieces.append("Teme u fokusu: " + ", ".join(focus))
    avoid = active.get("avoid_topics") or []
    if avoid:
        note_pieces.append("Teme koje su savladane, manje ih pitaj: " + ", ".join(avoid))
    bias = active.get("difficulty_bias") or 0
    if bias:
        note_pieces.append("Pitanja neka budu " + ("teza." if bias > 0 else "laksa."))

    prompt = prompts.build_generation_prompt(
        category_path=_path_of(category_id),
        study_prompt=categories.effective_study_prompt(category_id),
        material=batch_text,
        count=options["count_per_call"],
        type_mix=type_mix,
        allowed_types=allowed,
        variants=options["variants"],
        language=settings_store.get("question_language", "sr"),
        misconceptions=strategy.misconceptions(category_id),
        existing_stems=questions.existing_stems(ids) if options["avoid_duplicates"] else None,
        strategy_note="\n".join(piece for piece in note_pieces if piece.strip()),
    )
    return prompts.SYSTEM_GENERATE, prompt


def export_prompt(category_id: int, options: Optional[dict] = None) -> dict:
    """Prompt kao tekst za lepljenje u drugi model (Claude i slicno)."""
    options = _options(options)
    ids = _target_ids(category_id, options["include_subtree"])
    chunks = materials.chunks_for(ids)
    if not chunks:
        raise HttpError(
            400,
            "Nema procitanog teksta u ovoj kategoriji. Uploaduj materijale, ili ih posalji "
            "direktno Gemini-ju ako se lokalno ne citaju.",
        )

    batches = _pack(chunks, options["char_budget"])
    index = max(0, min(int(options.get("batch_index", 0)), len(batches) - 1))
    system, prompt = build_prompt_for_batch(category_id, batches[index]["text"], options)

    return {
        "batch_index": index,
        "batch_count": len(batches),
        "chars": batches[index]["char_count"],
        "sources": batches[index]["sources"],
        "text": prompts.export_bundle(system, prompt),
    }


def import_manual(category_id: int, raw_text: str) -> dict:
    """Odgovor iz drugog modela - ista provera kao za Gemini, bez izuzetka."""
    categories.get(category_id)
    if not (raw_text or "").strip():
        raise HttpError(400, "Nema nicega za uvoz.")

    run_id = db.insert(
        "generation_run",
        {
            "category_id": category_id,
            "provider": "manual",
            "model": "(nalepljeno)",
            "source_kind": "manual_import",
            "status": "running",
            "response_text": raw_text[:200000],
        },
    )
    try:
        parsed = contract.parse(raw_text)
    except contract.ContractError as exc:
        db.update("generation_run", run_id, {"status": "failed", "error": str(exc),
                                             "finished_at": _now()})
        raise HttpError(400, f"Nalepljeni tekst nije u ocekivanom formatu: {exc}") from None

    accepted, rejected = contract.validate_all(parsed["questions"], script=question_script())
    written = questions.insert_many(category_id, run_id, accepted)

    db.update(
        "generation_run",
        run_id,
        {
            "status": "done",
            "produced_count": written["inserted_count"],
            "rejected_count": len(rejected),
            "duplicate_count": written["duplicates"],
            "finished_at": _now(),
        },
    )
    return {
        "run_id": run_id,
        "inserted": written["inserted_count"],
        "duplicates": written["duplicates"],
        "rejected": rejected,
        "salvaged": parsed["salvaged"],
    }


def run(category_id: int, options: Optional[dict], job: Optional[Job] = None) -> dict:
    """Odradi ceo plan: tekstualni pozivi pa fajlovi. Delimican uspeh je uspeh."""
    options = _options(options)
    categories.get(category_id)

    api_key = settings_store.get("gemini_api_key", "")
    if not api_key:
        raise HttpError(400, "Nije unet Gemini API ključ. Podešavanja → AI.")

    ids = _target_ids(category_id, options["include_subtree"])
    model = resolve_model(options["tier"])

    text_batches = _pack(materials.chunks_for(ids), options["char_budget"])
    if options["max_calls"]:
        text_batches = text_batches[: options["max_calls"]]
    remote = [
        item for item in materials.remote_materials(ids)
        if item["kind"] in ("image", "audio", "video", "pdf", "document")
    ] if options["include_files"] else []
    file_batches = [remote[index : index + FILES_PER_CALL] for index in range(0, len(remote), FILES_PER_CALL)]

    total = len(text_batches) + len(file_batches)
    if not total:
        raise HttpError(400, "Nema materijala za generisanje. Prvo ubaci fajlove u kategoriju.")

    summary = {
        "calls": 0, "inserted": 0, "duplicates": 0,
        "rejected": [], "errors": [], "runs": [],
    }

    for index, batch in enumerate(text_batches, start=1):
        if job and job.cancelled:
            summary["errors"].append("Prekinuto na tvoj zahtev.")
            break
        if job:
            job.progress(index - 1, total, f"Gradivo {index}/{len(text_batches)} ({batch['char_count']:,} znakova)")
        _one_call(
            category_id=category_id,
            api_key=api_key,
            model=model,
            options=options,
            batch_text=batch["text"],
            chunk_ids=batch["chunk_ids"],
            files=None,
            summary=summary,
        )

    for index, group in enumerate(file_batches, start=1):
        if job and job.cancelled:
            summary["errors"].append("Prekinuto na tvoj zahtev.")
            break
        if job:
            job.progress(
                len(text_batches) + index - 1, total,
                f"Fajlovi {index}/{len(file_batches)}: " + ", ".join(item["filename"] for item in group),
            )
        try:
            attachments = [_ensure_uploaded(api_key, item) for item in group]
        except gemini.AiError as exc:
            summary["errors"].append(f"Upload fajlova nije uspeo: {exc.message}")
            continue

        listing = "\n".join(f"- {item['filename']} ({item['kind']})" for item in group)
        _one_call(
            category_id=category_id,
            api_key=api_key,
            model=model,
            options=options,
            batch_text=(
                "Gradivo je u prilozenim fajlovima. Procitaj ih i pravi pitanja iz njihovog "
                "sadrzaja.\nPrilozeni fajlovi:\n" + listing
            ),
            chunk_ids=[],
            files=attachments,
            summary=summary,
        )

    if job:
        job.progress(total, total, "Gotovo.")

    if options["auto_strategy"] and summary["inserted"]:
        try:
            strategy.refresh(category_id)
        except Exception as exc:  # noqa: BLE001 - strategija nije razlog da generisanje padne
            summary["errors"].append(f"Osvezavanje strategije preskoceno: {exc}")

    return summary


def _one_call(
    *,
    category_id: int,
    api_key: str,
    model: str,
    options: dict,
    batch_text: str,
    chunk_ids: list[int],
    files: Optional[list[dict]],
    summary: dict,
) -> None:
    system, prompt = build_prompt_for_batch(category_id, batch_text, options)
    run_id = db.insert(
        "generation_run",
        {
            "category_id": category_id,
            "provider": "gemini",
            "model": model,
            "source_kind": "auto",
            "status": "running",
            "request_json": json.dumps({"chars": len(prompt), "files": len(files or [])}),
            "chunk_ids": json.dumps(chunk_ids),
            "requested_count": options["count_per_call"],
        },
    )
    summary["calls"] += 1

    try:
        result = ai_models.generate(
            options["tier"],
            prompt,
            api_key=api_key,
            model=model,
            system=system,
            files=files,
            json_output=True,
            temperature=options["temperature"],
            purpose="generate_questions",
        )
        if result.get("model_switched"):
            switch = result["model_switched"]
            db.update("generation_run", run_id, {"model": switch["to"]})
            summary["errors"].append(
                f"Model '{switch['from']}' više nije dostupan — prešao sam na '{switch['to']}'."
            )
    except gemini.AiError as exc:
        db.update("generation_run", run_id, {"status": "failed", "error": exc.message,
                                             "finished_at": _now()})
        summary["errors"].append(exc.message)
        return

    try:
        parsed = contract.parse(result["text"])
    except contract.ContractError as exc:
        db.update(
            "generation_run", run_id,
            {"status": "failed", "error": str(exc), "response_text": result["text"][:200000],
             "finished_at": _now()},
        )
        summary["errors"].append(f"Odgovor modela nije upotrebljiv: {exc}")
        return

    accepted, rejected = contract.validate_all(parsed["questions"], script=question_script())
    written = questions.insert_many(category_id, run_id, accepted)

    db.update(
        "generation_run",
        run_id,
        {
            "status": "done",
            "response_text": result["text"][:200000],
            "produced_count": written["inserted_count"],
            "rejected_count": len(rejected),
            "duplicate_count": written["duplicates"],
            "prompt_tokens": result.get("prompt_tokens"),
            "output_tokens": result.get("output_tokens"),
            "finished_at": _now(),
        },
    )

    summary["inserted"] += written["inserted_count"]
    summary["duplicates"] += written["duplicates"]
    summary["rejected"].extend(rejected)
    summary["runs"].append(run_id)
    if parsed["salvaged"]:
        summary["errors"].append(
            f"Odgovor je bio odsecen; spaseno {len(accepted)} celih pitanja. "
            "Smanji broj pitanja po pozivu ako se ponovi."
        )


def _ensure_uploaded(api_key: str, material: dict) -> dict:
    """Fajl na Google-u zivi 48h - iskoristi postojeci upload dok vazi."""
    if material.get("remote_uri") and material.get("remote_expires_at"):
        still_valid = db.scalar(
            "SELECT CASE WHEN ? > datetime('now', '+5 minutes') THEN 1 ELSE 0 END",
            (material["remote_expires_at"],),
            default=0,
        )
        if still_valid:
            return {"uri": material["remote_uri"], "mime_type": material["mime"]}

    path = config.DATA_DIR / material["rel_path"]
    if material["size_bytes"] <= gemini.INLINE_LIMIT_BYTES and material["kind"] == "image":
        return {"path": str(path), "mime_type": material["mime"]}

    uploaded = gemini.upload_file(api_key, path, material["filename"])
    if material["kind"] in ("audio", "video"):
        gemini.wait_until_active(api_key, uploaded["name"])

    db.update(
        "material",
        material["id"],
        {
            "remote_uri": uploaded["uri"],
            "remote_expires_at": (uploaded.get("expires_at") or "").replace("T", " ")[:19] or None,
            "updated_at": _now(),
        },
    )
    return {"uri": uploaded["uri"], "mime_type": uploaded["mime_type"]}


def _pack(chunks: list[dict], budget: int) -> list[dict]:
    """Spakuj komade u sto manje poziva, bez sečenja komada na pola."""
    batches: list[dict] = []
    current: dict[str, Any] = {"text": "", "char_count": 0, "chunk_ids": [], "sources": []}

    for chunk in chunks:
        header = f"\n\n=== {chunk['filename']}"
        if chunk["label"]:
            header += f" | {chunk['label']}"
        header += " ===\n"
        piece = header + chunk["text"]

        if current["char_count"] and current["char_count"] + len(piece) > budget:
            batches.append(current)
            current = {"text": "", "char_count": 0, "chunk_ids": [], "sources": []}

        current["text"] += piece
        current["char_count"] += len(piece)
        current["chunk_ids"].append(chunk["id"])
        if chunk["filename"] not in current["sources"]:
            current["sources"].append(chunk["filename"])

    if current["char_count"]:
        batches.append(current)
    return batches


def _options(raw: Optional[dict]) -> dict:
    raw = raw or {}
    allowed = raw.get("allowed_types") or []
    if isinstance(allowed, str):
        allowed = [item.strip() for item in allowed.split(",") if item.strip()]

    return {
        "include_subtree": _truthy(raw.get("include_subtree", True)),
        "count_per_call": max(1, min(80, int(raw.get("count_per_call") or 25))),
        "variants": max(0, min(4, int(raw.get("variants", settings_store.get("generate_variants", 2))))),
        "allowed_types": allowed,
        "type_mix": raw.get("type_mix") or None,
        "char_budget": max(4000, min(400000, int(raw.get("char_budget")
                                                 or settings_store.get("batch_char_budget", 60000)))),
        "max_calls": max(0, int(raw.get("max_calls") or 0)),
        "tier": str(raw.get("tier") or "standard"),
        "temperature": max(0.0, min(1.5, float(raw.get("temperature") or 0.8))),
        "extra_instructions": str(raw.get("extra_instructions") or ""),
        "avoid_duplicates": _truthy(raw.get("avoid_duplicates", True)),
        "include_files": _truthy(raw.get("include_files", True)),
        "auto_strategy": _truthy(raw.get("auto_strategy", settings_store.get("auto_strategy", True))),
        "batch_index": int(raw.get("batch_index") or 0),
    }


def _target_ids(category_id: int, include_subtree: bool) -> list[int]:
    return categories.subtree_ids(category_id) if include_subtree else [category_id]


def _path_of(category_id: int) -> str:
    return " / ".join(node["name"] for node in categories.breadcrumb(category_id))


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "da", "yes", "on")


def _now() -> str:
    return db.scalar("SELECT datetime('now')")
