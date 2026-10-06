#!/usr/bin/env python3
"""Generiše `predlozi/KONTEKST-ZA-AI.md` iz stvarnog koda.

Pokretanje: `python mapa.py`

Mapa projekta koja se piše ručno zastari prvim sledećim commit-om, i onda AI
koji je čita menja fajlove koji više ne postoje. Zato se ovde ništa ne prepisuje
napamet: spisak fajlova, njihovi opisi, rute, tabele baze i tipovi pitanja se
čitaju iz koda koji stvarno postoji.

Pokreni ovo posle svake veće izmene, pa commit-uj rezultat.
"""

import ast
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from app import db  # noqa: E402
from app.quiz import types as question_types  # noqa: E402
from app.router import router  # noqa: E402
import app.api  # noqa: E402,F401  - uvoz puni ruter


HEADER = """\
# Kontekst za AI

> **Ovaj fajl se ne piše ručno.** Generiše ga `python mapa.py` iz stvarnog koda.
> Ako si ga menjao rukom, sledeće pokretanje briše tvoje izmene — piši u
> `predlozi/`, ne ovde.

Ovo je mapa projekta namenjena AI asistentu koji treba da izmeni ovu aplikaciju.
Nalepi je (ili je priloži kao fajl) uz svoj zahtev, pa asistent zna gde šta stoji
i šta sme, umesto da nagađa.

---

## Šta je ovaj projekat

**skripta-faks** — lokalna aplikacija za učenje i obnavljanje gradiva uz pomoć
AI-ja. Korisnik pravi kategorije (predmet → kolokvijum → oblast, u nedogled),
ubacuje materijale (PDF, Word, slike, snimci), napiše šta se tačno uči, i sistem
od toga generiše pitanja i ispituje ga — forsirajući ono što greši.

Radi na localhost-u. Pokreće se duplim klikom na `START.bat`.

---

## Pravila koja se ne krše

Ovo nisu preporuke. Izmena koja prekrši nešto od ovoga ruši ono zbog čega
aplikacija uopšte ovako izgleda.

1. **Nula spoljnih zavisnosti.** Nema `pip install`, nema `requirements.txt`,
   nema CDN-a u HTML-u. Sve je standardna biblioteka Pythona i običan browser.
   Ako rešenje traži biblioteku — ili ga napiši standardnom bibliotekom, ili
   izričito kaži korisniku da to menja osnovnu odluku projekta.

2. **AI nikad ne menja izvorni kod aplikacije u toku rada.** Adaptivnost živi u
   tabeli `strategy` (raspodela tipova pitanja, težina, teme u fokusu). Kod menja
   samo čovek, kroz git.

3. **Sva pitanja ulaze u bazu kroz `app/ai/contract.py`.** I odgovor Gemini-ja i
   ručno nalepljen odgovor iz drugog modela i ručna izmena u UI-ju — sve prolazi
   kroz `validate_one`. Nema drugog puta.

4. **Sve stanje je u SQLite fajlu `data/skripta.db`.** Šema se menja isključivo
   dodavanjem nove migracije u `MIGRATIONS` listu u `app/db.py`. Postojeće
   migracije se ne diraju — one su već primenjene kod korisnika.

5. **Media se nikad ne servira inline osim slika, zvuka, videa i PDF-a.**
   Uploadovan `.html` ili `.svg` posluženi inline su skladišteni XSS sa istim
   origin-om kao aplikacija.

6. **API ključ ne izlazi iz servera u celini** i ne ide u URL — samo u zaglavlje
   `x-goog-api-key`.

7. **Testovi se pokreću sa `python run_tests.py`**, ne pytest-om. Svaka izmena
   ponašanja ide sa testom.

---
"""

FOOTER = """
---

## Gde se šta menja

| Hoću da... | Diram |
|---|---|
| dodam novi tip pitanja | `app/quiz/types.py` (registar + validator), `app/quiz/grading.py` (ocenjivač), `web/js/render.js` (crtanje) — sva tri, uvek |
| promenim kako se bira sledeće pitanje | `app/quiz/scheduler.py` |
| promenim šta se šalje modelu | `app/ai/prompts.py` |
| promenim koliko dugo se čeka na AI ocenu | konstante `GRADE_*` na vrhu `app/services/study.py` |
| dodam kolonu ili tabelu | nova migracija na kraj `MIGRATIONS` u `app/db.py` |
| dodam ekran | `web/js/views/*.js` + ruta u `web/js/app.js` (`TABS` ili `route()`) |
| dodam API rutu | `app/api/*.py` (tanko) + `app/services/*.py` (logika) |
| podržim novi format fajla | `app/extract/` + `kind_for()` i liste u `app/config.py` |
| promenim izgled | `web/css/style.css` — boje isključivo kroz CSS promenljive |

## Kako da ti zahtev bude izvodljiv

- Reci **šta te muči**, ne kako da se to reši. „Pitanja su prelaka" je bolji
  zahtev od „promeni temperaturu na 0.9".
- Reci **na kom ekranu** si to primetio i **šta si očekivao** da se desi.
- Ako je nešto puklo, priloži tekst greške iz konzole (crni prozor koji ostaje
  otvoren dok app radi).
- Kaži šta **ne sme** da se pokvari — npr. „samo nemoj da mi obrišeš pitanja
  koja već imam".

Šablon zahteva je u `predlozi/SABLON-ZAHTEVA.md`.
"""


def module_summary(path: Path) -> str:
    """Prvi red docstringa modula. Ako ga nema, prazan string."""
    try:
        tree = ast.parse(path.read_text("utf-8", "replace"))
    except (SyntaxError, OSError):
        return ""
    doc = ast.get_docstring(tree) or ""
    return doc.strip().split("\n")[0].strip()


def js_summary(path: Path) -> str:
    """Prvi red komentara na vrhu JS modula."""
    try:
        lines = path.read_text("utf-8", "replace").splitlines()
    except OSError:
        return ""
    for line in lines[:6]:
        stripped = line.strip()
        if stripped.startswith("//"):
            return stripped.lstrip("/ ").strip()
    return ""


def count_lines(path: Path) -> int:
    try:
        return len(path.read_text("utf-8", "replace").splitlines())
    except OSError:
        return 0


def file_table(root: Path, patterns: list[str], summarize) -> list[str]:
    rows = ["| Fajl | Linija | Šta radi |", "|---|---:|---|"]
    paths: list[Path] = []
    for pattern in patterns:
        paths.extend(root.glob(pattern))
    for path in sorted(set(paths)):
        if "__pycache__" in path.parts:
            continue
        relative = path.relative_to(BASE_DIR).as_posix()
        rows.append(f"| `{relative}` | {count_lines(path)} | {summarize(path) or '—'} |")
    return rows


def route_table() -> list[str]:
    rows = ["| Metoda | Putanja | Funkcija |", "|---|---|---|"]
    entries = sorted(
        ((route.method, route.pattern, route.name) for route in router.entries()),
        key=lambda item: (item[1], item[0]),
    )
    for method, pattern, name in entries:
        rows.append(f"| {method} | `{pattern}` | `{name}` |")
    return rows


def schema_tables() -> list[str]:
    """Šema iz migracija, primenjenih na praznu bazu u memoriji."""
    connection = sqlite3.connect(":memory:")
    for migration in db.MIGRATIONS:
        for statement in db.statements(migration):
            connection.execute(statement)

    rows: list[str] = []
    names = [
        item[0]
        for item in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    for name in names:
        columns = connection.execute(f"PRAGMA table_info({name})").fetchall()
        listed = ", ".join(f"`{column[1]}`" for column in columns)
        rows.append(f"- **`{name}`** ({len(columns)}) — {listed}")
    connection.close()
    return rows


def question_type_list() -> list[str]:
    rows = ["| Ključ | Naziv | Ocenjuje | Odgovor |", "|---|---|---|---|"]
    for item in question_types.all_types():
        grading = {"local": "lokalno", "ai": "AI", "hybrid": "lokalno pa AI",
                   "self": "korisnik sam"}.get(item.grading, item.grading)
        rows.append(f"| `{item.key}` | {item.label} | {grading} | {item.answer_kind} |")
    return rows


def build() -> str:
    parts = [HEADER]

    parts.append("## Struktura — Python\n")
    parts.extend(file_table(BASE_DIR / "app", ["*.py", "*/*.py"], module_summary))
    parts.append("")
    parts.append("Ulazne tačke: `run.py` (pokretanje), `run_tests.py` (testovi), "
                 "`mapa.py` (ovaj fajl).\n")

    parts.append("## Struktura — frontend\n")
    parts.extend(file_table(BASE_DIR / "web", ["*.html", "css/*.css", "js/*.js", "js/*/*.js"],
                            js_summary))
    parts.append("")
    parts.append("Frontend je SPA bez frameworka: ES moduli, rutiranje preko `location.hash`, "
                 "server servira samo statiku i JSON.\n")

    parts.append("## Tabele u bazi\n")
    parts.extend(schema_tables())
    parts.append("")

    parts.append("## Tipovi pitanja\n")
    parts.extend(question_type_list())
    parts.append("")

    parts.append("## API rute\n")
    parts.extend(route_table())

    parts.append(FOOTER)
    return "\n".join(parts) + "\n"


def main() -> int:
    from app import config

    config.PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
    text = build()
    config.CONTEXT_FILE.write_text(text, "utf-8")

    print(f"Upisano: {config.CONTEXT_FILE.relative_to(BASE_DIR)}")
    print(f"  {len(text.splitlines())} redova, {len(router)} ruta, "
          f"{len(question_types.all_types())} tipova pitanja")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
