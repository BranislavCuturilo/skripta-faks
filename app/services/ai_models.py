"""Izbor modela u toku rada, sa samopopravljanjem.

Sve sto zove AI ide kroz `generate(tier, ...)` umesto da samo cita naziv iz
podesavanja. Razlog je konkretan: kad Google penzionise model, poziv vrati 404
i - ako se nista ne uradi - aplikacija prestane da radi uz poruku koja korisniku
ne znaci nista.

Ovako se, na tu gresku, spisak dostupnih modela procita ponovo sa kljuca, izbor
se prepravi i poziv se ponovi jednom. Korisnik vidi obavestenje sta je zamenjeno,
ne kvar.
"""

import json
from typing import Optional

from ..ai import gemini, models
from . import settings_store

SETTING_BY_TIER = {
    "fast": "model_fast",
    "standard": "model_standard",
    "strong": "model_strong",
    "tts": "model_tts",
}

AVAILABLE_KEY = "models_available"
CHECKED_KEY = "models_checked_at"

AUTO = ("", "auto")

# Poruke iz kojih se vidi da je kriv MODEL, a ne zahtev.
_MISSING_MODEL_MARKERS = (
    "not found", "is not supported", "not available", "does not exist",
    "has been deprecated", "retired",
)


def available() -> list[str]:
    raw = settings_store.get(AVAILABLE_KEY, "")
    if isinstance(raw, list):
        return [str(item) for item in raw]
    try:
        parsed = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def for_tier(tier: str) -> str:
    """Naziv modela za dati nivo: izbor korisnika, pa automatski, pa zelja."""
    chosen = str(settings_store.get(SETTING_BY_TIER.get(tier, "model_standard"), "") or "").strip()
    if chosen and chosen.lower() not in AUTO:
        return chosen
    return models.resolve(tier, available()) or models.default_for(tier)


def refresh(api_key: str = "") -> dict:
    """Procitaj spisak sa kljuca i prepravi automatske izbore."""
    api_key = api_key or settings_store.get("gemini_api_key", "")
    if not api_key:
        return {"ok": False, "error": "Nije unet API ključ."}

    result = gemini.probe(api_key)
    if not result.get("ok"):
        return result

    names = [item["name"] for item in result.get("models", [])]
    settings_store.set_value(AVAILABLE_KEY, json.dumps(names, ensure_ascii=False))
    settings_store.set_value(CHECKED_KEY, _now())

    resolved = models.resolve_all(names)
    changes = []
    for tier, name in resolved.items():
        setting = SETTING_BY_TIER[tier]
        current = str(settings_store.get(setting, "") or "").strip()
        manual = bool(current) and current.lower() not in AUTO

        # Rucni izbor se postuje - osim ako model vise ne postoji ILI je iz
        # familije koja se gasi. Postovati izbor do trenutka kad poziv pukne
        # znaci pustiti korisnika da to otkrije usred ucenja.
        if manual and current in names and not models.is_retired(current):
            continue
        if current == (name or ""):
            continue
        if name:
            settings_store.set_value(setting, name)
            changes.append({"tier": tier, "from": current or "(automatski)", "to": name})

    return {"ok": True, "models": names, "count": len(names),
            "resolved": resolved, "changes": changes}


def status() -> dict:
    """Za ekran podesavanja: sta se koristi i da li je zastarelo."""
    names = available()
    tiers = []
    for tier in models.TIERS:
        name = for_tier(tier)
        tiers.append({
            "tier": tier,
            "model": name,
            "manual": bool(str(settings_store.get(SETTING_BY_TIER[tier], "") or "").strip()
                           and str(settings_store.get(SETTING_BY_TIER[tier])).lower() not in AUTO),
            "retired": models.is_retired(name),
            "missing": bool(names) and name not in names,
        })
    return {
        "tiers": tiers,
        "available_count": len(names),
        "checked_at": settings_store.get(CHECKED_KEY, ""),
    }


def generate(tier: str, prompt: str, **kwargs) -> dict:
    """Poziv modelu za dati nivo, sa jednim pokusajem popravke.

    Vraca i `model_switched` kad je izbor morao da se promeni, da pozivalac
    moze da to prijavi korisniku.
    """
    api_key = kwargs.pop("api_key", "") or settings_store.get("gemini_api_key", "")
    model = kwargs.pop("model", "") or for_tier(tier)

    try:
        return {**gemini.generate(api_key, model, prompt, **kwargs), "model_switched": None}
    except gemini.AiError as exc:
        if not _looks_like_missing_model(exc):
            raise

        report = refresh(api_key)
        replacement = for_tier(tier)
        if not report.get("ok") or replacement == model:
            raise gemini.AiError(
                f"Model '{model}' više nije dostupan za tvoj ključ, a zamena nije nađena. "
                "Otvori Podešavanja → Modeli i izaberi ručno.",
                status=exc.status,
            ) from None

        result = gemini.generate(api_key, replacement, prompt, **kwargs)
        return {**result, "model_switched": {"from": model, "to": replacement}}


def _looks_like_missing_model(exc: gemini.AiError) -> bool:
    if exc.status not in (400, 403, 404):
        return False
    lowered = (exc.message or "").lower()
    return any(marker in lowered for marker in _MISSING_MODEL_MARKERS)


def _now() -> str:
    from .. import db

    return db.scalar("SELECT datetime('now')")
