# skripta-faks

Interaktivna aplikacija za ucenje i obnavljanje gradiva uz pomoc AI-ja.
Radi lokalno, na tvom racunaru, bez ijedne eksterne biblioteke.

Napravis kategoriju (predmet), u njoj podkategoriju (kolokvijum, oblast, sta god),
ubacis materijale — PDF, slike, snimke, Word, tekst — napises sta se tacno uci,
i sistem od toga generise pitanja. Onda te ispituje, prati sta gresis, i forsira
bas to.

## Sta ti treba

Samo **Python 3.11+**. Nista drugo — nema `pip install`, nema `requirements.txt`.
Celu aplikaciju cini standardna biblioteka: `http.server`, `sqlite3`, `urllib`,
`zipfile`, `zlib`, `xml`.

Za AI funkcije treba ti besplatan **Gemini API kljuc**
(https://aistudio.google.com/apikey) — unosis ga u aplikaciji, u tabu Podesavanja.

## Pokretanje

Dupli klik na `START.bat`. Otvorice se browser na `http://localhost:8077`.

U konzoli pise i adresa za telefon (npr. `http://192.168.1.12:8077`) — otvoris je
na telefonu koji je na istom Wi-Fi-ju i mozes da slikas zadatak i posaljes ga
direktno u aplikaciju.

Da napravis ikonicu na desktopu: desni klik na `START.bat` → Send to → Desktop
(create shortcut).

## Gde su podaci

Sve je u folderu `data/`:

- `data/skripta.db` — SQLite baza (pitanja, odgovori, napredak, podesavanja)
- `data/materials/<kategorija>/` — tvoji uploadovani fajlovi, u originalu

`data/` je van gita. Bekap = kopiraj taj folder.

## Dokumentacija

- [docs/PLAN.md](docs/PLAN.md) — plan izgradnje, faze i odluke
- [docs/ARHITEKTURA.md](docs/ARHITEKTURA.md) — kako je sastavljeno i zasto
