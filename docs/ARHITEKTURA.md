# Arhitektura

## Ograničenje koje oblikuje sve ostalo

**Nula zavisnosti.** Nema `pip install`, nema `requirements.txt`, nema CDN-a.
Sve je standardna biblioteka Pythona i običan browser.

To nije estetika — to je otpornost. Aplikacija koju pokrećeš dupli klikom, koja
ti treba noć pred kolokvijum, ne sme da zavisi od toga da li se neki paket
instalirao i da li verzije pristaju. Sve što je ovde potrebno stiže sa Pythonom.

Posledice, redom:

| Umesto | Koristi se |
|---|---|
| Django / Flask | `http.server.ThreadingHTTPServer` + sopstveni ruter (`app/router.py`) |
| PostgreSQL / MySQL | `sqlite3`, jedan fajl u `data/` |
| `requests` | `urllib.request` |
| Jinja2 / React | JSON API + vanilla ES moduli; server ne renderuje HTML |
| Bootstrap | `web/css/style.css`, tokeni u CSS promenljivama |
| PyMuPDF / pdfplumber | `zlib` + sopstveni PDF čitač (`app/extract/pdf.py`) |
| python-docx / openpyxl | `zipfile` + `xml.etree` — OOXML su ZIP arhive sa XML-om |
| pyttsx3 / gTTS | Web Speech API u browseru, `System.Speech` kroz PowerShell, Gemini TTS |
| `cgi.FieldStorage` (izbačen u 3.13) | streaming multipart parser (`app/http_util.py`) |

## Slojevi

```
run.py ─────────────► app/server.py ──► app/router.py ──► app/api/*.py
                            │                                  │
                            │ servira web/                      ▼
                            ▼                            app/services/*.py
                       browser (SPA)                            │
                                                    ┌───────────┼───────────┐
                                                    ▼           ▼           ▼
                                            app/extract/   app/quiz/    app/ai/
                                            (čitanje       (tipovi,     (Gemini,
                                             fajlova)      ocenjivanje,  promptovi,
                                                           raspored)     ugovor)
                                                                │
                                                                ▼
                                                           app/db.py → data/skripta.db
```

Rute su tanke: parsiraju ulaz i zovu servis. Logika je u `app/services/`.
`app/quiz/` i `app/extract/` su čiste biblioteke — ne znaju za HTTP.

## Odluke koje se ne vide iz koda

### Šema baze pre svega ostalog

16 tabela je napisano u jednom potezu, pre ijedne rute. Šema je jedina stvar
koju je skupo menjati kasnije: pitanja, odgovori i raspored ponavljanja su
međusobno vezani, i pogrešna pretpostavka tu se plaća migracijom preko podataka
koji već postoje.

### Korisnikove beleške žive odvojeno od pitanja

`question` je ono što je AI napravio. `question_meta` je tvoj odnos prema tome:
beleška, oznake, „zanemari zauvek". Odvojeno je namerno — AI sme da regeneriše
ili prepravi pitanje, a ono što si ti zapisao mora to da preživi. Pinovano
testom `test_note_survives_editing_the_question`.

### Migracije se ne rade preko `executescript`

`sqlite3.executescript` izda COMMIT pre nego što krene, pa bi migracija ostala
van transakcije i polomljena šema bi se upisala do pola. Zato `db.statements()`
deli skriptu na naredbe (poštujući navodnike i komentare) i izvršava ih unutar
prave transakcije.

### Ekstrakcija je hibrid, sa vidljivom odlukom po fajlu

Prvo lokalno, bez slanja igde. Kad lokalno ne da upotrebljiv tekst — skeniran
PDF, slika, snimak — fajl se označi `remote_needed` i original ide Gemini-ju.

Odluku donosi `extract.quality_of()`: gleda udeo slova, razmaka i prosečnu
dužinu reči. CID font bez ToUnicode mape daje niz simbola bez razmaka; to je
tačno ono što heuristika hvata. Rezultat i razlog stoje na materijalu i vide se
u UI-ju, pa nikad nije misterija zašto je nešto poslato na internet.

### PDF čitač bez biblioteke

`app/extract/pdf.py` radi: FlateDecode + PNG prediktore, object streamove
(PDF 1.5+ pakuje rečnike u `/ObjStm`, bez raspakivanja nema fontova), stablo
strana, i ToUnicode CMap mape. Poslednje je ključno — bez njega ćirilica i naši
znaci izađu kao smeće.

Ono što ne pokriva pada na Gemini. To je dozvoljeno po dizajnu, i zato je čitač
smeo da bude ambiciozan.

### Jedan poziv nosi što više gradiva

Besplatna Gemini kvota se troši po pozivu, ne po tokenu. Zato `generation._pack`
puni jedan poziv do budžeta znakova (podrazumevano 60 000) i traži desetine
pitanja odjednom, umesto pitanja po pitanja.

Kad odgovor bude odsečen na `MAX_TOKENS`, `contract._salvage` iz nepotpunog JSON-a
izvlači sve cele objekte. Bolje 18 upotrebljivih pitanja nego nijedno zato što
je 19. presečeno.

### AI se zove samo kad mora

Sve što se može proveriti lokalno — proverava se lokalno (`app/quiz/grading.py`).
Kod ponuđenih odgovora objašnjenje već postoji iz generisanja. AI ulazi u igru
samo za dopunu rečenice koja je promašena, kratak i duži odgovor, i foto-zadatke.

Rezultat se upisuje u `explanation_cache` po otisku odgovora, pa isti pogrešan
odgovor drugi put ne košta ništa.

Prazan odgovor nikad ne zove AI — netačan je bez razmišljanja.

### Isti ugovor za Gemini i za ručno nalepljen odgovor

`app/ai/contract.py` je jedini put kojim pitanja ulaze u bazu. Kad Gemini ne može
da obradi format, izvezeš prompt (`Generisanje → Izvezi prompt`), odneseš ga u
Claude, i nalepiš odgovor nazad. Prolazi kroz identičnu proveru — nema puta u
bazu koji zaobilazi validaciju.

Ručna izmena pitanja u UI-ju ide kroz isti `contract.validate_one`.

### „App menja sam sebe" znači bazu, ne kod

`app/services/strategy.py` menja sadržaj u bazi koji ulazi u sledeći prompt:
raspodelu tipova, težinu, teme u fokusu, profil grešaka. Svaka verzija se čuva,
vidi se na ekranu sa obrazloženjem, i vraća jednim klikom.

Kod aplikacije se ne dira nikad. Neproverena izmena koda koja se sama primenjuje
obara server usred učenja, a uzrok tražiš u kodu koji nisi pisao.

### Tipovi pitanja su registar, ne if-lanac

`app/quiz/types.py` i `web/js/render.js` drže po jedan unos za svaki od 15
tipova. Dodavanje tipa je dva unosa i jedan ocenjivač — nigde nema grananja koje
raste.

Registar se šalje i modelu u promptu, pa je tačnost registra direktno tačnost
generisanih pitanja.

## Bezbednost, koliko je lokalnoj aplikaciji potrebno

Server sluša na `0.0.0.0` — to je ono što omogućava telefon na istom Wi-Fi-ju.
Znači da je dostupan svakome na toj mreži, i to je svesna razmena.

Ono što je ipak zatvoreno:

- **Media se nikad ne servira inline osim slika, zvuka, videa i PDF-a.**
  Uploadovan `.html` ili `.svg` posluženi inline su skladišteni XSS sa istim
  origin-om kao aplikacija. Pinovano `test_uploaded_file_is_served_as_attachment`.
- **Path traversal** na `/media/` i na statici — putanja se razrešava i proverava
  da li je i dalje ispod dozvoljenog korena.
- **API ključ nikad ne izlazi iz servera u celini** — `public_settings()` vraća
  maskiran, a prazan string na upisu znači „nisam menjao", ne „obriši".
- **Ključ ide u zaglavlje `x-goog-api-key`, ne u URL** — URL završava u porukama
  o greškama i logovima.
- **`ai_call_log` nosi model, trajanje i status** — nikad telo ni ključ.
- **Windows govor prima tekst kroz stdin**, ne kroz komandnu liniju: apostrof u
  pitanju bi inače bio ubacivanje komande.

Ključ stoji u SQLite fajlu čitljiv. Šifrovanje bez odvojenog mesta za ključ šifre
bilo bi pozorište — ključ bi morao da stoji u istom folderu. Zaštita je to što
fajl ne napušta mašinu i van je gita.

## Testovi

125 testova, `python run_tests.py`. Bez pytest-a — `unittest` je u standardnoj
biblioteci.

Dva nezavisna predohrana, oba pinovana testom koji ih namerno ruši:

1. **`SKRIPTA_DATA_DIR`** na privremeni folder — baza je fizički drugi fajl
2. **`SKRIPTA_BLOCK_NETWORK`** — nijedan AI poziv ne izlazi iz procesa, pa suite
   ne može da potroši kvotu ni da pošalje gradivo na internet

`tests/base.py` proverava živu putanju na svakom `setUp`. Ako neko sutra promeni
redosled uvoza, test padne odmah umesto da obriše gradivo.

`test_http.py` vozi pravi HTTP server — ruter, multipart upload, JSON odgovore.
Sve ostalo ide oko servera, pa greška u serveru ne bi bila vidljiva nigde drugde.
