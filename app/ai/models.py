"""Koji se model zove za koji posao.

Nazivi Gemini modela se menjaju brze nego sto se ova aplikacija azurira. Kad su
bili tvrdo upisani (`gemini-2.5-flash`), Google ih je penzionisao i aplikacija
je prestala da radi bez ijedne poruke koja bi rekla zasto.

Zato se ovde ne bira po nazivu nego po OBLIKU, iz spiska koji vrati sam kljuc
korisnika: uvek NAJNOVIJI stabilan model odgovarajuce familije. Kad Google
izbaci novu generaciju, ona se koristi cim se spisak osvezi - bez izmene koda i
bez ijednog klika korisnika.

Redosled (`_score`), od najvaznijeg:
1. naziv sa verzijom (alias `gemini-flash-latest` ne kaze verziju, pa ni koje
   polje za razmisljanje prima)
2. stabilan pre preview-a - preview obicno nema besplatnu kvotu ("limit: 0")
3. najnovija generacija (4.x pre 3.x)
4. oblik za nivo (lite za brzi, pro za najjaci, obican flash za standardni)
5. najveca verzija unutar generacije

`PREFERRED` je samo za trenutak pre nego sto je spisak sa kljuca procitan.
"""

import re
from typing import Iterable, Optional

TIERS = ("fast", "standard", "strong", "tts")

# Samo dok spisak sa kljuca jos nije procitan (prvo pokretanje, bez mreze).
# Cim spisak stigne, bira se po obliku iz njega - ova lista tada ne vazi.
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

# Modeli koji nisu za tekst: slika, video, ugradjivanje, zivi audio, upravljanje
# racunarom i robotima.
_NOT_TEXT = ("image", "imagen", "veo", "embedding", "embed", "aqa", "live", "native-audio",
             "computer-use", "robotics")

_VERSION = re.compile(r"gemini-(\d+(?:\.\d+)?)")
_UNSTABLE = re.compile(r"(?:^|-)(?:preview|exp|experimental)(?:-|$)")


def preferred(tier: str) -> list[str]:
    return list(PREFERRED.get(tier, PREFERRED["standard"]))


def default_for(tier: str) -> str:
    """Sta se koristi dok spisak sa kljuca jos nije procitan."""
    return preferred(tier)[0]


def ranked(tier: str, available: Iterable[str]) -> list[str]:
    """Svi modeli sa kljuca koji odgovaraju nivou, od najboljeg ka najgorem."""
    names = {str(item) for item in available if item}
    return sorted(
        (name for name in names if _fits(tier, name)),
        key=lambda name: _score(tier, name),
        reverse=True,
    )


def resolve(tier: str, available: Iterable[str], skip: Iterable[str] = ()) -> Optional[str]:
    """Najbolji model za dati nivo iz onoga sto kljuc stvarno ima.

    `skip` su modeli za koje se zna da ne rade sa ovim kljucem (nema besplatne
    kvote, nestali su) - preskacu se, pa ide sledeci najnoviji.
    """
    skipped = set(skip)
    for name in ranked(tier, available):
        if name not in skipped:
            return name
    return None


def resolve_all(available: Iterable[str]) -> dict[str, Optional[str]]:
    names = list(available)
    return {tier: resolve(tier, names) for tier in TIERS}


def is_preview(name: str) -> bool:
    return bool(_UNSTABLE.search(name.lower()))


def is_retired(name: str) -> bool:
    """Da li je model iz familije koja se gasi - da UI moze da upozori."""
    version = _version_of(name)
    return version is not None and version < 3.0


def thinking_config(name: str, level: str) -> Optional[dict]:
    """`thinkingConfig` koji trazi "malo razmisljanja" od datog modela.

    Gemini 2.5+ podrazumevano razmislja pre odgovora, i to razmisljanje ide u
    `maxOutputTokens`. Kod ocenjivanja je to bilo i sporo (desetine sekundi) i
    opasno: misli pojedu budzet, JSON izadje odsecen i provera padne. Dve
    generacije imaju razlicito polje za isto, pa se bira po verziji.
    """
    if level != "low":
        return None
    version = _version_of(name)
    if version is None:
        return None
    if version >= 3.0:
        return {"thinkingLevel": "low"}
    if version >= 2.5:
        # 2.5 pro ne moze da iskljuci razmisljanje - 128 je najmanje sto prima.
        return {"thinkingBudget": 128 if "pro" in name.lower() else 0}
    return None


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
    """Kljuc za poredjenje - redosled je objasnjen na vrhu modula."""
    lowered = name.lower()
    version = _version_of(lowered)
    is_lite = "lite" in lowered
    is_pro = "pro" in lowered

    if tier == "fast":
        shape = 2 if is_lite else (1 if not is_pro else 0)
    elif tier == "strong":
        shape = 2 if is_pro else (0 if is_lite else 1)
    else:
        shape = 0 if is_lite else (2 if not is_pro else 1)

    return (
        version is not None,
        not is_preview(lowered),
        int(version or 0),
        shape,
        version or 0.0,
        -len(name),
    )
