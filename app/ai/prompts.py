"""Sablonski promptovi.

Dogovorena optimizacija je: sto vise sadrzaja po pozivu, sto manje poziva. Zato
jedan poziv nosi ceo komad gradiva i trazi desetine pitanja odjednom, umesto
pitanja po pitanja.

Svaki prompt ume i da se izveze kao obican tekst (`export_bundle`) da bi mogao
da se odnese u Claude ili bilo koji drugi model kad Gemini ne uspe - odgovor se
vraca kroz isti `contract.parse`.
"""

import json
from typing import Optional

from ..quiz import types as question_types

SYSTEM_GENERATE = """\
Ti si iskusan asistent za pripremu ispita. Od datog gradiva pravis pitanja za \
aktivno ucenje.

Pravila koja se ne krse:
1. Pitanja izvodis ISKLJUCIVO iz dostavljenog gradiva. Nista ne izmisljas i \
nista ne dodajes iz opsteg znanja. Ako gradivo nesto ne pokriva, o tome nema \
pitanja.
2. Svako pitanje mora da ima tacan odgovor koji se moze proveriti u gradivu.
3. Objasnjenje ('explanation') pises UVEK, i u njemu kazes zasto je tacan \
odgovor tacan, a kod ponudjenih odgovora i zasto su ostali netacni.
4. Distraktori su tipicne greske i cesta mesanja pojmova, nikad ocigledne \
gluposti i nikad "nista od navedenog".
5. Ne ponavljas isto pitanje drugim recima, osim kad se izricito traze \
varijacije - tada ih oznacavas istim 'variant_group'.
6. Odgovaras iskljucivo JSON-om po zadatoj semi, bez ijedne reci van JSON-a.
7. Jezik i PISMO su zadati u zadatku i vaze za SVAKO polje: tekst pitanja, svi \
ponudjeni odgovori, objasnjenje i tema. Nikad ne mesas latinicu i cirilicu u \
istom pitanju, cak i kad je gradivo napisano drugim pismom - tada ga preslovis.
8. Kod ponudjenih odgovora tacan odgovor stavljas na NASUMICNO mesto, \
ravnomerno po svim pozicijama. Ne sme pretezno da bude prvi.\
"""

SYSTEM_GRADE = """\
Ti ocenjujes odgovor studenta na pitanje iz njegovog gradiva. Strog si ali \
posten: sustina je vaznija od formulacije, ali pogresna sustina je netacna bez \
obzira koliko lepo zvuci.

U 'feedback' pises kratko i konkretno: sta je tacno u odgovoru, sta nije, i \
zasto je tacan odgovor tacan. Obracas se studentu direktno, na njegovom jeziku.
U 'misconception' upisujes kratku oznaku greske u razmisljanju ako je vidis \
(npr. "mesa uslovnu i bezuslovnu verovatnocu"), inace prazan string.

Odgovaras iskljucivo JSON-om, bez ijedne reci van JSON-a.\
"""


def question_type_reference(allowed: Optional[list[str]] = None) -> str:
    lines = []
    for item in question_types.all_types():
        if allowed and item.key not in allowed:
            continue
        lines.append(f'- "{item.key}" ({item.label}): {item.hint} {item.ai_instructions}'.strip())
    return "\n".join(lines)


def output_schema() -> str:
    return """\
{
  "questions": [
    {
      "type": "<jedan od dozvoljenih kljuceva>",
      "stem": "tekst pitanja",
      "payload": { /* polja zavise od tipa, videti spisak iznad */ },
      "explanation": "zasto je tacan odgovor tacan i zasto ostali nisu",
      "difficulty": 1,
      "topic": "kratka oznaka teme iz gradiva",
      "source_ref": "gde u gradivu (npr. 'strana 12' ili 'Lekcija 3')",
      "variant_group": "prazno, ili ista oznaka za varijacije istog pitanja",
      "variant_index": 0
    }
  ]
}"""


def build_generation_prompt(
    *,
    category_path: str,
    study_prompt: str,
    material: str,
    count: int,
    type_mix: Optional[dict] = None,
    allowed_types: Optional[list[str]] = None,
    variants: int = 0,
    language: str = "sr",
    misconceptions: Optional[list[dict]] = None,
    existing_stems: Optional[list[str]] = None,
    strategy_note: str = "",
) -> str:
    blocks: list[str] = []

    blocks.append(f"PREDMET / CELINA: {category_path}")
    blocks.append(f"JEZIK PITANJA: {_language_name(language)}")

    if study_prompt.strip():
        blocks.append(
            "STA SE TACNO UCI (uputstvo korisnika - ovo ogranicava obim, postuj ga doslovno):\n"
            + study_prompt.strip()
        )
    else:
        blocks.append("STA SE TACNO UCI: nije zadato - pokrij celo dostavljeno gradivo ravnomerno.")

    blocks.append("DOZVOLJENI TIPOVI PITANJA:\n" + question_type_reference(allowed_types))

    if type_mix:
        distribution = ", ".join(f"{key}: {value}" for key, value in type_mix.items() if value)
        blocks.append(f"TRAZENA RASPODELA PO TIPOVIMA (priblizno): {distribution}")
    else:
        blocks.append(
            "RASPODELA: mesaj tipove sto ravnomernije. Bar trecina pitanja neka NE bude "
            "sa ponudjenim odgovorima."
        )

    if variants > 0:
        blocks.append(
            f"VARIJACIJE: za deo pitanja napravi po {variants} varijacije iste provere znanja "
            "(obrnut smer tvrdnje, negacija, zamenjene uloge pojmova, drugi brojevi). "
            "Varijacije nose ISTI 'variant_group' i razlicit 'variant_index'. "
            "Varijacija mora da ima svoj tacan odgovor - ne prepisuj isti."
        )

    if misconceptions:
        lines = "\n".join(
            f"- {item['label']}" + (f" ({item['description']})" if item.get("description") else "")
            for item in misconceptions[:12]
        )
        blocks.append(
            "GRESKE KOJE OVAJ KORISNIK PONAVLJA - ciljaj ih vise nego ostalo:\n" + lines
        )

    if strategy_note.strip():
        blocks.append("DODATNO UPUTSTVO IZ DOSADASNJEG UCENJA:\n" + strategy_note.strip())

    if existing_stems:
        sample = "\n".join(f"- {stem[:110]}" for stem in existing_stems[:60])
        blocks.append(
            "VEC POSTOJECA PITANJA - nemoj ih ponavljati ni prepricavati:\n" + sample
        )

    blocks.append(f"BROJ PITANJA: napravi tacno {count}, ili koliko god gradivo posteno nosi.")
    blocks.append("IZLAZNI FORMAT (samo ovo, bez uvoda i bez markdown ograda):\n" + output_schema())
    blocks.append("GRADIVO:\n" + "-" * 60 + "\n" + material + "\n" + "-" * 60)

    return "\n\n".join(blocks)


def build_grading_prompt(
    *,
    question_type: str,
    stem: str,
    payload: dict,
    answer_text: str,
    language: str = "sr",
    has_photo: bool = False,
) -> str:
    expectation = {
        "short_answer": "accepted / key_points",
        "long_answer": "key_points / model_answer",
        "fill_blank": "accepted po praznini",
        "work_it_out": "final_answer / expected_steps",
    }.get(question_type, "payload")

    photo_note = (
        "\nStudent je poslao SLIKU svog resenja. Procitaj postupak sa slike, proveri korake "
        "i konacan rezultat. Ako je postupak tacan a racun pogresan, to jasno razdvoji."
        if has_photo
        else ""
    )

    return f"""\
JEZIK ODGOVORA: {_language_name(language)}

PITANJE ({question_type}):
{stem}

OCEKIVANO ({expectation}):
{json.dumps(payload, ensure_ascii=False, indent=2)}

ODGOVOR STUDENTA:
{answer_text or "(prazno)"}{photo_note}

Vrati iskljucivo ovaj JSON:
{{
  "is_correct": true,
  "score": 1.0,
  "feedback": "kratko objasnjenje studentu",
  "misconception": ""
}}
- score je izmedju 0 i 1; delimicno tacan odgovor nosi delimican skor.
- is_correct je true samo ako je score >= 0.8."""


def build_explanation_prompt(
    *, stem: str, correct_answer: str, given_answer: str, language: str = "sr"
) -> str:
    return f"""\
JEZIK: {_language_name(language)}

PITANJE:
{stem}

TACAN ODGOVOR:
{correct_answer}

STUDENT JE ODGOVORIO:
{given_answer or "(prazno)"}

Objasni studentu, u 2-4 recenice: zasto njegov odgovor nije tacan i zasto je tacan
odgovor tacan. Ako u njegovom odgovoru vidis prepoznatljivu gresku u razmisljanju,
imenuj je.

Vrati iskljucivo:
{{"feedback": "...", "misconception": ""}}"""


def build_strategy_prompt(*, category_path: str, evidence: dict, language: str = "sr") -> str:
    """Prompt kojim sistem prepravlja sopstvenu strategiju generisanja.

    Ovo je ono "app menja sam sebe" - menja se sadrzaj u bazi koji ulazi u
    sledeci prompt, nikad kod aplikacije.
    """
    return f"""\
JEZIK: {_language_name(language)}

Analiziras kako jedan student uci gradivo iz celine: {category_path}

PODACI O DOSADASNJEM UCENJU:
{json.dumps(evidence, ensure_ascii=False, indent=2)}

Na osnovu ovoga predlozi izmenu strategije ispitivanja. Gledaj:
- na kojim temama grese, i da li je greska u pojmu ili u primeni
- koji tipovi zadataka mu idu, a koje izbegava ili stalno gresi
- da li su pitanja prelaka ili preteska u odnosu na rezultate
- da li se neka greska ponavlja u razlicitim temama (to je obrazac razmisljanja,
  ne rupa u gradivu)

Vrati iskljucivo:
{{
  "type_mix": {{"mcq_single": 3, "short_answer": 5, "work_it_out": 2}},
  "difficulty_bias": 0,
  "focus_topics": ["tema 1", "tema 2"],
  "avoid_topics": [],
  "misconceptions": [{{"label": "kratka oznaka", "description": "sta tacno mesa"}}],
  "generation_note": "recenica-dve koje ce se dodati u sledeci prompt za generisanje",
  "rationale": "zasto predlazes bas ovo, studentu razumljivo"
}}
- type_mix su relativni odnosi, ne apsolutni brojevi.
- difficulty_bias je -1 (lakse), 0 (isto) ili +1 (teze)."""


def build_material_note_prompt(*, category_path: str, material: str, gaps: list[str], language: str = "sr") -> str:
    gap_text = "\n".join(f"- {item}" for item in gaps[:15]) or "- (nema izdvojenih rupa)"
    return f"""\
JEZIK: {_language_name(language)}

CELINA: {category_path}

Student ponavlja greske u ovim tackama:
{gap_text}

GRADIVO:
{"-" * 60}
{material}
{"-" * 60}

Napisi mu kratku dopunu za ucenje koja pokriva bas te tacke: definicije koje mu
ocigledno nedostaju, razliku izmedju pojmova koje mesa, i jedan resen primer.
Drzi se dostavljenog gradiva.

Vrati iskljucivo:
{{"title": "naslov dopune", "body": "tekst u markdownu"}}"""


SYSTEM_PROPOSAL = """\
Ti si iskusan programer koji nekome pomaze da nadogradi aplikaciju koju koristi, \
a nije je pisao.

Dobijas mapu projekta i zahtev korisnika napisan svojim recima. Tvoj posao NIJE \
da napises kod - nego da zahtev prevedes u nalog koji drugi AI asistent moze da \
izvrsi bez nagadjanja: sta se tacno menja, u kojim fajlovima, i sta ne sme da se \
pokvari.

Pravila:
1. Predlazes SAMO ono sto se uklapa u navedena pravila projekta. Ako zahtev trazi \
spoljnu biblioteku, kazi to otvoreno i ponudi resenje standardnom bibliotekom, \
ili jasno napisi da ovo menja osnovnu odluku projekta.
2. Pominjes samo fajlove koji stvarno postoje u mapi. Ne izmisljas putanje.
3. Ako zahtev dira vise mesta koja moraju da se menjaju zajedno (npr. novi tip \
pitanja trazi izmenu na tri mesta) - navodis sva tri.
4. Ako je zahtev nejasan, ne pogadjas: u 'pitanja' upisujes sta treba da se \
razjasni pre pocetka.
5. 'claude_brief' je tekst koji korisnik doslovno kopira u placenog AI asistenta. \
Pisan je asistentu, ne korisniku, i sam po sebi je dovoljan.

Odgovaras iskljucivo JSON-om, bez ijedne reci van JSON-a.\
"""


def build_proposal_prompt(*, context: str, request: str, usage: str, language: str = "sr") -> str:
    return f"""\
JEZIK ODGOVORA: {_language_name(language)}

{"=" * 60}
MAPA PROJEKTA
{"=" * 60}
{context}

{"=" * 60}
KAKO KORISNIK KORISTI APLIKACIJU
{"=" * 60}
{usage}

{"=" * 60}
ZAHTEV KORISNIKA (njegovim recima)
{"=" * 60}
{request}

{"=" * 60}

Vrati iskljucivo ovaj JSON:
{{
  "title": "kratak naslov predloga",
  "understood": "sta si razumeo da korisnik zeli, njegovim recnikom",
  "feasible": true,
  "breaks_rules": "",
  "approach": "kako bi se to uradilo, u 3-6 recenica",
  "files": [
    {{"path": "app/quiz/types.py", "change": "sta se tu tacno menja"}}
  ],
  "must_not_break": ["sta mora da nastavi da radi isto"],
  "questions": ["sta treba razjasniti pre pocetka, ako ista"],
  "effort": "mali",
  "claude_brief": "ceo nalog za AI asistenta, spreman za kopiranje"
}}
- feasible je false ako se ovo ne moze uraditi bez krsenja pravila projekta.
- breaks_rules popunjavas samo ako zahtev zaista krsi neko pravilo - napisi koje.
- effort je "mali", "srednji" ili "veliki"."""


def export_bundle(system: str, prompt: str, purpose: str = "generisanje pitanja") -> str:
    """Ceo poziv kao tekst za lepljenje u drugi model."""
    return f"""\
{"=" * 70}
skripta-faks - prompt za {purpose}
{"=" * 70}

UPUTSTVO:
1. Ceo tekst ispod (od 'SISTEMSKO UPUTSTVO' do kraja) nalepi u Claude,
   ChatGPT ili bilo koji drugi model.
2. Kad model odgovori, kopiraj CEO njegov odgovor.
3. Vrati se u aplikaciju, otvori istu kategoriju -> Generisanje ->
   "Nalepi odgovor iz drugog modela" i nalepi ga tamo.
4. Aplikacija ce ga proveriti kroz isti format kao i Gemini-jev odgovor;
   neispravna pitanja ce biti odbijena sa razlogom, ispravna upisana.

Ako model pocne odgovor recima ili markdown ogradama, ne smeta - aplikacija to
uklanja sama.

{"=" * 70}
SISTEMSKO UPUTSTVO
{"=" * 70}
{system}

{"=" * 70}
ZADATAK
{"=" * 70}
{prompt}
"""


def _language_name(code: str) -> str:
    return {
        "sr": "srpski, ISKLJUCIVO latinica (nijedno cirilicno slovo, ni u jednom polju)",
        "sr-cyrl": "srpski, ISKLJUCIVO cirilica (nijedno latinicno slovo osim formula i stranih skracenica)",
        "en": "engleski",
        "de": "nemacki",
        "ru": "ruski",
    }.get(code, code)


SYSTEM_TRANSCRIBE = """\
Ti PREPISUJES gotovu listu ispitnih pitanja iz dostavljenog dokumenta u JSON. \
Nisi autor pitanja i ne smes nista da menjas.

Pravila koja se ne krse:
1. Tekst svakog pitanja ('stem') i svaki ponudjeni odgovor prepisujes DOSLOVNO, \
znak po znak: ne skracujes, ne prepricavas, ne ispravljas gramatiku ni slovne \
greske, ne dodajes ni jednu rec. Jedino sto izostavljas su oznake nabrajanja \
ispred teksta ("1.", "a)", "-", "*") i oznake tacnog odgovora.
2. Ne dodajes pitanja kojih nema u dokumentu i ne izostavljas nijedno koje \
postoji. Ne pravis varijacije.
3. Redosled ponudjenih odgovora zadrzavas tacno kao u dokumentu.
4. Ako u dokumentu pise koji je odgovor tacan (zvezdica, podebljano, kljuc na \
kraju, "Tacan odgovor: b"), to je tacan odgovor i upisujes "answer_source": \
"document". Ako dokument NE kaze koji je tacan, odredi ga po svom znanju i \
upisi "answer_source": "model" - da korisnik zna da to mora da proveri.
5. Tipovi koje smes da koristis: "mcq_single", "mcq_multi", "true_false", \
"short_answer" (dokument daje odgovor tekstom), "numeric", "long_answer" \
(otvoreno pitanje bez odgovora u dokumentu - 'key_points' su tvoji, pa je \
answer_source "model").
6. 'explanation' sme da bude prazno. 'source_ref' je broj pitanja iz dokumenta.
7. Jezik i pismo su oni iz dokumenta - ne prevodis i ne preslovljavas.
8. Odgovaras iskljucivo JSON-om po zadatoj semi, bez ijedne reci van JSON-a.\
"""


def build_transcription_prompt(*, category_path: str, material: str, has_files: bool = False) -> str:
    source = (
        "Pitanja su u PRILOZENIM FAJLOVIMA (sken, slika, PDF). Procitaj ih pazljivo i prepisi "
        "doslovno.\n" + material
        if has_files
        else "DOKUMENT SA PITANJIMA:\n" + "-" * 60 + "\n" + material + "\n" + "-" * 60
    )
    return f"""\
PREDMET / CELINA: {category_path}

ZADATAK: prepisi SVA ispitna pitanja iz dokumenta ispod u JSON, doslovno.

IZLAZNI FORMAT (samo ovo, bez uvoda i bez markdown ograda):
{{
  "questions": [
    {{
      "type": "mcq_single",
      "stem": "tekst pitanja, doslovno iz dokumenta",
      "payload": {{"options": ["doslovno", "doslovno", "doslovno"], "correct_index": 0}},
      "answer_source": "document",
      "explanation": "",
      "difficulty": 2,
      "topic": "",
      "source_ref": "pitanje 1"
    }}
  ]
}}
Polja 'payload' po tipu: mcq_single -> options + correct_index; mcq_multi -> options +
correct_indices; true_false -> correct (true/false); short_answer -> accepted (lista
prihvatljivih doslovnih odgovora) + key_points; numeric -> value (+ unit); long_answer ->
key_points (+ model_answer).

{source}"""
