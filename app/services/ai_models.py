"""Izbor modela u toku rada, sa samopopravljanjem.

Sve sto zove AI ide kroz `generate(tier, ...)` umesto da samo cita naziv iz
podesavanja. Cilj je da korisnik NIKAD ne mora da menja model rucno:

- **Automatski izbor se nigde ne upisuje.** U `model_<nivo>` stoji samo ono sto
  je korisnik sam izabrao; prazno znaci "automatski" i razresava se pri svakom
  pozivu iz spiska sa kljuca. Ranije je osvezavanje upisivalo razreseni naziv u
  to podesavanje, pa je "Automatski" posle prvog osvezavanja tiho postajao
  rucni izbor i vise se nikad nije menjao - ni kad izadje nova generacija.
- **Spisak se osvezava sam**, jednom dnevno (`STALE_AFTER_HOURS`), na startu i
  pred poziv. Nov model se koristi cim ga Google objavi.
- **Model koji ne radi sa ovim kljucem se preskace.** Nestao (404) ili bez
  besplatne kvote ("limit: 0") - pamti se na `UNUSABLE_DAYS` i ide sledeci
  najnoviji. Obicna potrosena kvota (429) jednog modela prelazi na drugi samo
  za taj poziv: svaki model ima svoju kvotu.

Rucni izbor se postuje, osim kad model nestane ili je iz familije koja se gasi;
tada se vraca na automatski i to se **prijavi**.
"""

import json
import threading
import time
from typing import Optional

from .. import db
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
UNUSABLE_KEY = "models_unusable"

AUTO = ("", "auto")

STALE_AFTER_HOURS = 24
UNUSABLE_DAYS = 7
# Najvise toliko zamena u jednom pozivu - posle toga je problem u kljucu ili
# mrezi, ne u modelu, i dalje probanje samo trosi kvotu.
MAX_SWITCHES = 2
# Kad osvezavanje ne uspe (nema mreze), ne pokusava se pred svaki poziv.
_RETRY_REFRESH_S = 3600.0

# Poruke iz kojih se vidi da je kriv MODEL, a ne zahtev.
_MISSING_MODEL_MARKERS = (
    "not found", "is not supported", "not available", "does not exist",
    "has been deprecated", "retired",
)

_refresh_lock = threading.Lock()
_last_refresh_attempt = 0.0


def available() -> list[str]:
    raw = settings_store.get(AVAILABLE_KEY, "")
    if isinstance(raw, list):
        return [str(item) for item in raw]
    try:
        parsed = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def manual_choice(tier: str) -> str:
    """Model koji je korisnik SAM izabrao za nivo, ili '' kad je automatski."""
    chosen = str(settings_store.get(SETTING_BY_TIER.get(tier, "model_standard"), "") or "").strip()
    return "" if chosen.lower() in AUTO else chosen


def unusable() -> dict[str, str]:
    """Modeli za koje se zna da ne rade sa ovim kljucem -> kada je to vidjeno."""
    raw = settings_store.get(UNUSABLE_KEY, "")
    try:
        parsed = json.loads(raw) if isinstance(raw, str) and raw else (raw or {})
    except (TypeError, ValueError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    cutoff = db.scalar("SELECT datetime('now', ?)", (f"-{UNUSABLE_DAYS} days",))
    return {str(name): str(seen) for name, seen in parsed.items() if str(seen) > cutoff}


def mark_unusable(name: str) -> None:
    marked = unusable()
    marked[name] = db.scalar("SELECT datetime('now')")
    settings_store.set_value(UNUSABLE_KEY, marked)


def for_tier(tier: str) -> str:
    """Naziv modela za dati nivo: izbor korisnika, pa najnoviji sa kljuca."""
    chosen = manual_choice(tier)
    if chosen:
        return chosen
    names = available()
    return (
        models.resolve(tier, names, skip=unusable())
        # Ako je sve oznaceno kao neupotrebljivo, bolje probati nego stati.
        or models.resolve(tier, names)
        or models.default_for(tier)
    )


def refresh(api_key: str = "") -> dict:
    """Procitaj spisak sa kljuca. Automatski izbori se time sami pomere."""
    api_key = api_key or settings_store.get("gemini_api_key", "")
    if not api_key:
        return {"ok": False, "error": "Nije unet API ključ."}

    before = {tier: for_tier(tier) for tier in models.TIERS}
    result = gemini.probe(api_key)
    if not result.get("ok"):
        return result

    names = [item["name"] for item in result.get("models", [])]
    settings_store.set_value(AVAILABLE_KEY, json.dumps(names, ensure_ascii=False))
    settings_store.set_value(CHECKED_KEY, _now())

    changes = []
    for tier in models.TIERS:
        current = manual_choice(tier)
        # Postovati izbor koji je nestao ili se gasi do trenutka kad poziv
        # pukne znaci pustiti korisnika da to otkrije usred ucenja.
        if current and (current not in names or models.is_retired(current)):
            settings_store.set_value(SETTING_BY_TIER[tier], "")
        now = for_tier(tier)
        if now != before[tier]:
            changes.append({"tier": tier, "from": before[tier], "to": now})

    return {"ok": True, "models": names, "count": len(names),
            "resolved": {tier: for_tier(tier) for tier in models.TIERS}, "changes": changes}


def refresh_if_stale(api_key: str = "") -> None:
    """Osvezi spisak ako je stariji od dana. Nikad ne baca - ovo je usput."""
    global _last_refresh_attempt

    api_key = api_key or settings_store.get("gemini_api_key", "")
    if not api_key:
        return
    checked = str(settings_store.get(CHECKED_KEY, "") or "")
    cutoff = db.scalar("SELECT datetime('now', ?)", (f"-{STALE_AFTER_HOURS} hours",))
    if checked and checked > cutoff:
        return
    with _refresh_lock:
        if time.monotonic() - _last_refresh_attempt < _RETRY_REFRESH_S:
            return
        _last_refresh_attempt = time.monotonic()
    refresh(api_key)


def status() -> dict:
    """Za ekran podesavanja: sta se koristi i da li je zastarelo."""
    names = available()
    tiers = []
    for tier in models.TIERS:
        name = for_tier(tier)
        tiers.append({
            "tier": tier,
            "model": name,
            "manual": bool(manual_choice(tier)),
            "retired": models.is_retired(name),
            "missing": bool(names) and name not in names,
        })
    return {
        "tiers": tiers,
        "available_count": len(names),
        "checked_at": settings_store.get(CHECKED_KEY, ""),
    }


def generate(tier: str, prompt: str, **kwargs) -> dict:
    """Poziv modelu za dati nivo; na gresku koja je do MODELA - sledeci model.

    Vraca i `model_switched` kad je model morao da se promeni, da pozivalac
    moze da to prijavi korisniku.
    """
    api_key = kwargs.pop("api_key", "") or settings_store.get("gemini_api_key", "")
    refresh_if_stale(api_key)

    automatic = not manual_choice(tier)
    model = kwargs.pop("model", "") or for_tier(tier)
    # Pozivalac je naziv razresio ranije (npr. na pocetku generisanja); ako je
    # u medjuvremenu oznacen kao neupotrebljiv, ne trosi se poziv na njega.
    if automatic and model in unusable():
        model = for_tier(tier)

    first = model
    switches = 0
    while True:
        try:
            result = gemini.generate(api_key, model, prompt, **kwargs)
        except gemini.AiError as exc:
            replacement = (
                _replacement(tier, model, exc, automatic, api_key)
                if switches < MAX_SWITCHES else None
            )
            if replacement is None:
                if _looks_like_missing_model(exc):
                    raise gemini.AiError(
                        f"Model '{model}' više nije dostupan za tvoj ključ, a zamena nije nađena. "
                        "Otvori Podešavanja → Modeli i izaberi ručno.",
                        status=exc.status,
                    ) from None
                raise
            model = replacement
            switches += 1
            continue
        switched = {"from": first, "to": model} if model != first else None
        return {**result, "model_switched": switched}


def _replacement(
    tier: str, model: str, exc: gemini.AiError, automatic: bool, api_key: str
) -> Optional[str]:
    """Sledeci model posle greske koja je do modela; None kad greska nije takva."""
    if _looks_like_missing_model(exc):
        mark_unusable(model)
        # Spisak je ocigledno zastareo. Rucni izbor koji je nestao vraca se na
        # automatski unutar `refresh`.
        refresh(api_key)
    elif not automatic:
        return None
    elif gemini.is_no_free_quota(exc):
        mark_unusable(model)
    elif exc.status != 429:
        return None

    return models.resolve(tier, available(), skip={*unusable(), model})


def _looks_like_missing_model(exc: gemini.AiError) -> bool:
    if exc.status not in (400, 403, 404):
        return False
    lowered = (exc.message or "").lower()
    return any(marker in lowered for marker in _MISSING_MODEL_MARKERS)


def _now() -> str:
    return db.scalar("SELECT datetime('now')")
