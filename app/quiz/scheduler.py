"""Raspored ponavljanja i izbor sledeceg pitanja.

Sustina dogovora: ono sto gresis vraca se brzo i cesto, ono sto si utanacio
provlaci se tek povremeno. Koliko "tek povremeno" - odlucuje agresivnost:

  1  "moze po nesto i da ne znam"  - prag 0.70, dugi intervali, savladano retko
  3  sredina
  5  "moram sve da znam"           - prag 0.95, kratki intervali, savladano se i
                                     dalje vrti

Algoritam je SM-2 sa dve izmene: delimican skor (0.5 nije ni tacno ni netacno)
i mastery kao klizeci prosek, jer jedan pogodak ne znaci da se zna.
"""

import random
from typing import Optional

from .. import db
from . import duplicates

# Po agresivnosti: (prag savladanosti, mnozilac intervala, udeo savladanih u sesiji)
_PROFILES = {
    1: (0.70, 1.60, 0.30),
    2: (0.80, 1.30, 0.22),
    3: (0.85, 1.00, 0.15),
    4: (0.90, 0.80, 0.10),
    5: (0.95, 0.60, 0.06),
}

_MIN_EASE = 1.3
_MAX_EASE = 3.0
# Promasaj se vraca za 10 minuta - u istoj sesiji, ali ne odmah sledeci.
_LAPSE_MINUTES = 10


def profile(aggressiveness: int) -> tuple[float, float, float]:
    return _PROFILES.get(max(1, min(5, int(aggressiveness or 3))), _PROFILES[3])


def ensure_schedule(question_id: int, category_id: int) -> None:
    db.execute(
        """
        INSERT INTO question_schedule (question_id, category_id) VALUES (?, ?)
        ON CONFLICT(question_id) DO NOTHING
        """,
        (question_id, category_id),
    )


def record(question_id: int, score: float, aggressiveness: int = 3) -> dict:
    """Upisi rezultat i izracunaj kada pitanje sledeci put dolazi na red."""
    row = db.query_one("SELECT * FROM question_schedule WHERE question_id = ?", (question_id,))
    if not row:
        category_id = db.scalar("SELECT category_id FROM question WHERE id = ?", (question_id,))
        if category_id is None:
            return {}
        ensure_schedule(question_id, category_id)
        row = db.query_one("SELECT * FROM question_schedule WHERE question_id = ?", (question_id,))

    _, interval_multiplier, _ = profile(aggressiveness)
    score = max(0.0, min(1.0, float(score)))

    ease = float(row["ease"])
    interval = float(row["interval_days"])
    streak = int(row["streak"])
    lapses = int(row["lapses"])
    mastery = float(row["mastery"])

    if score >= 0.8:
        streak += 1
        ease = min(_MAX_EASE, ease + 0.10)
        interval = 1.0 if interval <= 0 else interval * ease
    elif score >= 0.5:
        streak = 0
        interval = max(0.5, interval * 1.15)
    else:
        streak = 0
        lapses += 1
        ease = max(_MIN_EASE, ease - 0.20)
        interval = 0.0

    interval *= interval_multiplier
    mastery = mastery * 0.7 + score * 0.3

    if interval <= 0:
        due_at = db.scalar("SELECT datetime('now', ?)", (f"+{_LAPSE_MINUTES} minutes",))
    else:
        due_at = db.scalar("SELECT datetime('now', ?)", (f"+{interval:.4f} days",))

    db.execute(
        """
        UPDATE question_schedule
           SET ease = ?, interval_days = ?, due_at = ?, streak = ?, lapses = ?,
               seen_count = seen_count + 1,
               correct_count = correct_count + ?,
               mastery = ?, last_seen_at = datetime('now'), updated_at = datetime('now')
         WHERE question_id = ?
        """,
        (ease, interval, due_at, streak, lapses, 1 if score >= 0.8 else 0, mastery, question_id),
    )
    return {
        "due_at": due_at,
        "interval_days": round(interval, 3),
        "mastery": round(mastery, 3),
        "streak": streak,
        "lapses": lapses,
    }


def pick(
    category_ids: list[int],
    *,
    limit: int = 20,
    aggressiveness: int = 3,
    session_id: Optional[int] = None,
    type_filter: Optional[list[str]] = None,
    mode: str = "adaptive",
    origin: str = "",
) -> list[dict]:
    """Izaberi pitanja za sesiju.

    U jednoj sesiji nikad dvaput isto: ni dva pitanja iz iste grupe
    varijacija, ni dva ista pitanja iz razlicitih kategorija predmeta
    (`quiz/duplicates.py`). "Vec bilo" ukljucuje i ono sto je u ovoj sesiji
    odgovoreno ili preskoceno - sledece pitanje se bira posebno (`limit=1`),
    pa bi bez toga varijacija upravo odgovorenog pitanja dosla odmah posle njega.
    """
    if not category_ids:
        return []

    mastery_threshold, _, mastered_share = profile(aggressiveness)
    rows = _candidates(category_ids, session_id, type_filter, origin)
    if not rows:
        return []
    seen = _seen_in_session(session_id) if session_id else []

    if mode == "new":
        pool = [row for row in rows if row["seen_count"] == 0] or rows
        return _without_repeats(pool, limit, seen)
    if mode == "weak":
        pool = sorted(rows, key=lambda row: (row["mastery"], -row["lapses"]))
        return _without_repeats(pool, limit, seen)
    if mode == "flagged":
        pool = [row for row in rows if row["flag_review"] or row["pinned"]]
        return _without_repeats(pool, limit, seen)
    if mode == "all":
        pool = list(rows)
        random.shuffle(pool)
        return _without_repeats(pool, limit, seen)

    return _without_repeats(
        _adaptive_order(rows, mastery_threshold, mastered_share, limit), limit, seen
    )


def _adaptive_order(
    rows: list[dict], mastery_threshold: float, mastered_share: float, limit: int
) -> list[dict]:
    unseen: list[dict] = []
    due_weak: list[dict] = []
    due_ok: list[dict] = []
    mastered: list[dict] = []

    for row in rows:
        if row["seen_count"] == 0:
            unseen.append(row)
        elif row["mastery"] >= mastery_threshold and not row["is_due"]:
            mastered.append(row)
        elif row["is_due"] or row["mastery"] < mastery_threshold:
            (due_weak if row["mastery"] < mastery_threshold else due_ok).append(row)
        else:
            mastered.append(row)

    # Unutar grupe "gresi se" - najslabije prvo, sa malo suma da redosled ne
    # bude identican svaki put.
    due_weak.sort(key=lambda row: row["mastery"] + random.uniform(0, 0.08))
    due_ok.sort(key=lambda row: row["due_at"])
    random.shuffle(unseen)
    random.shuffle(mastered)

    flagged = [row for row in rows if row["flag_review"] or row["pinned"]]
    random.shuffle(flagged)

    mastered_slots = max(0, int(round(limit * mastered_share)))
    flagged_slots = min(len(flagged), max(1, limit // 8)) if flagged else 0

    ordered: list[dict] = []
    ordered.extend(flagged[:flagged_slots])
    ordered.extend(due_weak)
    ordered.extend(due_ok)
    ordered.extend(unseen)
    ordered.extend(mastered[:mastered_slots])

    if len(ordered) < limit:
        remaining = [row for row in rows if row not in ordered]
        random.shuffle(remaining)
        ordered.extend(remaining)
    return ordered


def _without_repeats(rows: list[dict], limit: int, seen: list[dict]) -> list[dict]:
    seen_groups = {row["variant_group"] for row in seen if row["variant_group"]}
    seen_ids: set[int] = set()
    same = duplicates.Index(_comparable(row) for row in seen)
    result: list[dict] = []
    for row in rows:
        if row["id"] in seen_ids:
            continue
        group = row["variant_group"] or ""
        if group and group in seen_groups:
            continue
        question = _comparable(row)
        if same.match(question):
            continue
        seen_ids.add(row["id"])
        if group:
            seen_groups.add(group)
        same.add(question)
        result.append(row)
        if len(result) >= limit:
            break
    return result


def _comparable(row: dict) -> dict:
    return {"type": row["type"], "stem": row["stem"], "payload": db.json_field(row, "payload")}


def _seen_in_session(session_id: int) -> list[dict]:
    """Pitanja koja su u ovoj sesiji vec odgovorena ili preskocena."""
    return db.query(
        """
        SELECT q.type, q.stem, q.payload, q.variant_group FROM question q
         WHERE q.id IN (SELECT question_id FROM attempt WHERE session_id = ?)
            OR q.id IN (SELECT question_id FROM session_skip WHERE session_id = ?)
        """,
        (session_id, session_id),
    )


def _candidates(
    category_ids: list[int],
    session_id: Optional[int],
    type_filter: Optional[list[str]],
    origin: str = "",
) -> list[dict]:
    marks = ", ".join("?" for _ in category_ids)
    params: list = list(category_ids)

    type_clause = ""
    if type_filter:
        type_clause = f"AND q.type IN ({', '.join('?' for _ in type_filter)})"
        params.extend(type_filter)
    if origin:
        type_clause += " AND q.origin = ?"
        params.append(origin)

    skip_clause = ""
    if session_id:
        # Dva izuzimanja, oba vezana za tekucu sesiju:
        #   - preskoceno ("ne sada")
        #   - vec odgovoreno u ovoj sesiji
        # Bez drugog, netacan odgovor obara mastery na dno i gura `due_at` na
        # +10 minuta, pa adaptivni redosled isto pitanje vraca odmah - i vraca
        # ga dok se ne pogodi. Ponavljanje pripada SLEDECOJ sesiji.
        skip_clause = (
            "AND q.id NOT IN (SELECT question_id FROM session_skip WHERE session_id = ?) "
            "AND q.id NOT IN (SELECT question_id FROM attempt WHERE session_id = ?)"
        )
        params.extend((session_id, session_id))

    return db.query(
        f"""
        SELECT q.id, q.category_id, q.type, q.variant_group, q.difficulty, q.topic,
               q.stem, q.payload,
               COALESCE(s.mastery, 0)       AS mastery,
               COALESCE(s.seen_count, 0)    AS seen_count,
               COALESCE(s.lapses, 0)        AS lapses,
               COALESCE(s.due_at, '')       AS due_at,
               CASE WHEN s.question_id IS NULL OR s.due_at <= datetime('now')
                    THEN 1 ELSE 0 END       AS is_due,
               COALESCE(m.flag_review, 0)   AS flag_review,
               COALESCE(m.pinned, 0)        AS pinned
          FROM question q
          LEFT JOIN question_schedule s ON s.question_id = q.id
          LEFT JOIN question_meta m     ON m.question_id = q.id
         WHERE q.category_id IN ({marks})
           AND q.state = 'active'
           AND COALESCE(m.deleted_at, '') = ''
           AND COALESCE(m.ignored_at, '') = ''
           {type_clause}
           {skip_clause}
        """,
        params,
    )


def stats(category_ids: list[int], aggressiveness: int = 3) -> dict:
    """Brojevi za ekran kategorije: koliko je novo, slabo, savladano, na redu."""
    if not category_ids:
        return {"total": 0, "unseen": 0, "weak": 0, "mastered": 0, "due": 0, "threshold": 0}

    threshold, _, _ = profile(aggressiveness)
    rows = _candidates(category_ids, None, None)
    return {
        "total": len(rows),
        "unseen": sum(1 for row in rows if row["seen_count"] == 0),
        "weak": sum(1 for row in rows if row["seen_count"] > 0 and row["mastery"] < threshold),
        "mastered": sum(1 for row in rows if row["mastery"] >= threshold),
        "due": sum(1 for row in rows if row["is_due"] and row["seen_count"] > 0),
        "flagged": sum(1 for row in rows if row["flag_review"] or row["pinned"]),
        "threshold": threshold,
    }
