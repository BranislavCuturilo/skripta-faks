"""Uvoz fiksne liste ispitnih pitanja - DOSLOVNO, bez AI prepravljanja.

Zahtev korisnika: "postoji fiksna lista pitanja koja se ne menja; na ispitu
dodje 20 od tih 100, tacno onako kako pise u dokumentu - hocu da vezbam bas
njih". Generisanje iz gradiva tu ne valja: model parafrazira, spaja, dodaje.

Dva rezima, oba upisuju pitanja sa `origin='exam'`:

1. `import_local`  - parser (`extract/exam_parser.py`), nula AI poziva. Pitanje i
   odgovori ulaze znak po znak iz teksta. Radi kad je dokument koliko-toliko
   sredjen (numerisana pitanja, a) b) c) odgovori, oznacen tacan).
2. `import_ai`     - Gemini prepisuje nesredjen fajl ili sken. I tu vazi
   "doslovno": kad postoji lokalno procitan tekst, svako pitanje se proverava
   da li se njegov tekst i svaki odgovor STVARNO nalaze u tom tekstu
   (`_verbatim_guard`). Sto nije nadjeno - odbija se, ne upisuje.
   Tacan odgovor koji nije pisao u dokumentu nego ga je model odredio nosi
   flag "provera u fajlu" od prvog prikaza.

`preview` ne upisuje nista - pokaze korisniku sta je prepoznato da odluci.
"""

import json
import re
import unicodedata
from typing import Any, Optional

from .. import config, db, translit
from ..ai import contract, gemini, prompts
from ..extract import chunking, exam_parser
from ..http_util import HttpError
from ..quiz import types as question_types
from . import ai_models, categories, generation, materials, questions, settings_store
from .jobs import Job

# Manji komad nego kod generisanja: prepis vraca SVA pitanja iz komada, pa je
# izlaz srazmeran ulazu i lako probije limit tokena.
DEFAULT_CHAR_BUDGET = 25000
ALLOWED_TYPES = {"mcq_single", "mcq_multi", "true_false", "short_answer", "numeric", "long_answer"}
PREVIEW_LIMIT = 300
_VALIDATION_ERRORS = (question_types.InvalidQuestion, contract.ContractError, TypeError, ValueError)


# --------------------------------------------------------------------------
# izvor teksta
# --------------------------------------------------------------------------


def _options(raw: Optional[dict]) -> dict:
    raw = raw or {}
    ids = raw.get("material_ids") or []
    if isinstance(ids, str):
        ids = [item for item in ids.split(",") if item.strip()]
    return {
        "material_ids": [int(item) for item in ids],
        "text": str(raw.get("text") or ""),
        "keep_order": _truthy(raw.get("keep_order", True)),
        "strict": _truthy(raw.get("strict", True)),
        "tier": str(raw.get("tier") or "standard"),
        "char_budget": max(4000, min(120000, int(raw.get("char_budget") or DEFAULT_CHAR_BUDGET))),
        "include_files": _truthy(raw.get("include_files", True)),
    }


def _sources(category_id: int, options: dict) -> dict:
    """Tekst iz izabranih materijala + nalepljeni tekst, i fajlovi bez teksta."""
    allowed_categories = set(categories.subtree_ids(category_id))
    texts: list[dict] = []
    remote: list[dict] = []
    for material_id in options["material_ids"]:
        material = materials.get(material_id)
        if material["category_id"] not in allowed_categories:
            raise HttpError(400, f"Materijal {material_id} nije u ovoj kategoriji.")
        path = config.EXTRACTED_DIR / f"{material_id}.txt"
        text = path.read_text("utf-8", "replace") if path.is_file() else ""
        if text.strip():
            texts.append({"label": material["filename"], "text": text})
        else:
            remote.append(material)
    if options["text"].strip():
        texts.append({"label": "nalepljeni tekst", "text": options["text"]})
    if not texts and not remote:
        raise HttpError(400, "Izaberi bar jedan materijal ili nalepi tekst sa pitanjima.")
    return {"texts": texts, "remote": remote}


# --------------------------------------------------------------------------
# pregled i lokalni uvoz
# --------------------------------------------------------------------------


def preview(category_id: int, raw_options: Optional[dict]) -> dict:
    """Sta bi parser prepoznao - nista se ne upisuje."""
    categories.get(category_id)
    options = _options(raw_options)
    sources = _sources(category_id, options)

    listing: list[dict] = []
    totals: dict[str, Any] = {"total": 0, "with_answer": 0, "without_answer": 0, "open": 0, "warnings": []}
    per_source: list[dict] = []

    for source in sources["texts"]:
        report = exam_parser.parse(source["text"])
        stats = exam_parser.summary(report)
        per_source.append({"label": source["label"], **{k: v for k, v in stats.items() if k != "warnings"}})
        for key in ("total", "with_answer", "without_answer", "open"):
            totals[key] += stats[key]
        totals["warnings"].extend(f"{source['label']}: {item}" for item in stats["warnings"])
        items, skipped = exam_parser.to_contract_items(
            report, keep_order=options["keep_order"], source_ref=source["label"]
        )
        listing.extend(_describe(item) for item in items)
        listing.extend(
            {"number": item["number"], "stem": item["stem"], "type": "", "skipped": item["reason"]}
            for item in skipped
        )

    return {
        "sources": per_source,
        "remote_files": [
            {"id": item["id"], "filename": item["filename"], "kind": item["kind"]}
            for item in sources["remote"]
        ],
        "stats": totals,
        "questions": listing[:PREVIEW_LIMIT],
        "shown": min(len(listing), PREVIEW_LIMIT),
        "importable": sum(1 for item in listing if not item.get("skipped")),
        "recommendation": _recommend(totals, sources),
    }


def _recommend(totals: dict, sources: dict) -> str:
    if sources["remote"] and not sources["texts"]:
        return "ai"
    if totals["total"] == 0:
        return "ai"
    if totals["without_answer"] > totals["total"] / 2:
        return "ai"
    return "local"


def import_local(category_id: int, raw_options: Optional[dict]) -> dict:
    """Parser -> ugovor -> baza. Nijedan AI poziv."""
    categories.get(category_id)
    options = _options(raw_options)
    sources = _sources(category_id, options)
    if not sources["texts"]:
        raise HttpError(
            400,
            "Izabrani fajlovi nemaju lokalno procitan tekst (sken ili slika). "
            "Za njih koristi rezim 'AI prepisuje doslovno'.",
        )

    script = generation.question_script()
    summary: dict[str, Any] = {
        "calls": 0, "inserted": 0, "duplicates": 0, "flagged": 0,
        "rejected": [], "skipped": [], "errors": [], "runs": [],
    }

    for source in sources["texts"]:
        report = exam_parser.parse(source["text"])
        items, skipped = exam_parser.to_contract_items(
            report, keep_order=options["keep_order"], source_ref=source["label"]
        )
        summary["skipped"].extend(skipped)
        if not items:
            continue

        run_id = db.insert(
            "generation_run",
            {
                "category_id": category_id,
                "provider": "local",
                "model": "(parser, bez AI)",
                "source_kind": "exam_local",
                "status": "running",
                "requested_count": len(report.questions),
            },
        )
        accepted, rejected = contract.validate_all(items, script=script)
        _record_run(summary, category_id, run_id, accepted, rejected)

    if not summary["inserted"] and not summary["duplicates"]:
        summary["errors"].append(
            "Parser nije prepoznao nijedno upotrebljivo pitanje. Proveri format "
            "(numerisana pitanja, a) b) c) odgovori, oznacen tacan) ili pusti AI da prepise."
        )
    return summary


# --------------------------------------------------------------------------
# AI prepis
# --------------------------------------------------------------------------


def import_ai(category_id: int, raw_options: Optional[dict], job: Optional[Job] = None) -> dict:
    """Gemini prepisuje doslovno; lokalni tekst je sudija sta je stvarno doslovno."""
    categories.get(category_id)
    options = _options(raw_options)
    api_key = settings_store.get("gemini_api_key", "")
    if not api_key:
        raise HttpError(400, "Nije unet Gemini API ključ. Podešavanja → AI.")
    sources = _sources(category_id, options)
    model = ai_models.for_tier(options["tier"])
    path = " / ".join(node["name"] for node in categories.breadcrumb(category_id))

    text_batches: list[dict] = []
    for source in sources["texts"]:
        for chunk in chunking.split(source["text"], budget=options["char_budget"], overlap=0):
            text_batches.append({"label": source["label"], "text": chunk["text"]})
    remote = sources["remote"] if options["include_files"] else []
    step = generation.FILES_PER_CALL
    file_batches = [remote[index : index + step] for index in range(0, len(remote), step)]
    total = len(text_batches) + len(file_batches)
    if not total:
        raise HttpError(400, "Nema teksta ni fajlova za prepis.")

    summary: dict[str, Any] = {
        "calls": 0, "inserted": 0, "duplicates": 0, "flagged": 0,
        "rejected": [], "skipped": [], "errors": [], "runs": [],
    }

    for index, batch in enumerate(text_batches, start=1):
        if job and job.cancelled:
            summary["errors"].append("Prekinuto na tvoj zahtev.")
            break
        if job:
            job.progress(index - 1, total, f"Prepis {index}/{len(text_batches)}: {batch['label']}")
        _one_call(
            category_id=category_id, api_key=api_key, model=model, options=options, path=path,
            material=batch["text"], haystack=batch["text"], files=None, summary=summary,
            label=batch["label"],
        )

    for index, group in enumerate(file_batches, start=1):
        if job and job.cancelled:
            summary["errors"].append("Prekinuto na tvoj zahtev.")
            break
        if job:
            job.progress(len(text_batches) + index - 1, total,
                         "Fajlovi: " + ", ".join(item["filename"] for item in group))
        try:
            attachments = [generation._ensure_uploaded(api_key, item) for item in group]
        except gemini.AiError as exc:
            summary["errors"].append(f"Upload fajlova nije uspeo: {exc.message}")
            continue
        listing = "\n".join(f"- {item['filename']}" for item in group)
        _one_call(
            category_id=category_id, api_key=api_key, model=model, options=options, path=path,
            material="Prilozeni fajlovi:\n" + listing, haystack=None, files=attachments,
            summary=summary, label=", ".join(item["filename"] for item in group),
        )

    if job:
        job.progress(total, total, "Gotovo.")
    return summary


def _one_call(
    *, category_id: int, api_key: str, model: str, options: dict, path: str,
    material: str, haystack: Optional[str], files: Optional[list[dict]], summary: dict, label: str,
) -> None:
    prompt = prompts.build_transcription_prompt(category_path=path, material=material, has_files=bool(files))
    run_id = db.insert(
        "generation_run",
        {
            "category_id": category_id,
            "provider": "gemini",
            "model": model,
            "source_kind": "exam_ai",
            "status": "running",
            "request_json": json.dumps({"chars": len(prompt), "files": len(files or []), "label": label}),
        },
    )
    summary["calls"] += 1
    try:
        result = ai_models.generate(
            options["tier"], prompt, api_key=api_key, model=model, system=prompts.SYSTEM_TRANSCRIBE,
            files=files, json_output=True, temperature=0.0, purpose="transcribe_exam",
        )
    except gemini.AiError as exc:
        db.update("generation_run", run_id, {"status": "failed", "error": exc.message, "finished_at": _now()})
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

    accepted, rejected = prepare_transcribed(
        parsed["questions"], haystack=haystack, keep_order=options["keep_order"],
        strict=options["strict"], script=generation.question_script(),
    )
    _record_run(
        summary, category_id, run_id, accepted, rejected,
        extra={
            "response_text": result["text"][:200000],
            "prompt_tokens": result.get("prompt_tokens"),
            "output_tokens": result.get("output_tokens"),
        },
    )
    if parsed["salvaged"]:
        summary["errors"].append(
            "Odgovor je bio odsecen; spaseno koliko je bilo celo. Smanji velicinu komada ako se ponovi."
        )


def _record_run(
    summary: dict, category_id: int, run_id: int, accepted: list[dict], rejected: list[dict],
    extra: Optional[dict] = None,
) -> None:
    """Upis pitanja + zatvaranje zapisa o pokretanju - isto za oba rezima."""
    written = questions.insert_many(category_id, run_id, accepted, author="exam", origin="exam")
    db.update(
        "generation_run",
        run_id,
        {
            "status": "done",
            "produced_count": written["inserted_count"],
            "rejected_count": len(rejected),
            "duplicate_count": written["duplicates"],
            "finished_at": _now(),
            **(extra or {}),
        },
    )
    summary["inserted"] += written["inserted_count"]
    summary["duplicates"] += written["duplicates"]
    summary["flagged"] += sum(1 for item in accepted if (item.get("flags") or {}).get("flag_check_source"))
    summary["rejected"].extend(rejected)
    summary["runs"].append(run_id)


def prepare_transcribed(
    raw_items: list, *, haystack: Optional[str], keep_order: bool = True, strict: bool = True,
    script: Optional[str] = None,
) -> tuple[list[dict], list[dict]]:
    """Odgovor modela -> provera ugovora -> provera doslovnosti -> flagovi.

    Odvojeno od poziva modelu da bi se testiralo bez mreze: isti ulaz kao
    odgovor modela, isti izlaz kao ono sto ide u `insert_many`.
    """
    accepted: list[dict] = []
    rejected: list[dict] = []
    source = _norm(haystack) if haystack else None

    for position, raw in enumerate(raw_items, start=1):
        if not isinstance(raw, dict):
            rejected.append({"position": position, "reason": "Stavka nije objekat.", "type": None, "stem": ""})
            continue
        item = dict(raw)
        item_type = str(item.get("type") or "")
        stem_preview = str(item.get("stem", ""))[:160]
        if item_type not in ALLOWED_TYPES:
            rejected.append({"position": position, "type": item_type, "stem": stem_preview,
                             "reason": f"Tip '{item_type}' nije dozvoljen pri doslovnom uvozu."})
            continue
        payload = item.get("payload")
        if isinstance(payload, dict) and item_type in ("mcq_single", "mcq_multi"):
            item["payload"] = {**payload, "shuffle": not keep_order}
        # Prepis nema varijacije - model ih ponekad doda iz navike.
        item.pop("variant_group", None)
        item.pop("variant_index", None)

        try:
            validated = contract.validate_one(item, script=script)
        except _VALIDATION_ERRORS as exc:
            rejected.append({"position": position, "type": item_type, "stem": stem_preview, "reason": str(exc)})
            continue

        if source is not None and strict:
            problem = _verbatim_guard(validated, source)
            if problem:
                rejected.append({"position": position, "type": item_type,
                                 "stem": validated["stem"][:160], "reason": problem})
                continue

        # Sken/slika nema tekst za proveru, pa SVE ide na proveru u fajlu.
        by_model = (
            str(item.get("answer_source") or "").strip().lower() == "model"
            or item_type == "long_answer"
            or source is None
        )
        validated["flags"] = {"flag_check_source": by_model}
        accepted.append(validated)

    return accepted, rejected


def _verbatim_guard(item: dict, haystack: str) -> Optional[str]:
    """Razlog odbijanja ili None. Tekst pitanja i svaki odgovor moraju da budu u izvoru."""
    if not _contains(haystack, item["stem"]):
        return "Tekst pitanja nije nadjen doslovno u fajlu - model ga je promenio ili izmislio."
    for option in item["payload"].get("options") or []:
        if not _contains(haystack, option):
            return f"Ponudjeni odgovor '{option[:60]}' nije nadjen doslovno u fajlu."
    return None


def _contains(haystack: str, needle: str) -> bool:
    """Cele reci: 'rektor' se ne sme naci u 'direktor'. Oba su vec kroz `_norm`."""
    return f" {_norm(needle)} " in f" {haystack} "


def _norm(text: str) -> str:
    """Poredjenje koje prezivi prelom reda, pismo, velicinu slova i interpunkciju.

    Reci ostaju razdvojene jednim razmakom da bi provera bila po celim recima;
    crtica na kraju reda (PDF prelom) se spaja.
    """
    value = translit.to_latin(text or "").lower()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = re.sub(r"-[ \t]*\n\s*", "", value)
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _describe(item: dict) -> dict:
    """Red za pregled: sta je prepoznato i koji je odgovor oznacen."""
    payload = item["payload"]
    correct = ""
    if item["type"] == "mcq_single":
        correct = payload["options"][payload["correct_index"]]
    elif item["type"] == "mcq_multi":
        correct = ", ".join(payload["options"][index] for index in payload["correct_indices"])
    elif item["type"] == "true_false":
        correct = "tačno" if payload["correct"] else "netačno"
    elif item["type"] == "short_answer":
        correct = (payload.get("accepted") or [""])[0]
    number = item["source_ref"].rsplit("pitanje", 1)[-1].strip() if "pitanje" in item["source_ref"] else ""
    return {
        "number": number,
        "stem": item["stem"],
        "type": item["type"],
        "options": payload.get("options") or [],
        "correct": correct,
    }


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "da", "yes", "on")


def _now() -> str:
    return db.scalar("SELECT datetime('now')")
