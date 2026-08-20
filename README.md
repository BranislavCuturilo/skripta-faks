# skripta-faks

Interaktivna aplikacija za ucenje i obnavljanje gradiva uz pomoc AI-ja.
Radi lokalno, na tvom racunaru, bez ijedne eksterne biblioteke.

Napravis kategoriju (predmet), u njoj podkategoriju (kolokvijum, oblast, sta god),
ubacis materijale — PDF, slike, snimke, Word, tekst — napises sta se tacno uci,
i sistem od toga generise pitanja. Onda te ispituje, prati sta gresis, i forsira
bas to.

Ako fakultet deli fiksnu listu ispitnih pitanja, tab **Ispitna baza** je uveze
doslovno — bez AI prepravljanja — pa vezbas tacno ta pitanja.

## Instalacija (Windows)

Skini **[instaliraj.bat](https://github.com/BranislavCuturilo/skripta-faks/raw/main/instaliraj.bat)**
i klikni dupli klik na njega. To je sve.

Instalacija sama: instalira Python ako ga nema, skine aplikaciju, napravi
ikonicu na desktopu i pokrene je.

> Windows ce verovatno reci *„Windows protected your PC"* — to kaze za svaki
> `.bat` skinut sa interneta, ne znaci da nesto nije u redu. Klikni **More
> info** → **Run anyway**.

Posle toga aplikaciju pokreces ikonicom **skripta-faks** na desktopu.

### Rucno, ako ti je tako draze

Treba ti samo **Python 3.11+**. Nista drugo — nema `pip install`, nema
`requirements.txt`. Celu aplikaciju cini standardna biblioteka: `http.server`,
`sqlite3`, `urllib`, `zipfile`, `zlib`, `xml`.

Skini ZIP repozitorijuma, raspakuj ga i klikni na `START.bat`. Otvorice se
browser na `http://localhost:8077`.

### Gemini kljuc

Za AI funkcije treba ti besplatan **Gemini API kljuc**
(https://aistudio.google.com/apikey) — unosis ga u aplikaciji, u tabu Podesavanja.

## Azuriranje

U aplikaciji: **Podesavanja → Verzija i azuriranje → Preuzmi i azuriraj**.

Nova verzija se preuzme odmah, a ugradi se pri sledecem pokretanju — dok
aplikacija radi, drzi svoje fajlove otvorene i ne moze da ih prepise ispod
sebe. Znaci: klikni preuzmi, zatvori aplikaciju, pokreni je ponovo.

Tvoja pitanja, materijali i napredak se pri azuriranju ne diraju.

## Ucenje sa telefona

Adresa za telefon pise na **pocetnom ekranu aplikacije** (kartica *Otvori na
telefonu*) i u konzoli pri pokretanju — npr. `http://192.168.1.12:8077`.

Telefon mora da bude na istom Wi-Fi-ju. Time dobijas i tip zadatka „Uradi
zadatak": resis na papiru, slikas telefonom, i AI proverava postupak.

Ako je ponudjeno vise adresa, probaj onu bez napomene — one oznacene kao
*VirtualBox*, *WSL* ili *VPN* skoro sigurno nisu tvoj Wi-Fi.

## Gde su podaci

Sve je u folderu `data/`:

- `data/skripta.db` — SQLite baza (pitanja, odgovori, napredak, podesavanja)
- `data/materials/<kategorija>/` — tvoji uploadovani fajlovi, u originalu

`data/` je van gita. Bekap = kopiraj taj folder.

## Ako ti aplikacija ne radi ono sto ti treba

Ne moras sam da pises kod. Tab **Predlozi** u aplikaciji: opises svojim recima
sta ti fali, Gemini to prevede u konkretan nalog (koji fajlovi se diraju, sta se
menja, sta ne sme da se pokvari), i taj nalog odneses placenom AI asistentu koji
ume da napise kod.

Vidi [predlozi/README.md](predlozi/README.md).

## Dokumentacija

- [docs/UPUTSTVO.md](docs/UPUTSTVO.md) — **od nule do prve sesije**: Gemini kljuc,
  podesavanja, materijali, ucenje, telefon, resavanje problema
- [docs/PLAN.md](docs/PLAN.md) — plan izgradnje, faze i odluke
- [docs/ARHITEKTURA.md](docs/ARHITEKTURA.md) — kako je sastavljeno i zasto
- [predlozi/README.md](predlozi/README.md) — kako se aplikacija nadogradjuje

## Za programere

```
python run_tests.py     # ceo test suite (230 testova, bez pytest-a)
python mapa.py          # regenerise predlozi/KONTEKST-ZA-AI.md iz koda
```
