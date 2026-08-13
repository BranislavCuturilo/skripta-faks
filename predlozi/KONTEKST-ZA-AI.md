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

## Struktura — Python

| Fajl | Linija | Šta radi |
|---|---:|---|
| `app/__init__.py` | 3 | skripta-faks: lokalna aplikacija za ucenje uz pomoc AI-ja, bez zavisnosti. |
| `app/ai/__init__.py` | 6 | AI sloj: klijent, promptovi i ugovor o formatu odgovora. |
| `app/ai/contract.py` | 210 | Ugovor o formatu izmedju aplikacije i bilo kog modela. |
| `app/ai/gemini.py` | 332 | Gemini klijent na urllib. |
| `app/ai/models.py` | 133 | Koji se model zove za koji posao. |
| `app/ai/prompts.py` | 379 | Sablonski promptovi. |
| `app/ai/tts.py` | 120 | Izgovor teksta. |
| `app/api/__init__.py` | 11 | Registracija ruta. Uvoz modula je ono sto puni ruter, pa svi moraju da se |
| `app/api/ai.py` | 266 | Rute za AI: generisanje, poslovi, strategija, dopune, izgovor. |
| `app/api/categories.py` | 86 | Rute za stablo kategorija. |
| `app/api/materials.py` | 112 | Rute za materijale: upload, obrada, pregled. |
| `app/api/meta.py` | 60 | Zdravlje aplikacije i jedan poziv koji browser radi na startu. |
| `app/api/proposals.py` | 84 | Rute za predloge nadogradnje aplikacije. |
| `app/api/questions.py` | 60 | Rute za pitanja: pregled, izmena, beleske i flagovi. |
| `app/api/settings.py` | 52 | Rute za podesavanja, ukljucujuci unos i proveru AI kljuca. |
| `app/api/study.py` | 118 | Rute za ucenje: sesija, sledece pitanje, odgovor, preskakanje, rezime. |
| `app/config.py` | 85 | Putanje i podrazumevane vrednosti. Jedino mesto koje zna gde sta stoji. |
| `app/db.py` | 442 | SQLite sloj: konekcija po niti, semа u migracijama, sitni upitni helperi. |
| `app/extract/__init__.py` | 110 | Ekstrakcija teksta iz uploadovanih materijala. |
| `app/extract/chunking.py` | 133 | Deljenje izvucenog teksta na komade koji staju u jedan AI poziv. |
| `app/extract/ooxml.py` | 177 | docx / xlsx / pptx bez ijedne biblioteke. |
| `app/extract/pdf.py` | 620 | Citanje teksta iz PDF-a samo standardnom bibliotekom. |
| `app/extract/plaintext.py` | 52 | Obicni tekstualni formati. Kodiranje se pogadja, ne pretpostavlja. |
| `app/http_util.py` | 349 | Request/response sloj nad http.server. |
| `app/netinfo.py` | 93 | Pod kojim adresama je aplikacija dostupna. |
| `app/quiz/__init__.py` | 1 | Kviz: tipovi pitanja, ocenjivanje, raspored ponavljanja. |
| `app/quiz/grading.py` | 344 | Ocenjivanje odgovora. |
| `app/quiz/scheduler.py` | 268 | Raspored ponavljanja i izbor sledeceg pitanja. |
| `app/quiz/types.py` | 424 | Registar tipova pitanja. |
| `app/router.py` | 107 | Minimalni ruter: sablon putanje -> funkcija. |
| `app/server.py` | 243 | HTTP server nad standardnom bibliotekom. |
| `app/services/__init__.py` | 1 | Poslovna logika. Rute u app/api su tanke i samo zovu ovo. |
| `app/services/ai_models.py` | 152 | Izbor modela u toku rada, sa samopopravljanjem. |
| `app/services/categories.py` | 293 | Kategorije: samo-referentno stablo bez ogranicenja dubine. |
| `app/services/generation.py` | 454 | Generisanje pitanja iz materijala. |
| `app/services/jobs.py` | 124 | Poslovi koji traju duze od jednog zahteva. |
| `app/services/materials.py` | 222 | Materijali: sta korisnik uploaduje i sta se od toga da procitati. |
| `app/services/notes.py` | 116 | AI dopune materijala. |
| `app/services/proposals.py` | 316 | Predlozi za nadogradnju same aplikacije. |
| `app/services/questions.py` | 330 | Pitanja: upis iz generisanja, citanje, korisnikove beleske i flagovi. |
| `app/services/settings_store.py` | 120 | Podesavanja: kljuc-vrednost u bazi, sa tipiziranim podrazumevanim vrednostima. |
| `app/services/strategy.py` | 314 | Adaptivna strategija: kako sistem menja nacin na koji te ispituje. |
| `app/services/study.py` | 352 | Sesija ucenja: izbor pitanja, ocenjivanje, objasnjenja. |

Ulazne tačke: `run.py` (pokretanje), `run_tests.py` (testovi), `mapa.py` (ovaj fajl).

## Struktura — frontend

| Fajl | Linija | Šta radi |
|---|---:|---|
| `web/css/style.css` | 507 | — |
| `web/index.html` | 43 | — |
| `web/js/api.js` | 67 | Jedan omotac oko fetch-a. Greska servera stize kao Error sa citljivom porukom, |
| `web/js/app.js` | 361 | Ulazna tačka: stablo u sidebar-u, rutiranje preko hash-a, tabovi predmeta. |
| `web/js/dom.js` | 175 | Sitni DOM alati. Bez frameworka - `el` je sve sto treba za ovoliku aplikaciju. |
| `web/js/render.js` | 406 | Crtanje pitanja, tip po tip. |
| `web/js/store.js` | 104 | Stanje aplikacije. Malo je, pa je jedan objekat sa pretplatnicima dovoljan. |
| `web/js/tts.js` | 60 | Izgovor teksta. Tri motora, isti poziv. |
| `web/js/views/category.js` | 547 | Ekrani unutar predmeta: pregled, materijali, generisanje pitanja. |
| `web/js/views/guide.js` | 204 | Uputstvo unutar aplikacije. |
| `web/js/views/library.js` | 447 | Pitanja, strategija i dopune - sve što se gleda van sesije učenja. |
| `web/js/views/network.js` | 98 | Kartica "otvori na telefonu". |
| `web/js/views/proposals.js` | 229 | Predlozi za nadogradnju same aplikacije. |
| `web/js/views/settings.js` | 319 | Podešavanja: AI ključ, modeli, agresivnost, govor, izgled, potrošnja. |
| `web/js/views/study.js` | 406 | Ekran ucenja: podesavanje sesije, petlja pitanja, rezime. |

Frontend je SPA bez frameworka: ES moduli, rutiranje preko `location.hash`, server servira samo statiku i JSON.

## Tabele u bazi

- **`ai_call_log`** (12) — `id`, `purpose`, `provider`, `model`, `ok`, `http_status`, `duration_ms`, `prompt_chars`, `prompt_tokens`, `output_tokens`, `error`, `created_at`
- **`attempt`** (12) — `id`, `question_id`, `session_id`, `answer`, `answer_hash`, `is_correct`, `score`, `graded_by`, `feedback`, `misconception`, `response_ms`, `created_at`
- **`category`** (11) — `id`, `parent_id`, `name`, `slug`, `description`, `study_prompt`, `position`, `color`, `archived_at`, `created_at`, `updated_at`
- **`explanation_cache`** (8) — `id`, `question_id`, `answer_hash`, `is_correct`, `score`, `feedback`, `misconception`, `created_at`
- **`generation_run`** (18) — `id`, `category_id`, `provider`, `model`, `source_kind`, `status`, `request_json`, `response_text`, `chunk_ids`, `requested_count`, `produced_count`, `rejected_count`, `duplicate_count`, `prompt_tokens`, `output_tokens`, `error`, `created_at`, `finished_at`
- **`material`** (22) — `id`, `category_id`, `filename`, `stored_name`, `rel_path`, `mime`, `ext`, `size_bytes`, `sha256`, `kind`, `extraction_status`, `extraction_method`, `extraction_note`, `quality_score`, `char_count`, `page_count`, `remote_uri`, `remote_expires_at`, `user_note`, `include_in_study`, `created_at`, `updated_at`
- **`material_chunk`** (9) — `id`, `material_id`, `ordinal`, `label`, `text`, `char_count`, `page_from`, `page_to`, `created_at`
- **`material_note`** (8) — `id`, `category_id`, `material_id`, `kind`, `title`, `body`, `author`, `created_at`
- **`misconception`** (9) — `id`, `category_id`, `label`, `description`, `topic`, `evidence_count`, `resolved_at`, `first_seen_at`, `last_seen_at`
- **`question`** (16) — `id`, `category_id`, `generation_run_id`, `type`, `stem`, `payload`, `explanation`, `difficulty`, `topic`, `source_ref`, `content_hash`, `variant_group`, `variant_index`, `state`, `created_at`, `updated_at`
- **`question_meta`** (10) — `question_id`, `note`, `flag_review`, `flag_check_source`, `flag_irrelevant`, `flag_wrong`, `ignored_at`, `deleted_at`, `pinned`, `updated_at`
- **`question_schedule`** (12) — `question_id`, `category_id`, `ease`, `interval_days`, `due_at`, `streak`, `lapses`, `seen_count`, `correct_count`, `mastery`, `last_seen_at`, `updated_at`
- **`session_skip`** (4) — `session_id`, `question_id`, `reason`, `created_at`
- **`setting`** (3) — `key`, `value`, `updated_at`
- **`strategy`** (9) — `id`, `category_id`, `kind`, `version`, `content`, `rationale`, `author`, `active`, `created_at`
- **`study_session`** (11) — `id`, `category_id`, `include_subtree`, `mode`, `aggressiveness`, `type_filter`, `planned_count`, `asked_count`, `correct_count`, `started_at`, `ended_at`

## Tipovi pitanja

| Ključ | Naziv | Ocenjuje | Odgovor |
|---|---|---|---|
| `mcq_single` | Zaokruži tačan odgovor | lokalno | choice |
| `mcq_multi` | Zaokruži sve tačne | lokalno | choice |
| `true_false` | Tačno ili netačno | lokalno | choice |
| `fill_blank` | Dopuni rečenicu | lokalno pa AI | text |
| `cloze_dropdown` | Dopuni izborom | lokalno | choice |
| `short_answer` | Kratak odgovor | lokalno pa AI | text |
| `long_answer` | Napiši rešenje / objasni | AI | text |
| `numeric` | Brojčani odgovor | lokalno | number |
| `match_pairs` | Poveži parove | lokalno | pairs |
| `order_sequence` | Poređaj redosled | lokalno | order |
| `odd_one_out` | Koji ne pripada | lokalno | choice |
| `image_match` | Poveži sa slikom | lokalno | choice |
| `image_label` | Označi na slici | lokalno | pairs |
| `work_it_out` | Uradi zadatak | AI | photo |
| `flashcard` | Kartica (sam se ocenjuješ) | korisnik sam | self |

## API rute

| Metoda | Putanja | Funkcija |
|---|---|---|
| GET | `/api/ai/usage` | `ai_usage` |
| GET | `/api/bootstrap` | `bootstrap` |
| GET | `/api/categories` | `list_categories` |
| POST | `/api/categories` | `create_category` |
| DELETE | `/api/categories/<int:category_id>` | `delete_category` |
| GET | `/api/categories/<int:category_id>` | `read_category` |
| PATCH | `/api/categories/<int:category_id>` | `update_category` |
| POST | `/api/categories/<int:category_id>/archive` | `archive_category` |
| POST | `/api/categories/<int:category_id>/generate` | `generate_questions` |
| POST | `/api/categories/<int:category_id>/generate/export` | `export_generation_prompt` |
| POST | `/api/categories/<int:category_id>/generate/import` | `import_generated` |
| POST | `/api/categories/<int:category_id>/generate/plan` | `generation_plan` |
| GET | `/api/categories/<int:category_id>/materials` | `list_materials` |
| POST | `/api/categories/<int:category_id>/materials` | `upload_materials` |
| POST | `/api/categories/<int:category_id>/move` | `move_category` |
| GET | `/api/categories/<int:category_id>/notes` | `list_notes` |
| POST | `/api/categories/<int:category_id>/notes` | `create_note` |
| POST | `/api/categories/<int:category_id>/notes/generate` | `generate_note` |
| GET | `/api/categories/<int:category_id>/questions` | `list_questions` |
| GET | `/api/categories/<int:category_id>/runs` | `list_runs` |
| GET | `/api/categories/<int:category_id>/stats` | `category_stats` |
| GET | `/api/categories/<int:category_id>/strategy` | `read_strategy` |
| POST | `/api/categories/<int:category_id>/strategy` | `write_strategy` |
| POST | `/api/categories/<int:category_id>/strategy/refresh` | `refresh_strategy` |
| GET | `/api/health` | `health` |
| GET | `/api/jobs` | `list_jobs` |
| GET | `/api/jobs/<str:job_id>` | `read_job` |
| POST | `/api/jobs/<str:job_id>/cancel` | `cancel_job` |
| DELETE | `/api/materials/<int:material_id>` | `delete_material` |
| GET | `/api/materials/<int:material_id>` | `read_material` |
| PATCH | `/api/materials/<int:material_id>` | `update_material` |
| POST | `/api/materials/<int:material_id>/reprocess` | `reprocess_material` |
| POST | `/api/misconceptions/<int:misconception_id>/resolve` | `resolve_misconception` |
| GET | `/api/models` | `list_models` |
| POST | `/api/models/refresh` | `refresh_models` |
| GET | `/api/network` | `network` |
| DELETE | `/api/notes/<int:note_id>` | `delete_note` |
| GET | `/api/proposals` | `list_proposals` |
| POST | `/api/proposals` | `create_proposal` |
| DELETE | `/api/proposals/<str:slug>` | `delete_proposal` |
| GET | `/api/proposals/<str:slug>` | `read_proposal` |
| GET | `/api/proposals/context` | `read_context` |
| POST | `/api/proposals/context/refresh` | `refresh_context` |
| POST | `/api/proposals/manual` | `create_manual_proposal` |
| DELETE | `/api/questions/<int:question_id>` | `purge_question` |
| GET | `/api/questions/<int:question_id>` | `read_question` |
| PATCH | `/api/questions/<int:question_id>` | `edit_question` |
| POST | `/api/questions/<int:question_id>/answer` | `answer_standalone` |
| POST | `/api/questions/<int:question_id>/meta` | `set_question_meta` |
| GET | `/api/settings` | `read_settings` |
| PATCH | `/api/settings` | `write_settings` |
| DELETE | `/api/settings/api-key` | `delete_api_key` |
| POST | `/api/settings/test-key` | `test_api_key` |
| POST | `/api/strategy/<int:strategy_id>/revert` | `revert_strategy` |
| POST | `/api/study/<int:session_id>/answer` | `answer_in_session` |
| POST | `/api/study/<int:session_id>/end` | `end_session` |
| GET | `/api/study/<int:session_id>/next` | `next_question` |
| POST | `/api/study/<int:session_id>/skip` | `skip_question` |
| GET | `/api/study/<int:session_id>/summary` | `session_summary` |
| POST | `/api/study/photo/<int:question_id>` | `upload_answer_photo` |
| POST | `/api/study/start` | `start_session` |
| POST | `/api/tts` | `speak` |
| GET | `/api/tts/voices` | `tts_voices` |

---

## Gde se šta menja

| Hoću da... | Diram |
|---|---|
| dodam novi tip pitanja | `app/quiz/types.py` (registar + validator), `app/quiz/grading.py` (ocenjivač), `web/js/render.js` (crtanje) — sva tri, uvek |
| promenim kako se bira sledeće pitanje | `app/quiz/scheduler.py` |
| promenim šta se šalje modelu | `app/ai/prompts.py` |
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

