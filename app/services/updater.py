"""Samo-azuriranje: provera nove verzije na GitHub-u i ugradnja preko sebe.

**Nova verzija je poslednji commit na `main`**, ne GitHub release. Prva verzija
je pitala `releases/latest`, a release se nikad ne pravi - odgovor je uvek bio
404, provera je uvek govorila "imas najnoviju", i azuriranje nikad nije radilo.
Koliko je instalacija iza, kaze `compare` od instaliranog commit-a do `main`-a.

Dve vrste instalacije, i svaka se azurira na svoj nacin (`install_kind`):

- **git kopija** (`.git/` postoji i git je na PATH-u): `git pull --ff-only`.
  ZIP preko git kopije bi ostavio izmenjene fajlove u radnom stablu, i sledeci
  `git pull` bi odbio da radi. `--ff-only` nikad ne spaja i ne brise lokalne
  izmene - kad ne moze cisto, odbije i kaze zasto.
- **ZIP instalacija** (`instaliraj.bat`, ili rucno raspakovano): app sama
  povuce ZIP i prepise svoje fajlove. Instalirani commit pamti `verzija.json`.

Dva pravila koja se ne krse:

1. `data/` se NIKAD ne dira. Tu su pitanja, napredak i materijali - jedina
   stvar u celom folderu koju korisnik ne moze da vrati ponovnim skidanjem.
2. Nista se ne prepisuje dok se ceo ZIP ne skine i ne raspakuje u stranu. Pola
   preuzimanja preko zive instalacije ostavlja aplikaciju koja se ne pokrece.

Sama zamena fajlova se ne radi iz servera koji tece: on je vec ucitao stari kod
i izvrsavao bi ga dalje, mesajuci ga sa novim. Zato se priprema radi ovde, a
zamenu izvodi `azuriraj.bat` pri sledecem startu (ili odmah, kad ga korisnik
pokrene duplim klikom).
"""

import json
import os
import re
import shutil
import ssl
import subprocess
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

from .. import __version__, config

GITHUB_OWNER = "BranislavCuturilo"
GITHUB_REPO = "skripta-faks"
BRANCH = "main"

REPO_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"
API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"
COMMITS_URL = f"{API_URL}/commits/{BRANCH}"
COMPARE_URL = API_URL + "/compare/{base}..." + BRANCH
ZIP_URL = f"{REPO_URL}/archive/refs/heads/{BRANCH}.zip"

USER_AGENT = f"skripta-faks/{__version__}"
TIMEOUT = 30
GIT_TIMEOUT = 120

# Folderi koje ugradnja nikad ne pise, ma sta stiglo u ZIP-u.
PROTECTED = {"data", ".git", "__pycache__"}

# Preuzeta verzija ceka ovde dok je `azuriraj.bat` ne ugradi.
STAGING_DIRNAME = ".update"
MARKER_NAME = "spremno.json"
UNPACKED_NAME = "novo"
# Prazan fajl koji `azuriraj.bat` vidi bez citanja JSON-a: ugradnja je git pull.
GIT_MARKER_NAME = "git"

# Instalirani commit ZIP instalacije. Git kopija ga cita iz `.git/`.
INSTALLED_NAME = "verzija.json"

_SHA = re.compile(r"[0-9a-f]{40}")
_NOTES_LIMIT = 30


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


def install_kind() -> str:
    """'git' kad se azurira git-om, inace 'zip'."""
    if (config.BASE_DIR / ".git").is_dir() and shutil.which("git"):
        return "git"
    return "zip"


def installed_commit() -> str:
    """Commit koji je instaliran, ili '' kad se ne zna (sveza ZIP instalacija)."""
    head = _git_head(config.BASE_DIR / ".git")
    if head:
        return head
    try:
        data = json.loads((config.BASE_DIR / INSTALLED_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    sha = str(data.get("sha") or "") if isinstance(data, dict) else ""
    return sha if _SHA.fullmatch(sha) else ""


def check() -> dict:
    """Ima li novije verzije. Nikad ne baca - provera ne sme da obori ekran."""
    local = installed_commit()
    result = {
        "ok": True,
        "current": f"{__version__} · {local[:7] or 'commit nepoznat'}",
        "installed": local,
        "kind": install_kind(),
        "latest": None,
        "latest_sha": "",
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
        head = _github_json(COMMITS_URL)
    except UpdateError as exc:
        result["error"] = str(exc)
        return result
    remote = str((head or {}).get("sha") or "")
    if not _SHA.fullmatch(remote):
        result["error"] = "GitHub nije vratio poslednju verziju."
        return result

    result["latest_sha"] = remote
    result["latest"] = _describe(head)
    result["notes"] = _subject(head)
    if remote == local:
        return result
    if not local:
        # ZIP instalacija iz vremena pre `verzija.json`: ne zna se sta je
        # instalirano, pa se nudi najnovije - posle toga se zna.
        result["available"] = True
        return result

    try:
        compared = _github_json(COMPARE_URL.format(base=local))
    except UpdateError as exc:
        result["error"] = str(exc)
        return result
    if compared is None:
        # GitHub ne zna instalirani commit: lokalne izmene koje nisu poslate.
        # Takvoj kopiji se nista ne nudi - git pull bi je samo zbunio.
        return result
    if compared.get("status") in ("ahead", "diverged"):
        commits = list(reversed(compared.get("commits") or []))[:_NOTES_LIMIT]
        result["available"] = True
        result["notes"] = "\n".join(f"- {_subject(item)}" for item in commits) or result["notes"]
        result["url"] = compared.get("html_url") or result["url"]
    return result


def _github_json(url: str) -> Optional[dict]:
    """JSON sa GitHub API-ja; None na 404, UpdateError na sve ostalo."""
    try:
        with _open(url, accept="application/vnd.github+json") as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        if exc.code == 403:
            raise UpdateError("GitHub privremeno ne odgovara (ogranicenje upita). "
                              "Probaj ponovo za sat vremena.") from exc
        raise UpdateError(f"GitHub je odgovorio {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise UpdateError(f"Nema veze sa internetom ili GitHub ne odgovara ({exc}).") from exc
    return payload if isinstance(payload, dict) else None


def _describe(commit: dict) -> str:
    sha = str(commit.get("sha") or "")[:7]
    date = str(((commit.get("commit") or {}).get("committer") or {}).get("date") or "")[:10]
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        year, month, day = date.split("-")
        return f"{sha} od {day}.{month}.{year}."
    return sha


def _subject(commit: dict) -> str:
    message = str((commit.get("commit") or {}).get("message") or "")
    return message.strip().splitlines()[0] if message.strip() else ""


def _git_head(git_dir: Path) -> str:
    """HEAD git kopije iz samih fajlova - bez git-a, koji ne mora da postoji."""
    try:
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if not head.startswith("ref:"):
        return head if _SHA.fullmatch(head) else ""
    ref = head[len("ref:"):].strip()
    try:
        sha = (git_dir / ref).read_text(encoding="utf-8").strip()
        if _SHA.fullmatch(sha):
            return sha
    except OSError:
        pass
    try:
        for line in (git_dir / "packed-refs").read_text(encoding="utf-8").splitlines():
            sha, _, name = line.partition(" ")
            if name.strip() == ref and _SHA.fullmatch(sha):
                return sha
    except OSError:
        pass
    return ""


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
    """Pripremi novu verziju da ceka restart. `version` je commit sa GitHub-a.

    Nista se u ovom trenutku ne prepisuje. Zamena je posao `azuriraj.bat`-a i
    desava se kad server vise ne tece. Git kopija se ne preuzima ovde: pri
    startu je azurira `git pull`, pa se samo ostavi oznaka.
    """
    current = installed_commit()[:7] or "nepoznata"
    if install_kind() == "git":
        discard()
        staging_dir().mkdir(parents=True)
        (staging_dir() / GIT_MARKER_NAME).write_text("", encoding="utf-8")
        info = {"version": version[:7] or "najnovija", "from": current, "mode": "git"}
    else:
        archive = download(url, on_progress)
        sha = _archive_commit(archive) or (version if _SHA.fullmatch(version or "") else "")
        folder = extract(archive)
        archive.unlink(missing_ok=True)
        # Ide u koren aplikacije zajedno sa kodom - sledeca provera tako zna
        # sta je instalirano.
        (folder / INSTALLED_NAME).write_text(json.dumps({"sha": sha}), encoding="utf-8")
        info = {"version": sha[:7] or "najnovija", "from": current, "mode": "zip",
                "folder": str(folder)}

    (staging_dir() / MARKER_NAME).write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return info


def _archive_commit(archive: Path) -> str:
    """GitHub upisuje commit u komentar ZIP arhive - tacniji od upita pre
    preuzimanja, jer je `main` mogao da se pomeri izmedju ta dva poziva."""
    try:
        with zipfile.ZipFile(archive) as zip_file:
            comment = zip_file.comment.decode("ascii", "ignore").strip()
    except (zipfile.BadZipFile, OSError):
        return ""
    return comment if _SHA.fullmatch(comment) else ""


def git_pull() -> tuple[bool, str]:
    """`git pull --ff-only` u folderu aplikacije. Nikad ne spaja i ne brise."""
    try:
        done = subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=config.BASE_DIR,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
            # Bez ovoga bi git na pokvarenoj vezi cekao lozinku koju niko ne kuca.
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"git nije uspeo da se pokrene: {exc}"
    output = (done.stdout + done.stderr).strip()
    return done.returncode == 0, output


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
    if info.get("mode") == "git":
        discard()
        ok, output = git_pull()
        if not ok:
            print(f"  git pull nije uspeo - pokrecem staru verziju.\n{output}")
            return None
        return info

    source = Path(info.get("folder", ""))
    if not source.is_dir():
        discard()
        return None

    apply_tree(source, config.BASE_DIR)
    discard()
    return info


def main() -> int:
    """`azuriraj.bat` pokrenut rucno u ZIP instalaciji: pripremi najnoviju verziju.

    Ugradnju posle toga radi sam .bat (robocopy). Git kopiju .bat azurira sam,
    bez ovoga. Poruke su bez nasih slova - konzola ih ne prikazuje uvek.
    """
    state = check()
    if state["error"]:
        print(f"  [X] {state['error']}")
        return 1
    if not state["available"]:
        print(f"  Vec imas najnoviju verziju ({state['current']}).")
        return 0
    print(f"  Preuzimam verziju {state['latest']}")
    try:
        prepare(state["latest_sha"], state["download"])
    except UpdateError as exc:
        print(f"  [X] {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
