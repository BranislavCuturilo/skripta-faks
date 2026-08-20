"""Samo-azuriranje: provera nove verzije na GitHub-u i ugradnja preko sebe.

Zasto ovako, a ne `git pull`: aplikaciju preuzima i neko ko nema git, ko je
skinuo ZIP i raspakovao ga. Jedini nacin koji radi za SVE korisnike je da app
sama povuce ZIP i prepise svoje fajlove.

Dva pravila koja se ne krse:

1. `data/` se NIKAD ne dira. Tu su pitanja, napredak i materijali - jedina
   stvar u celom folderu koju korisnik ne moze da vrati ponovnim skidanjem.
2. Nista se ne prepisuje dok se ceo ZIP ne skine i ne raspakuje u stranu. Pola
   preuzimanja preko zive instalacije ostavlja aplikaciju koja se ne pokrece.

Sama zamena fajlova ne moze da se odradi iz procesa koji tece: na Windows-u je
`app/*.py` vec ucitan, a python.exe drzi folder. Zato se priprema radi ovde, a
zamenu izvodi `azuriraj.bat` pri sledecem startu - kad aplikacija vise ne drzi
nijedan svoj fajl.
"""

import json
import os
import shutil
import ssl
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

from .. import __version__, config

GITHUB_OWNER = "BranislavCuturilo"
GITHUB_REPO = "skripta-faks"

REPO_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"
RELEASES_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
ZIP_URL = f"{REPO_URL}/archive/refs/heads/main.zip"

USER_AGENT = f"skripta-faks/{__version__}"
TIMEOUT = 30

# Folderi koje ugradnja nikad ne pise, ma sta stiglo u ZIP-u.
PROTECTED = {"data", ".git", "__pycache__"}

# Preuzeta verzija ceka ovde dok je `azuriraj.bat` ne ugradi.
STAGING_DIRNAME = ".update"
MARKER_NAME = "spremno.json"
UNPACKED_NAME = "novo"


class UpdateError(Exception):
    """Greska koju API pretvara u citljivu poruku korisniku."""


def staging_dir() -> Path:
    return config.BASE_DIR / STAGING_DIRNAME


def _network_blocked() -> bool:
    """Isti prekidac koji cuva AI pozive cuva i ovaj.

    Bez ovoga bi `python run_tests.py` udarao na GitHub API na svakom
    pokretanju suite-a - sporo, i podlozno rate-limitu.
    """
    return bool(os.environ.get("SKRIPTA_BLOCK_NETWORK"))


def _open(url: str, accept: str = "*/*"):
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": accept}
    )
    return urllib.request.urlopen(
        request, timeout=TIMEOUT, context=ssl.create_default_context()
    )


def parse_version(text: str) -> tuple:
    """'v1.2.3' -> (1, 2, 3). Nebrojevi prekidaju, pa 'main' ostane ().

    Poredjenje mora da bude numericko: kao tekst je '0.10.0' < '0.9.0', pa bi
    aplikacija tvrdila da je novija verzija starija.
    """
    cleaned = (text or "").strip().lstrip("vV")
    parts: list[int] = []
    for chunk in cleaned.split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def is_newer(remote: str, local: str) -> bool:
    remote_parts = parse_version(remote)
    if not remote_parts:
        return False
    return remote_parts > parse_version(local)


def check() -> dict:
    """Ima li novije verzije. Nikad ne baca - provera ne sme da obori ekran."""
    result = {
        "ok": True,
        "current": __version__,
        "latest": None,
        "available": False,
        "notes": "",
        "url": REPO_URL,
        "download": ZIP_URL,
        "pending": pending_info(),
        "error": "",
    }
    if _network_blocked():
        result["error"] = "Mrezne provere su iskljucene."
        return result

    try:
        with _open(RELEASES_URL, accept="application/vnd.github+json") as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # 404 = repo postoji ali jos nema nijedan release. To nije greska koju
        # korisnik treba da vidi kao crveno, nego "nema novije verzije".
        if exc.code == 404:
            return result
        result["error"] = f"GitHub je odgovorio {exc.code}."
        return result
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        result["error"] = f"Nema veze sa internetom ili GitHub ne odgovara ({exc})."
        return result

    tag = (payload.get("tag_name") or "").strip()
    result["latest"] = tag or None
    result["notes"] = (payload.get("body") or "").strip()[:4000]
    if payload.get("html_url"):
        result["url"] = payload["html_url"]
    if payload.get("zipball_url"):
        result["download"] = payload["zipball_url"]
    result["available"] = is_newer(tag, __version__)
    return result


def pending_info() -> Optional[dict]:
    """Sta ceka da bude ugradjeno pri sledecem startu, ako nesto ceka."""
    marker = staging_dir() / MARKER_NAME
    if not marker.is_file():
        return None
    try:
        return json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def download(url: str, on_progress=None) -> Path:
    """Skine ZIP u staging folder i vrati putanju do njega."""
    target_dir = staging_dir()
    shutil.rmtree(target_dir, ignore_errors=True)
    target_dir.mkdir(parents=True, exist_ok=True)
    archive = target_dir / "verzija.zip"

    try:
        with _open(url) as response:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            with archive.open("wb") as handle:
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    done += len(chunk)
                    if on_progress:
                        on_progress(done, total)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise UpdateError(f"Preuzimanje nije uspelo: {exc}") from exc

    return archive


def _safe_members(archive: zipfile.ZipFile, root: str) -> list:
    """Clanovi ZIP-a koje smemo da raspakujemo.

    Odbacuje apsolutne putanje i `..` (zip slip): raspakivanje na tudju putanju
    pisalo bi van foldera aplikacije. GitHub-ov ZIP jeste bezbedan, ali ovo je
    jedina odbrana koja vazi i ako se URL jednog dana promeni.
    """
    picked = []
    for name in archive.namelist():
        if name.endswith("/"):
            continue
        relative = name[len(root):] if root and name.startswith(root) else name
        relative = relative.lstrip("/")
        if not relative:
            continue
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts:
            continue
        if path.parts[0] in PROTECTED:
            continue
        picked.append((name, relative))
    return picked


def extract(archive: Path) -> Path:
    """Raspakuje ZIP u `<staging>/novo/` i vrati taj folder.

    GitHub pakuje sve u jedan koreni folder (`skripta-faks-main/`); on se skida
    ovde, da bi `novo/` sadrzao tacno ono sto ide u koren aplikacije.
    """
    destination = staging_dir() / UNPACKED_NAME
    shutil.rmtree(destination, ignore_errors=True)
    destination.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(archive) as zip_file:
            names = zip_file.namelist()
            if not names:
                raise UpdateError("Preuzeta arhiva je prazna.")
            first = names[0].split("/")[0]
            root = f"{first}/" if all(n.startswith(f"{first}/") for n in names) else ""

            members = _safe_members(zip_file, root)
            if not members:
                raise UpdateError("Preuzeta arhiva ne sadrzi nijedan upotrebljiv fajl.")

            for name, relative in members:
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with zip_file.open(name) as source, target.open("wb") as handle:
                    shutil.copyfileobj(source, handle)
    except zipfile.BadZipFile as exc:
        raise UpdateError("Preuzeta arhiva je ostecena.") from exc

    # Provera pre nego sto ovo dobije pravo da prepise zivu instalaciju: ako
    # arhiva nije ono sto mislimo da jeste, ugradnja pravi folder koji se ne
    # pokrece, a korisnik nema odakle da se vrati.
    if not (destination / "run.py").is_file() or not (destination / "app").is_dir():
        raise UpdateError(
            "Preuzeta arhiva ne lici na skripta-faks (nema run.py ili app/). "
            "Nista nije promenjeno."
        )
    return destination


def prepare(version: str, url: str, on_progress=None) -> dict:
    """Skine i raspakuje novu verziju, i ostavi je da ceka restart.

    Nista se u ovom trenutku ne prepisuje. Zamena je posao `azuriraj.bat`-a i
    desava se kad aplikacija vise ne drzi nijedan svoj fajl.
    """
    archive = download(url, on_progress)
    folder = extract(archive)
    archive.unlink(missing_ok=True)

    info = {
        "version": version or "nepoznata",
        "from": __version__,
        "folder": str(folder),
    }
    (staging_dir() / MARKER_NAME).write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return info


def discard() -> None:
    """Odustajanje: pripremljena verzija se brise, instalacija ostaje ista."""
    shutil.rmtree(staging_dir(), ignore_errors=True)


def apply_tree(source: Path, destination: Path) -> int:
    """Kopira `source` preko `destination`, preskacuci zasticene foldere.

    Kopira, ne zamenjuje folder: fajl obrisan u novoj verziji ostaje na disku,
    ali nista korisnikovo ne moze da nestane. Za aplikaciju bez zavisnosti to
    je dobra pogodba - visak .py fajla ne kosta nikoga.
    """
    count = 0
    for item in source.rglob("*"):
        if item.is_dir():
            continue
        relative = item.relative_to(source)
        if relative.parts[0] in PROTECTED:
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        count += 1
    return count


def install_pending() -> Optional[dict]:
    """Ugradi ono sto ceka. Zove se sa STARTA, pre uvoza ostatka aplikacije.

    Postoji zbog Linux-a i macOS-a, gde `azuriraj.bat` ne postoji. Na Windows-u
    posao odradi .bat pre nego sto Python uopste krene, pa ova funkcija tamo
    obicno nema sta da nadje.
    """
    info = pending_info()
    if not info:
        return None
    source = Path(info.get("folder", ""))
    if not source.is_dir():
        discard()
        return None

    apply_tree(source, config.BASE_DIR)
    discard()
    return info
