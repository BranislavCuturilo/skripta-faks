"""Predlozi za nadogradnju same aplikacije.

Zamisljeni tok: neko skine ovo kao osnovni template, koristi ga sa besplatnim
Gemini-jem, i u nekom trenutku zakljuci da mu osnovna verzija ne radi posao.
Tada ovde opise svojim recima sta mu fali, Gemini to prevede u konkretan nalog
(koji fajlovi, sta se menja, sta ne sme da se pokvari), i taj nalog se odnese u
placenog asistenta koji ume da napise kod.

Zato predlog i JESTE u gitu, za razliku od `data/`: on je polazna tacka izmene
koda, ne korisnicki podatak.

Sama aplikacija NIKAD ne primenjuje predlog. Pise ga, i tu joj se posao zavrsava.
"""

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from .. import config, db
from ..ai import contract, gemini, prompts
from ..http_util import HttpError
from . import ai_models, settings_store

FILE_PATTERN = re.compile(r"^predlog-(\d{4})-(.+)\.md$")

# Mapa projekta je ~250 redova; gornja granica postoji da neko ko je rucno
# nabudzi ne posalje pola megabajta u jedan poziv.
MAX_CONTEXT_CHARS = 120000


def context_text() -> str:
    """Mapa projekta koja ide AI-u. Generise se ako je nema."""
    if not config.CONTEXT_FILE.is_file():
        regenerate_context()
    if not config.CONTEXT_FILE.is_file():
        raise HttpError(
            500,
            "Nema mape projekta (predlozi/KONTEKST-ZA-AI.md). "
            "Pokreni `python mapa.py` u folderu aplikacije.",
        )
    return config.CONTEXT_FILE.read_text("utf-8", "replace")[:MAX_CONTEXT_CHARS]


def regenerate_context() -> bool:
    """Ponovo izgradi mapu iz koda. Vraca False ako mapa.py nije dostupan."""
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location("mapa", config.BASE_DIR / "mapa.py")
        if spec is None or spec.loader is None:
            return False
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        config.PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
        config.CONTEXT_FILE.write_text(module.build(), "utf-8")
        return True
    except Exception:  # noqa: BLE001 - mapa nije razlog da ekran padne
        return False


def list_all() -> list[dict]:
    if not config.PROPOSALS_DIR.is_dir():
        return []
    items = []
    for path in sorted(config.PROPOSALS_DIR.glob("predlog-*.md"), reverse=True):
        found = FILE_PATTERN.match(path.name)
        if not found:
            continue
        items.append(
            {
                "slug": path.stem,
                "number": int(found.group(1)),
                "title": _title_of(path),
                "size": path.stat().st_size,
                "created_at": datetime.fromtimestamp(
                    path.stat().st_mtime, timezone.utc
                ).strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
    return items


def read(slug: str) -> dict:
    path = _path_for(slug)
    return {"slug": slug, "title": _title_of(path), "text": path.read_text("utf-8", "replace")}


def delete(slug: str) -> None:
    _path_for(slug).unlink()


def create(request_text: str) -> dict:
    """Zamoli model da zahtev prevede u nalog za izmenu koda."""
    request_text = (request_text or "").strip()
    if len(request_text) < 15:
        raise HttpError(400, "Opiši malo detaljnije šta ti fali — bar rečenicu-dve.")

    api_key = settings_store.get("gemini_api_key", "")
    if not api_key:
        raise HttpError(400, "Nije unet Gemini API ključ. Podešavanja → AI.")

    result = ai_models.generate(
        "strong",
        prompts.build_proposal_prompt(
            context=context_text(),
            request=request_text,
            usage=_usage_summary(),
            language=settings_store.get("ui_language", "sr"),
        ),
        api_key=api_key,
        system=prompts.SYSTEM_PROPOSAL,
        json_output=True,
        temperature=0.4,
        purpose="proposal",
    )

    try:
        payload = json.loads(contract.strip_fence(result["text"]))
    except ValueError as exc:
        raise HttpError(502, f"Model nije vratio ispravan JSON: {exc}") from None
    if not isinstance(payload, dict) or not str(payload.get("title") or "").strip():
        raise HttpError(502, "Model nije vratio upotrebljiv predlog.")

    number = _next_number()
    slug = f"predlog-{number:04d}-{_slugify(payload['title'])}"
    path = config.PROPOSALS_DIR / f"{slug}.md"
    config.PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(_render(number, request_text, payload, result.get("model", "")), "utf-8")

    return {"slug": slug, "title": str(payload["title"]).strip(), "path": path.name,
            "feasible": bool(payload.get("feasible", True)),
            "text": path.read_text("utf-8", "replace")}


def create_manual(title: str, body: str) -> dict:
    """Predlog napisan rukom, bez AI-ja."""
    title = (title or "").strip()
    if not title:
        raise HttpError(400, "Naslov je obavezan.")
    number = _next_number()
    slug = f"predlog-{number:04d}-{_slugify(title)}"
    path = config.PROPOSALS_DIR / f"{slug}.md"
    config.PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# Predlog {number:04d} — {title}\n\n"
        f"- Datum: {_now()}\n- Napisao: korisnik\n\n---\n\n{body or ''}\n",
        "utf-8",
    )
    return {"slug": slug, "title": title, "path": path.name, "feasible": True,
            "text": path.read_text("utf-8", "replace")}


# --------------------------------------------------------------------------


def _render(number: int, request_text: str, payload: dict, model: str) -> str:
    def listing(key: str, empty: str) -> str:
        values = [str(item).strip() for item in (payload.get(key) or []) if str(item).strip()]
        return "\n".join(f"- {item}" for item in values) if values else empty

    files = payload.get("files") or []
    if isinstance(files, list) and files:
        rows = ["| Fajl | Šta se menja |", "|---|---|"]
        for item in files:
            if isinstance(item, dict):
                rows.append(f"| `{item.get('path', '?')}` | {item.get('change', '')} |")
            else:
                rows.append(f"| `{item}` | |")
        file_table = "\n".join(rows)
    else:
        file_table = "_Model nije naveo fajlove._"

    feasible = bool(payload.get("feasible", True))
    breaks = str(payload.get("breaks_rules") or "").strip()

    header = f"# Predlog {number:04d} — {str(payload['title']).strip()}\n"
    warning = ""
    if not feasible or breaks:
        warning = (
            "\n> **Pažnja:** ovo se ne uklapa u pravila projekta kako je traženo.\n"
            f"> {breaks or 'Model je označio zahtev kao neizvodljiv u ovom obliku.'}\n"
        )

    return f"""{header}{warning}
- Datum: {_now()}
- Predložio: {model or 'gemini'}
- Obim: {payload.get('effort', '?')}

## Šta si tražio

> {request_text.replace(chr(10), chr(10) + "> ")}

## Kako je model to razumeo

{str(payload.get('understood') or '—').strip()}

## Predloženo rešenje

{str(payload.get('approach') or '—').strip()}

## Fajlovi

{file_table}

## Ne sme da se pokvari

{listing('must_not_break', '_Model nije naveo ništa._')}

## Pitanja pre početka

{listing('questions', '_Nema — zahtev je bio dovoljno jasan._')}

---

## Nalog za AI asistenta

Ovo je deo koji kopiraš. Otvori plaćenog asistenta u folderu aplikacije,
priloži mu i `predlozi/KONTEKST-ZA-AI.md`, pa nalepi ovo:

```
{str(payload.get('claude_brief') or '').strip()}
```

---

*Napravila aplikacija. Ništa od ovoga nije primenjeno — kod menjaš ti, kroz git.*
"""


def _usage_summary() -> str:
    """Kratak profil korišćenja - da predlog bude vezan za stvarnu upotrebu."""
    counts = {
        "kategorija": db.scalar("SELECT COUNT(*) FROM category", default=0),
        "materijala": db.scalar("SELECT COUNT(*) FROM material", default=0),
        "pitanja": db.scalar("SELECT COUNT(*) FROM question", default=0),
        "odgovora": db.scalar("SELECT COUNT(*) FROM attempt", default=0),
        "sesija": db.scalar("SELECT COUNT(*) FROM study_session", default=0),
    }
    lines = [", ".join(f"{value} {key}" for key, value in counts.items())]

    types = db.query(
        "SELECT type, COUNT(*) AS n FROM question GROUP BY type ORDER BY n DESC LIMIT 8"
    )
    if types:
        lines.append("Najčešći tipovi pitanja: "
                     + ", ".join(f"{row['type']} ({row['n']})" for row in types))

    kinds = db.query(
        "SELECT kind, COUNT(*) AS n FROM material GROUP BY kind ORDER BY n DESC"
    )
    if kinds:
        lines.append("Vrste materijala: "
                     + ", ".join(f"{row['kind']} ({row['n']})" for row in kinds))

    failed = db.scalar(
        "SELECT COUNT(*) FROM material WHERE extraction_status IN ('remote_needed', 'failed')",
        default=0,
    )
    if failed:
        lines.append(f"Fajlova koje lokalno nismo pročitali: {failed}")

    errors = db.query(
        """
        SELECT error, COUNT(*) AS n FROM ai_call_log
         WHERE ok = 0 AND error <> '' GROUP BY error ORDER BY n DESC LIMIT 3
        """
    )
    if errors:
        lines.append("Najčešće greške AI poziva: "
                     + "; ".join(f"{row['error'][:120]} ({row['n']}×)" for row in errors))

    return "\n".join(lines)


def _next_number() -> int:
    existing = [item["number"] for item in list_all()]
    return (max(existing) + 1) if existing else 1


def _path_for(slug: str) -> Path:
    if not FILE_PATTERN.match(f"{slug}.md"):
        raise HttpError(400, "Neispravan naziv predloga.")
    path = (config.PROPOSALS_DIR / f"{slug}.md").resolve()
    try:
        path.relative_to(config.PROPOSALS_DIR.resolve())
    except ValueError:
        raise HttpError(400, "Neispravna putanja.") from None
    if not path.is_file():
        raise HttpError(404, "Predlog ne postoji.")
    return path


def _title_of(path: Path) -> str:
    try:
        for line in path.read_text("utf-8", "replace").splitlines():
            if line.startswith("# "):
                return line[2:].strip()
    except OSError:
        pass
    return path.stem


def _slugify(value: str) -> str:
    replacements = {"č": "c", "ć": "c", "š": "s", "ž": "z", "đ": "dj"}
    lowered = value.lower()
    for source, target in replacements.items():
        lowered = lowered.replace(source, target)
    lowered = unicodedata.normalize("NFKD", lowered).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return (slug or "predlog")[:60]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")
