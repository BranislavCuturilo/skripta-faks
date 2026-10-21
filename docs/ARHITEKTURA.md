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

### Nazivi modela se ne upisuju tvrdo

Prva verzija je nosila `gemini-2.5-flash` i drugove kao podrazumevane vrednosti.
Google ih je penzionisao, a odvojeno od toga počeo i da gasi stari tip API
ključa — i aplikacija je prestala da radi uz poruku koja korisniku nije značila
ništa.

Zato se model bira **po obliku, ne po nazivu**, iz spiska koji vrati sam ključ
(`ListModels`): uvek **najnoviji stabilan** model odgovarajuće familije
(`lite` za brzi, običan flash za standardni, `pro` za najjači). Redosled u
`models._score`: naziv sa verzijom → stabilan pre preview-a → najnovija
generacija → oblik → najveća verzija. Preview ide tek kad stabilnog nema, jer
nov preview obično nema besplatnu kvotu. Aliasi tipa `gemini-flash-latest` idu
na kraj: ne kažu verziju, pa ni koje polje za razmišljanje model prima.
`PREFERRED` važi samo dok spisak još nije pročitan.

Korisnik ne bira ništa — pinovano u `tests/test_ai_models.py`:

- **Automatski izbor se nigde ne upisuje.** U `model_<nivo>` stoji samo ručni
  izbor; prazno = automatski i razrešava se pri svakom pozivu. Prva verzija je
  pri osvežavanju **upisivala** razrešen naziv, pa je „Automatski" tiho postajao
  ručni izbor i nova generacija se nikad nije koristila — zbog toga su korisnici
  menjali model ručno. Migracija 7 vraća sve tako upisane izbore na automatski.
- **Spisak se osvežava sam**, jednom dnevno: na startu (u pozadini) i pred poziv
  (`refresh_if_stale`). Neuspelo osvežavanje se ne ponavlja pred svaki poziv.
- **Model koji ne radi sa ključem se preskače u istom pozivu.** Nestao (404) ili
  bez besplatne kvote (429 sa `limit: 0`, koji se zato ni ne ponavlja) — pamti se
  7 dana u `models_unusable` i ide sledeći najnoviji. Obična potrošena kvota
  menja model samo za taj poziv, jer svaki model ima svoju kvotu. Najviše dve
  zamene po pozivu — posle toga je kriv ključ ili mreža.
- Ručni izbor se poštuje, osim kad model nestane ili je iz familije koja se
  gasi; tada se vraća na automatski i **prijavi**.

### AI se zove samo kad mora

Sve što se može proveriti lokalno — proverava se lokalno (`app/quiz/grading.py`).
Kod ponuđenih odgovora objašnjenje već postoji iz generisanja. AI ulazi u igru
samo za dopunu rečenice koja je promašena, kratak i duži odgovor, i foto-zadatke.

Rezultat se upisuje u `explanation_cache` po otisku odgovora, pa isti pogrešan
odgovor drugi put ne košta ništa.

Prazan odgovor nikad ne zove AI — netačan je bez razmišljanja.

Ocenjivanje se radi dok student čeka pred ekranom, pa ima sopstvena ograničenja
(`GRADE_*` u `app/services/study.py`): model dobija `thinking="low"`, poziv ima
kratak timeout i najviše dva pokušaja. Bez toga je Gemini 2.5+/3.x podrazumevano
„razmišljao" desetinama sekundi, razmišljanje je jelo `maxOutputTokens` i sekao
JSON, a četiri pokušaja po 300 s su značila i po dva minuta spinera. Polje za
razmišljanje se razlikuje po generaciji (`thinkingLevel` / `thinkingBudget`) i
bira ga `models.thinking_config()`; model koji ga ne prihvati (400) dobije isti
zahtev još jednom bez njega. Foto-zadaci razmišljaju normalno i čekaju duže.
Poslovi u pozadini (generisanje, prepis ispita) i dalje rade sa strpljivim
podrazumevanim vrednostima.

### U sesiji: jedan AI poziv na kraju, ne po odgovoru

I sa tim ograničenjima, poziv posle svakog tekstualnog odgovora troši kvotu po
pitanju i drži studenta da čeka usred učenja. Zato `study.answer` u sesiji ne
zove model. Odgovor se upiše sa
`attempt.graded_by = 'pending'` (`grading.PENDING`) i korisnik ide dalje.
`study.review` na kraju šalje **jedan** poziv sa svim odgovorima koji čekaju,
ostalim odgovorima iz sesije (za zaključak) i izvodom iz skripte iz kog su ta
pitanja generisana (`generation_run.chunk_ids`) — isti tekst koji je modelu već
poslat pri generisanju. Model vrati ocenu po odgovoru i zaključak sesije, koji
se čuva u `study_session.review`.

Pravila koja drže ovo poštenim:

- **Odgovor koji čeka nema ocenu.** Raspored (`scheduler.record`), brojač
  tačnih, strategija i grafikon aktivnosti ga ne vide dok ga pregled ne oceni —
  inače bi svaki esej prvo bio kažnjen kao netačan, pa ocenjen još jednom.
- **Pao poziv ne gubi ništa.** Odgovori ostaju `pending`; ponovni pregled
  ocenjuje samo ono što i dalje čeka. Odgovor koji model preskoči čeka sledeći.
- **Svaka ocena je jedna transakcija** — upis ocene, keš, raspored i brojač.
- **Dva pregleda iste sesije ne idu istovremeno** (409), da raspored ne upiše
  isti odgovor dvaput.
- Van sesije (provera jednog pitanja iz liste) model se i dalje zove odmah —
  tu nema „kraja" na koji bi se čekalo.
- Pregled ima svoja ograničenja (`REVIEW_*`): isto `thinking="low"` za tekst,
  ali duži timeout i pun izlazni budžet, jer nosi sve odgovore odjednom.

Pinovano u `tests/test_session_review.py`.

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

### Ono što ulazi u bazu prolazi kroz filter pisma, ne kroz nadu

Model dobije „piši latinicom" i vrati pola pitanja ćirilicom — naročito kad je
gradivo ćirilično. Uputstvo u promptu je pojačano, ali garancija je
`app/translit.py`: `contract.validate_one(item, script=...)` preslovljava svako
tekstualno polje pre nego što se izračuna otisak i pre upisa. Ćirilica →
latinica je 1:1; latinica → ćirilica ide po rečima i preskače formule, jedinice
i strane reči (`H2O`, `kg`, `Windows`). Isti filter ide preko AI ocene odgovora.
Usput je popravljen i otisak pitanja (`content_hash`), koji je do tada bacao sva
neASCII slova — dva različita ćirilična pitanja su imala isti otisak i drugo je
tiho nestajalo kao „duplikat".

### Redosled ponuđenih odgovora se meša u browseru, ne u bazi

Model stavlja tačan odgovor na prvo mesto mnogo češće nego što bi trebalo.
`payload.shuffle` je postojao od početka, ali ga niko nije čitao. Mešanje je u
`web/js/render.js` (`shuffledOrder`) pri svakom prikazu; server i ocenjivanje
vide samo originalne indekse, pa stara pitanja u bazi dobijaju popravku bez
migracije. Doslovno uvezena ispitna pitanja nose `shuffle: false` (redosled kao
u dokumentu), osim ako korisnik pri uvozu ne kaže drugačije.

### Ispitna baza: parser pre modela, model pod nadzorom teksta

Zahtev „fiksna lista pitanja, 1:1 kao na ispitu" je suprotan generisanju: tu AI
ne sme ništa da piše. `app/extract/exam_parser.py` prepoznaje numerisana pitanja,
`a) b) c)` odgovore i oznaku tačnog bez ijednog poziva, a
`app/services/exam_import.py` ih upisuje sa `question.origin = 'exam'`. Drugi
režim pušta Gemini da prepiše nesređen fajl, ali onda svako pitanje i svaki
odgovor moraju da se nađu **doslovno** u lokalno pročitanom tekstu — šta nije
nađeno, odbija se sa razlogom. Odgovor koji je odredio model (dokument ga nije
imao) nosi `flag_check_source` od prvog prikaza. Sesija učenja ima
`origin_filter` da se vežbaju samo ta pitanja.

### Duplikat je ono što student oseti kao isto pitanje, ne isti bajtovi

`content_hash` hvata samo bajt-isto pitanje u istoj kategoriji; jedan drugačiji
pogrešan odgovor ili jedna reč više i isto pitanje je ulazilo ponovo.
`app/quiz/duplicates.py` zato poredi: **isti tip + isti tačan odgovor + tekst
≥ 85 % sličan, sa istim brojevima** („Izračunaj 2+2" i „1+3" imaju isti odgovor,
a nisu isti zadatak). Pogrešni ponuđeni odgovori ne ulaze u poređenje. Drugi
tip na istu temu nije duplikat — dogovor sa korisnikom. Pitanja se grupišu po
(tip, tačan odgovor), pa se tekst poredi samo unutar grupe.

Pravilo drže tri mesta, sva pinovana u `tests/test_duplicates.py`:

- **upis** (`questions.insert_many`): AI pitanje se poredi sa celim podstablom
  ciljne kategorije (i obrisanim i zanemarenim — inače bi se vratila kao nova)
  i sa ostatkom serije. Ispitna pitanja ulaze doslovno, bez toga.
- **sesija** (`scheduler.pick`): nikad dvaput isto ni dve varijacije iste
  grupe, računajući i ono što je u sesiji već odgovoreno ili preskočeno.
  Sledeće pitanje se bira posebno (`limit=1`); ranije ta odluka nije znala za
  već odgovorena, pa je varijacija upravo odgovorenog pitanja dolazila odmah.
- **čišćenje** (`questions.remove_duplicates`, dugme u tabu Pitanja): meko
  briše kopije koje su ušle ranije. Ne dira ispitna pitanja, pitanja sa
  beleškom ili oznakom, ni pitanje čiji par stoji u **susednoj** kategoriji —
  sesija samo te kategorije bi ga izgubila.

### Ažuriranje: poslednji commit na `main`, git ili ZIP

Prva verzija je pitala GitHub `releases/latest`. Release se nikad ne pravi,
odgovor je bio 404, provera je uvek govorila „imaš najnoviju" — ažuriranje nije
radilo nikad. Sada je izvor istine `commits/main`, a koliko je instalacija iza
kaže `compare` od instaliranog commit-a (`.git/HEAD` bez git-a, ili
`verzija.json` kod ZIP instalacije). Commit koji GitHub ne zna (neposlate
izmene na mašini na kojoj se programira) ne dobija ponudu.

Git kopija se ažurira sa `git pull --ff-only`, ne ZIP-om: ZIP preko git kopije
ostavlja izmenjeno radno stablo i sledeći `git pull` odbije. `--ff-only` nikad
ne spaja i ne briše lokalne izmene.

`START.bat` i `azuriraj.bat` se **prepisuju dok se izvršavaju**, a cmd čita
.bat red po red sa diska — posle prepisivanja nastavlja na istom bajtu u novom
fajlu. Proba u sandbox-u sa starim `START.bat`-om: posle ugradnje je cmd
pokušao da izvrši reč iz komentara novog fajla. Zato: svaki korak koji menja
fajlove je u bloku `( ... )` koji se završava sa `exit` (blok se pročita ceo
pre izvršavanja), `azuriraj.bat` sebe kopira tek u poslednjem bloku, nema
`goto` ni labela (ZIP stiže sa LF krajevima), `findstr` umesto `find` (Git za
Windows ume da stavi Unix `find` ispred), i puna putanja `%~dp0azuriraj.bat`
(uz `NoDefaultCurrentDirectoryInExePath` cmd ne traži u tekućem folderu).
Pinovano statičkim testovima u `tests/test_updater.py`.

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

333 testa, `python run_tests.py`. Bez pytest-a — `unittest` je u standardnoj
biblioteci.

Dva nezavisna predohrana, oba pinovana testom koji ih namerno ruši:

1. **`SKRIPTA_DATA_DIR`** na privremeni folder — baza je fizički drugi fajl
2. **`SKRIPTA_BLOCK_NETWORK`** — nijedan AI poziv ne izlazi iz procesa, pa suite
   ne može da potroši kvotu ni da pošalje gradivo na internet

`tests/base.py` proverava živu putanju na svakom `setUp`. Ako neko sutra promeni
redosled uvoza, test padne odmah umesto da obriše gradivo.

`test_http.py` vozi pravi HTTP server — ruter, multipart upload, JSON odgovore.
Sve ostalo ide oko servera, pa greška u serveru ne bi bila vidljiva nigde drugde.
