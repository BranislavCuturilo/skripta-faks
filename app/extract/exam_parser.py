"""Prepoznavanje gotove liste ispitnih pitanja u obicnom tekstu - BEZ AI-ja.

Slucaj: fakultet podeli dokument sa fiksnom bazom pitanja, i na ispitu dodje
20 od tih 100, doslovno. Tu AI ne sme nista da menja ni "popravlja": pitanje
i ponudjeni odgovori ulaze u bazu tacno onako kako pisu u dokumentu.

Parser je namerno konzervativan. Ono sto ne prepozna sa sigurnoscu - ne
izmislja, nego prijavi (pitanje bez oznacenog tacnog odgovora, opcija bez
pitanja) i pusti korisnika da odluci: da doradi dokument, ili da pusti AI da
prepise nesredjen fajl (`services/exam_import.py`, drugi rezim).

Prepoznaje:
- pitanja: "1.", "1)", "1:", "Pitanje 1", "Питање 1."
- ponudjene odgovore: "a)", "a.", "(a)", "A)", "а)" (cirilica), "-", "•", "*"
- oznaku tacnog: "*" ili "+" ili "✓" ispred, "[x]" ispred, "*" / "✓" / "(tačno)"
  iza; "Tačan odgovor: b" / "Odgovor: b" / "Rešenje: b" posle opcija;
  i kljuc na kraju dokumenta ("Odgovori:" pa "1. b", "2) c", "3-a", "1b 2c 3a")
- otvorena pitanja: "Odgovor: tekst" posle pitanja -> kratak odgovor
- tacno/netacno: dve opcije tacno/netacno, da/ne, true/false
"""

import re
from dataclasses import dataclass, field
from typing import Optional

from .. import translit

# --------------------------------------------------------------------------
# obrasci
# --------------------------------------------------------------------------

_Q_START = re.compile(
    r"^\s*(?P<prefix>(?:pitanje|питање|zadatak|задатак|q)\s*[.:#]?\s*)?(?P<number>\d{1,3})\s*[.)\]:]\s*(?P<text>.*)$",
    re.IGNORECASE,
)
_LETTER_CLASS = "abcdefghABCDEFGHабвгдђежзАБВГДЂЕЖЗ"
# Opcija sa slovom: a) a. (a) [a] A) а) - latinica a-h, cirilica а-з.
_OPT_LETTER = re.compile(
    r"^\s*(?P<mark>[*+✓√]\s*|\[\s*[xX✓]\s*\]\s*|\(\s*[xX✓]\s*\)\s*)?"
    r"[\(\[]?\s*(?P<letter>[" + _LETTER_CLASS + r"])\s*[.)\]]\s+(?P<text>.+)$"
)
# Opcija sa brojem ("1)", "2.") - vazi samo kad pitanje pocinje recju "Pitanje",
# inace bi svaki nabrojani red bio opcija.
_OPT_DIGIT = re.compile(
    r"^\s*(?P<mark>[*+✓√]\s*|\[\s*[xX✓]\s*\]\s*)?[\(\[]?\s*(?P<digit>\d{1,2})\s*[.)\]]\s+(?P<text>.+)$"
)
_OPT_BULLET = re.compile(
    r"^\s*(?P<mark>\[\s*[xX✓]\s*\]\s*|\(\s*[xX✓]\s*\)\s*)?(?P<bullet>[-•·▪◦*+])\s+(?P<text>.+)$"
)
_OPT_CHECK_ONLY = re.compile(r"^\s*(?P<mark>\[\s*[xX✓]\s*\]|\[\s*\]|☐|☑|☒|✓|✔)\s+(?P<text>.+)$")

# Oznaka tacnog IZA teksta. Namerno bez "(x)": "f(x)" je matematika, ne oznaka.
_TRAILING_MARK = re.compile(
    r"\s*(?:\*+|✓|✔|√|\(\s*(?:ta[cč]no|тачно|tacan|tačan|тачан|correct)\s*\)|<[-=]{1,3}|←)\s*$",
    re.IGNORECASE,
)
_INLINE_ANSWER = re.compile(
    r"^\s*(?:ta[cč]an\s+odgovor|тачан\s+одговор|ta[cč]ni\s+odgovori|тачни\s+одговори|"
    r"odgovor|одговор|re[sš]enje|решење|re[sš]enja|решења|resenje|answer|key|klju[cč]|кључ)"
    r"\s*[:\-=]\s*(?P<value>.+)$",
    re.IGNORECASE,
)
_KEY_HEADER = re.compile(
    r"^\s*(?:odgovori|одговори|re[sš]enja|решења|ta[cč]ni\s+odgovori|тачни\s+одговори|"
    r"klju[cč](?:\s+odgovora)?|кључ(?:\s+одговора)?|answers?|answer\s+key|resenja)\s*[:.]?\s*$",
    re.IGNORECASE,
)
# "1. b", "1) c", "1-a", "1 b", "1: d", "1b", "6. a, c" - po jedan ili vise u redu.
_KEY_SEGMENT = re.compile(r"(\d{1,3})\s*[.):\-–]?\s*([^\d]*)")
_KEY_LETTER = re.compile(r"(?<!\w)([" + _LETTER_CLASS + r"])(?!\w)")

_TRUE_WORDS = {"tacno", "tačno", "тачно", "da", "да", "true", "yes", "t", "т"}
_FALSE_WORDS = {"netacno", "netačno", "нетачно", "ne", "не", "false", "no", "n", "н"}

_CYR_LETTERS = "абвгдђежз"
_LAT_LETTERS = "abcdefgh"


@dataclass
class ParsedOption:
    text: str
    correct: bool = False
    bullet: str = ""  # "*" / "-" / "" - da bi se razlikovala lista od oznake tacnog


@dataclass
class ParsedQuestion:
    number: int
    stem: str
    options: list[ParsedOption] = field(default_factory=list)
    answer_text: str = ""  # "Odgovor: ..." za otvoreno pitanje
    line: int = 0
    prefixed: bool = False  # "Pitanje 1." - tada su i "1)" "2)" opcije

    @property
    def has_answer(self) -> bool:
        return any(option.correct for option in self.options) or bool(self.answer_text)


@dataclass
class ParseReport:
    questions: list[ParsedQuestion]
    answer_key: dict[int, list[int]]
    warnings: list[str]


# --------------------------------------------------------------------------
# parsiranje
# --------------------------------------------------------------------------


def parse(text: str) -> ParseReport:
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    questions: list[ParsedQuestion] = []
    warnings: list[str] = []
    answer_key: dict[int, list[int]] = {}

    current: Optional[ParsedQuestion] = None
    in_key = False
    pending_blank = False

    for number, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            pending_blank = True
            continue

        if _KEY_HEADER.match(line):
            in_key = True
            current = None
            continue

        if in_key:
            pairs = _key_pairs(line)
            if pairs:
                for q_number, index in pairs:
                    answer_key.setdefault(q_number, []).append(index)
                continue
            # Red bez parova unutar kljuca: kljuc je gotov, nastavlja obican tekst.
            in_key = False

        q_match = _Q_START.match(line)
        # Brojcani pocetak je pitanje samo ako je broj sledeci u nizu (ili prvi),
        # inace je to "1) opcija" ili "2024." u tekstu.
        if q_match and _is_next_number(int(q_match.group("number")), questions, bool(q_match.group("prefix"))):
            current = ParsedQuestion(
                number=int(q_match.group("number")),
                stem=q_match.group("text").strip(),
                line=number,
                prefixed=bool(q_match.group("prefix")),
            )
            questions.append(current)
            pending_blank = False
            continue

        if current is None:
            pending_blank = False
            continue

        inline = _INLINE_ANSWER.match(line)
        if inline:
            _apply_inline_answer(current, inline.group("value").strip(), warnings)
            pending_blank = False
            continue

        option = _match_option(line, allow_digits=current.prefixed)
        if option is not None:
            current.options.append(option)
            pending_blank = False
            continue

        # Nastavak prethodnog elementa (prelomljen red): opcije ako ih ima,
        # inace teksta pitanja. Prazan red pre toga znaci novi pasus pitanja.
        if current.options:
            last = current.options[-1]
            last.text = (last.text + " " + line).strip()
            if _TRAILING_MARK.search(last.text):
                last.text = _TRAILING_MARK.sub("", last.text).strip()
                last.correct = True
        else:
            separator = "\n" if pending_blank else " "
            current.stem = (current.stem + separator + line).strip()
        pending_blank = False

    for question in questions:
        _resolve_star_bullets(question)
        if question.number in answer_key:
            for index in answer_key[question.number]:
                if 0 <= index < len(question.options):
                    question.options[index].correct = True
                else:
                    warnings.append(
                        f"Pitanje {question.number}: kljuc pokazuje na odgovor koji ne postoji."
                    )

    return ParseReport(questions=questions, answer_key=answer_key, warnings=warnings)


def _is_next_number(value: int, questions: list[ParsedQuestion], prefixed: bool) -> bool:
    if not questions:
        # Dokument sme da pocne od bilo kog broja ako pise "Pitanje 12."; goli
        # "12." na pocetku je verovatnije godina ili nabrajanje.
        return prefixed or value <= 3
    # Kad pitanja pocinju recju "Pitanje", goli broj ("2)") je opcija, ne pitanje.
    if questions[-1].prefixed and not prefixed:
        return False
    expected = questions[-1].number + 1
    # Dozvoli preskok (dokument je izostavio broj) ali ne i povratak unazad.
    return expected <= value <= expected + 2


def _match_option(line: str, allow_digits: bool = False) -> Optional[ParsedOption]:
    patterns = [_OPT_LETTER, _OPT_BULLET, _OPT_CHECK_ONLY]
    if allow_digits:
        patterns.insert(1, _OPT_DIGIT)
    for pattern in patterns:
        match = pattern.match(line)
        if not match:
            continue
        groups = match.groupdict()
        mark = (groups.get("mark") or "").strip()
        bullet = groups.get("bullet") or ""
        text = match.group("text").strip()
        correct = bool(mark) and mark not in ("[ ]", "[]", "☐")
        if _TRAILING_MARK.search(text):
            text = _TRAILING_MARK.sub("", text).strip()
            correct = True
        if not text:
            return None
        return ParsedOption(text=text, correct=correct, bullet=bullet)
    return None


def _resolve_star_bullets(question: ParsedQuestion) -> None:
    """'* tekst' je ili markdown lista ili oznaka tacnog - zavisi od ostalih.

    Ako SVE opcije pocinju zvezdicom, to je lista. Ako samo neke, a ostale
    pocinju crticom ili tackom, zvezdica je oznaka tacnog.
    """
    if not question.options:
        return
    starred = [option for option in question.options if option.bullet in ("*", "+")]
    if starred and len(starred) < len(question.options):
        for option in starred:
            option.correct = True


def _apply_inline_answer(question: ParsedQuestion, value: str, warnings: list[str]) -> None:
    """'Tačan odgovor: b' ili 'Odgovor: Beograd'."""
    letters = re.findall(r"(?<!\w)([" + _LETTER_CLASS + r"])(?!\w)", value)
    compact = re.sub(r"[\s,;/]+", "", value)
    if question.options and letters and len(compact) == len(letters):
        for letter in letters:
            index = _letter_index(letter)
            if 0 <= index < len(question.options):
                question.options[index].correct = True
            else:
                warnings.append(f"Pitanje {question.number}: odgovor '{letter}' ne postoji medju opcijama.")
        return
    if question.options:
        # Odgovor dat tekstom - nadji opciju koja se poklapa.
        wanted = _norm(value)
        for option in question.options:
            if _norm(option.text) == wanted:
                option.correct = True
                return
        warnings.append(f"Pitanje {question.number}: odgovor '{value[:40]}' se ne poklapa ni sa jednom opcijom.")
        return
    question.answer_text = value


def _key_pairs(line: str) -> list[tuple[int, int]]:
    """'1. b  2) c  6. a, c' -> [(1, 1), (2, 2), (6, 0), (6, 2)]."""
    pairs: list[tuple[int, int]] = []
    for match in _KEY_SEGMENT.finditer(line):
        letters = _KEY_LETTER.findall(match.group(2))
        for letter in letters:
            pairs.append((int(match.group(1)), _letter_index(letter)))
    return pairs


def _letter_index(letter: str) -> int:
    lowered = letter.lower()
    if lowered in _LAT_LETTERS:
        return _LAT_LETTERS.index(lowered)
    if lowered in _CYR_LETTERS:
        return _CYR_LETTERS.index(lowered)
    return -1


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", translit.to_latin(value).lower())


# --------------------------------------------------------------------------
# u oblik ugovora (contract.validate_one ga proverava kao i AI izlaz)
# --------------------------------------------------------------------------


def to_contract_items(
    report: ParseReport, *, keep_order: bool = True, source_ref: str = ""
) -> tuple[list[dict], list[dict]]:
    """Vrati (stavke za ugovor, preskocene sa razlogom)."""
    items: list[dict] = []
    skipped: list[dict] = []

    for question in report.questions:
        stem = question.stem.strip()
        if len(stem) < 5:
            skipped.append({"number": question.number, "stem": stem, "reason": "Tekst pitanja je prazan."})
            continue

        base = {
            "stem": stem,
            "explanation": "",
            "difficulty": 2,
            "topic": "",
            "source_ref": f"{source_ref} · pitanje {question.number}".strip(" ·"),
            "variant_group": "",
            "variant_index": 0,
        }

        if question.options:
            texts = [option.text for option in question.options]
            correct = [index for index, option in enumerate(question.options) if option.correct]
            if not correct:
                skipped.append(
                    {"number": question.number, "stem": stem,
                     "reason": "Nema oznacenog tacnog odgovora (ni oznake, ni kljuca)."}
                )
                continue
            truth = _as_true_false(texts, correct)
            if truth is not None:
                items.append({**base, "type": "true_false", "payload": {"correct": truth}})
            elif len(correct) == 1:
                items.append({
                    **base, "type": "mcq_single",
                    "payload": {"options": texts, "correct_index": correct[0], "shuffle": not keep_order},
                })
            else:
                items.append({
                    **base, "type": "mcq_multi",
                    "payload": {"options": texts, "correct_indices": correct, "shuffle": not keep_order},
                })
            continue

        if question.answer_text:
            truth = _truth_word(question.answer_text)
            if truth is not None:
                items.append({**base, "type": "true_false", "payload": {"correct": truth}})
            else:
                items.append({
                    **base, "type": "short_answer",
                    "payload": {"accepted": [question.answer_text], "key_points": [question.answer_text]},
                })
            continue

        skipped.append(
            {"number": question.number, "stem": stem,
             "reason": "Otvoreno pitanje bez odgovora u dokumentu."}
        )

    return items, skipped


def _as_true_false(texts: list[str], correct: list[int]) -> Optional[bool]:
    if len(texts) != 2 or len(correct) != 1:
        return None
    words = [_truth_word(text) for text in texts]
    if set(words) != {True, False}:
        return None
    return words[correct[0]]


def _truth_word(text: str) -> Optional[bool]:
    word = _norm(text)
    if word in {_norm(item) for item in _TRUE_WORDS}:
        return True
    if word in {_norm(item) for item in _FALSE_WORDS}:
        return False
    return None


def summary(report: ParseReport) -> dict:
    """Brojke za ekran: koliko je prepoznato i sta fali."""
    with_options = [question for question in report.questions if question.options]
    return {
        "total": len(report.questions),
        "with_options": len(with_options),
        "with_answer": sum(1 for question in report.questions if question.has_answer),
        "without_answer": sum(1 for question in report.questions if not question.has_answer),
        "open": sum(1 for question in report.questions if not question.options),
        "answer_key_entries": len(report.answer_key),
        "warnings": report.warnings,
    }
