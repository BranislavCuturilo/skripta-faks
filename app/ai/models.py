"""Koji se model zove za koji posao.

Nazivi Gemini modela se menjaju brze nego sto se ova aplikacija azurira. Kad su
bili tvrdo upisani (`gemini-2.5-flash`), Google ih je penzionisao i aplikacija
je prestala da radi bez ijedne poruke koja bi rekla zasto.

Zato ovde nema jednog naziva nego REDOSLED ZELJA po nivou. Pravi izbor se radi
u toku rada, iz spiska koji vrati sam kljuc korisnika:

1. uzmi prvi iz liste zelja koji taj kljuc stvarno ima
2. ako nijedan ne postoji (Google je opet preimenovao sve), izaberi heuristikom
   iz onoga sto postoji - najveca verzija, pa odgovarajuca familija

Drugi korak je ono zbog cega ovo prezivljava sledece preimenovanje.
"""

import re
from typing import Iterable, Optional

TIERS = ("fast", "standard", "strong", "tts")

# Stanje na dan 13.08.2026. Novije ide prvo. Stari nazivi ostaju na dnu jer
# poneki kljuc jos uvek ima pristup samo njima.
PREFERRED: dict[str, list[str]] = {
    # sitni poslovi - najjeftinije sto radi posao
    "fast": [
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-3.6-flash",
        "gemini-2.5-flash-lite",
    ],
    # generisanje pitanja i ocenjivanje - glavni radni konj
    "standard": [
        "gemini-3.6-flash",
        "gemini-3.7-flash",
        "gemini-3.5-flash",
        "gemini-2.5-flash",
    ],
    # foto-zadaci, tesko ocenjivanje, predlozi za nadogradnju
    "strong": [
        "gemini-3.7-flash",
        "gemini-3.1-pro-preview",
        "gemini-3.6-flash",
        "gemini-2.5-pro",
    ],
    "tts": [
        "gemini-3.1-flash-tts-preview",
        "gemini-2.5-flash-preview-tts",
        "gemini-2.5-pro-preview-tts",
    ],
}

# Modeli koji nisu za tekst: slika, video, ugradjivanje, zivi audio.
_NOT_TEXT = ("image", "imagen", "veo", "embedding", "embed", "aqa", "live", "native-audio")

_VERSION = re.compile(r"gemini-(\d+(?:\.\d+)?)")


def preferred(tier: str) -> list[str]:
    return list(PREFERRED.get(tier, PREFERRED["standard"]))


def default_for(tier: str) -> str:
    """Sta se koristi dok spisak sa kljuca jos nije procitan."""
    return preferred(tier)[0]


def resolve(tier: str, available: Iterable[str]) -> Optional[str]:
    """Najbolji model za dati nivo iz onoga sto kljuc stvarno ima."""
    names = [str(item) for item in available if item]
    if not names:
        return None

    existing = set(names)
    for candidate in preferred(tier):
        if candidate in existing:
            return candidate

    # Nijedan poznat naziv - Google je preimenovao familiju. Biraj po obliku.
    ranked = sorted(
        (name for name in names if _fits(tier, name)),
        key=lambda name: _score(tier, name),
        reverse=True,
    )
    return ranked[0] if ranked else None


def resolve_all(available: Iterable[str]) -> dict[str, Optional[str]]:
    names = list(available)
    return {tier: resolve(tier, names) for tier in TIERS}


def is_retired(name: str) -> bool:
    """Da li je model iz familije koja se gasi - da UI moze da upozori."""
    version = _version_of(name)
    return version is not None and version < 3.0


def _fits(tier: str, name: str) -> bool:
    lowered = name.lower()
    if tier == "tts":
        return "tts" in lowered
    if "tts" in lowered:
        return False
    return not any(marker in lowered for marker in _NOT_TEXT)


def _version_of(name: str) -> Optional[float]:
    found = _VERSION.search(name.lower())
    if not found:
        return None
    try:
        return float(found.group(1))
    except ValueError:
        return None


def _score(tier: str, name: str) -> tuple:
    lowered = name.lower()
    version = _version_of(lowered) or 0.0
    is_lite = "lite" in lowered
    is_pro = "pro" in lowered
    is_preview = "preview" in lowered

    if tier == "fast":
        shape = 2 if is_lite else (1 if not is_pro else 0)
    elif tier == "strong":
        shape = 2 if is_pro else (0 if is_lite else 1)
    else:
        shape = 0 if is_lite else (2 if not is_pro else 1)

    # Stabilno pre preview-a kad je sve ostalo isto.
    return (shape, version, 0 if is_preview else 1, -len(name))
