# Plan i odluke

## Šta je ovo

Lokalna aplikacija za učenje i obnavljanje gradiva uz pomoć AI-ja. Praviš
kategoriju (predmet), u njoj podkategoriju (kolokvijum, oblast — u nedogled),
ubaciš materijale, napišeš šta se tačno uči, i sistem od toga generiše pitanja i
ispituje te — forsirajući ono što grešiš.

## Odluke donete pre pisanja koda

| Pitanje | Odluka | Zašto |
|---|---|---|
| Stack | **Nula zavisnosti**, samo standardna biblioteka | Aplikacija koja ti treba noć pred kolokvijum ne sme da zavisi od `pip install` |
| Baza | SQLite, jedan fajl u `data/` | Bekap = kopiranje foldera |
| Obrada fajlova | **Hibrid**: prvo lokalno, fallback na Gemini Files API | Jeftino i privatno gde može, tačno gde mora |
| Obim prve isporuke | **Cela specifikacija odjednom** | Klijentska odluka |
| Samo-izmena | **Menja strategiju u bazi, nikad kod** | Neproverena izmena koda obara server usred učenja |
| Jezik | Srpski (latinica), bez gettext-a | Jedan korisnik, jedan jezik — katalog bi bio čista režija |
| Repo | Privatan | Drži lični API ključ i lične materijale |

## Šta je urađeno

### Temelj
- `app/config.py` — sve putanje na jednom mestu, `use_data_dir()` za testove
- `app/db.py` — 16 tabela u 4 migracije, `statements()` splitter, konekcija po niti, WAL
- `app/http_util.py` — streaming multipart parser (`cgi` je izbačen u 3.13), request/response
- `app/router.py` — šabloni putanja sa `<int:>` / `<str:>` / `<path:>` konvertorima
- `app/server.py` — `ThreadingHTTPServer`, statika, media sa zaštitom od path traversal-a

### Kategorije
Samo-referentno stablo bez ograničenja dubine. Nasleđivanje uputstva „šta se uči"
niz lanac. Cycle guard na premeštanju i `seen`-set na obilasku.

### Materijali i ekstrakcija
- `plaintext` — pogađanje kodiranja, skidanje tajminga sa titlova
- `ooxml` — docx/xlsx/pptx kroz `zipfile` + `xml.etree`
- `pdf` — FlateDecode, PNG prediktori, object streamovi, stablo strana, ToUnicode CMap
- `chunking` — deljenje na granici pasusa/naslova, prepoznavanje „Lekcija N"
- heuristika kvaliteta koja odlučuje da li tekst ide dalje ili original ide AI-u

### AI sloj
- `gemini.py` — `urllib`, ključ u zaglavlju, Files API (resumable), retry sa backoff-om
- `prompts.py` — generisanje, ocenjivanje, objašnjenje, strategija, dopune, izvoz
- `contract.py` — parsiranje sa skidanjem ograda, spasavanje odsečenog JSON-a,
  validacija po tipu, otisak za prepoznavanje duplikata
- `tts.py` — Gemini TTS (PCM → WAV kroz `wave`) i Windows govor

### Kviz
15 tipova pitanja, svaki sa svojim validatorom i ocenjivačem:

`mcq_single` · `mcq_multi` · `true_false` · `fill_blank` · `cloze_dropdown` ·
`short_answer` · `long_answer` · `numeric` · `match_pairs` · `order_sequence` ·
`odd_one_out` · `image_match` · `image_label` · `work_it_out` · `flashcard`

Delimičan skor gde ima smisla (višestruki izbor, parovi, redosled, praznine).

Raspored ponavljanja je SM-2 sa dve izmene: delimičan skor i `mastery` kao
klizeći prosek. Agresivnost 1–5 pomera prag savladanosti (0.70 → 0.95), dužinu
intervala i udeo savladanih pitanja u sesiji.

### Interakcija sa pitanjem
Beleška, „želim da proverim", „proveriti u fajlu (ponavlja se ili je greška)",
„nebitno", preskoči (samo ova sesija) i zanemari zauvek. Sve u `question_meta`,
odvojeno od pitanja, da preživi regenerisanje.

### Adaptivnost
Profil grešaka (`misconception`) se puni iz AI ocenjivanja. `strategy.refresh()`
šalje modelu sažetak učenja i dobija novu raspodelu tipova, težinu, teme u fokusu
i uputstvo za sledeći prompt. Svaka verzija se čuva i vraća.

### Frontend
SPA bez frameworka: `web/js/` ES moduli, `web/css/style.css` sa tokenima za tamnu
i svetlu temu. Sedam tabova po predmetu, ekran učenja sa svih 15 rendera, mobilni
izgled sa fioka-menijem.

### Testovi
125 testova, `python run_tests.py`. Dva predohrana (privremena baza + blokirana
mreža), oba pinovana testom koji ih namerno ruši.

## Šta bi bio sledeći korak

Nije rađeno, i nije obećano — spisak stoji ovde da se ne izgubi:

- **Izvoz i uvoz cele kategorije** (pitanja + materijali) kao jedan fajl, za
  deljenje sa kolegama ili prelazak na drugi računar
- **Simulacija ispita** — vremenski ograničena sesija sa ocenom na kraju, bez
  objašnjenja u toku
- **Grupisanje varijacija u UI-ju** — sada se u jednoj sesiji pojavljuje najviše
  jedna iz grupe, ali ne postoji ekran koji pokazuje sve varijante zajedno
- **Automatsko sečenje slika iz PDF-a** za `image_match` i `image_label` — sada
  slika mora da bude zaseban uploadovan fajl
- **Statistika kroz vreme** preko više predmeta, na početnom ekranu
- **Podsetnik** kad nešto dospe za ponavljanje (sistemsko obaveštenje)

## Poznata ograničenja

- **Skenirani PDF bez teksta ide Gemini-ju u celini.** To troši kvotu brže nego
  tekstualni materijal. Vidi se u planu generisanja pre nego što pritisneš dugme.
- **Stari binarni formati** (`.doc`, `.xls`, `.ppt`) se ne čitaju lokalno, a
  Gemini ih ne prima pouzdano. Sačuvaj ih kao `.docx` ili PDF.
- **Poslovi u pozadini žive u memoriji.** Restart aplikacije usred generisanja
  znači da se posao ne nastavlja — pitanja koja su do tada upisana ostaju.
- **Server sluša na svim adresama.** To je ono što omogućava telefon; znači i da
  je dostupan svakome na istom Wi-Fi-ju. Nema lozinke.
- **Web Speech glasovi zavise od Windows-a.** Ako nema instaliranog srpskog
  glasa, čita se engleskim izgovorom — Windows ih dodaje kroz
  Settings → Time & Language → Speech.
