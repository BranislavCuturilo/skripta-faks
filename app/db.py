"""SQLite sloj: konekcija po niti, semа u migracijama, sitni upitni helperi.

Server je threading, a sqlite3 konekcija ne sme da prelazi granicu niti, pa
svaka nit dobija svoju. WAL dozvoljava citanje dok jedan pisac radi, sto je
tacno obrazac ove aplikacije (kviz cita, generisanje pise).
"""

import json
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Iterable, Iterator, Optional, Sequence

from . import config

_local = threading.local()

# Jedan pisac u procesu. SQLite bi i sam serijalizovao, ali ovako greska stize
# kao cekanje umesto kao "database is locked" usred generisanja pitanja.
_write_lock = threading.RLock()


MIGRATIONS: list[str] = []


def migration(sql: str) -> None:
    MIGRATIONS.append(sql)


migration(
    """
    CREATE TABLE category (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        parent_id       INTEGER REFERENCES category(id) ON DELETE CASCADE,
        name            TEXT    NOT NULL,
        slug            TEXT    NOT NULL,
        description     TEXT    NOT NULL DEFAULT '',
        study_prompt    TEXT    NOT NULL DEFAULT '',
        position        INTEGER NOT NULL DEFAULT 0,
        color           TEXT    NOT NULL DEFAULT '',
        archived_at     TEXT,
        created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
        updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX idx_category_parent ON category(parent_id, position);
    CREATE UNIQUE INDEX idx_category_slug_parent ON category(parent_id, slug);

    CREATE TABLE material (
        id                 INTEGER PRIMARY KEY AUTOINCREMENT,
        category_id        INTEGER NOT NULL REFERENCES category(id) ON DELETE CASCADE,
        filename           TEXT    NOT NULL,
        stored_name        TEXT    NOT NULL,
        rel_path           TEXT    NOT NULL,
        mime               TEXT    NOT NULL DEFAULT '',
        ext                TEXT    NOT NULL DEFAULT '',
        size_bytes         INTEGER NOT NULL DEFAULT 0,
        sha256             TEXT    NOT NULL DEFAULT '',
        kind               TEXT    NOT NULL DEFAULT 'other',
        extraction_status  TEXT    NOT NULL DEFAULT 'pending',
        extraction_method  TEXT    NOT NULL DEFAULT '',
        extraction_note    TEXT    NOT NULL DEFAULT '',
        quality_score      REAL,
        char_count         INTEGER NOT NULL DEFAULT 0,
        page_count         INTEGER,
        remote_uri         TEXT,
        remote_expires_at  TEXT,
        user_note          TEXT    NOT NULL DEFAULT '',
        include_in_study   INTEGER NOT NULL DEFAULT 1,
        created_at         TEXT    NOT NULL DEFAULT (datetime('now')),
        updated_at         TEXT    NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX idx_material_category ON material(category_id, created_at);
    CREATE INDEX idx_material_sha ON material(sha256);

    CREATE TABLE material_chunk (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        material_id   INTEGER NOT NULL REFERENCES material(id) ON DELETE CASCADE,
        ordinal       INTEGER NOT NULL,
        label         TEXT    NOT NULL DEFAULT '',
        text          TEXT    NOT NULL,
        char_count    INTEGER NOT NULL DEFAULT 0,
        page_from     INTEGER,
        page_to       INTEGER,
        created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX idx_chunk_material ON material_chunk(material_id, ordinal);
    """
)

migration(
    """
    CREATE TABLE generation_run (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        category_id     INTEGER NOT NULL REFERENCES category(id) ON DELETE CASCADE,
        provider        TEXT    NOT NULL DEFAULT 'gemini',
        model           TEXT    NOT NULL DEFAULT '',
        source_kind     TEXT    NOT NULL DEFAULT 'auto',
        status          TEXT    NOT NULL DEFAULT 'running',
        request_json    TEXT    NOT NULL DEFAULT '',
        response_text   TEXT    NOT NULL DEFAULT '',
        chunk_ids       TEXT    NOT NULL DEFAULT '[]',
        requested_count INTEGER NOT NULL DEFAULT 0,
        produced_count  INTEGER NOT NULL DEFAULT 0,
        rejected_count  INTEGER NOT NULL DEFAULT 0,
        duplicate_count INTEGER NOT NULL DEFAULT 0,
        prompt_tokens   INTEGER,
        output_tokens   INTEGER,
        error           TEXT    NOT NULL DEFAULT '',
        created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
        finished_at     TEXT
    );
    CREATE INDEX idx_run_category ON generation_run(category_id, created_at);

    CREATE TABLE question (
        id                 INTEGER PRIMARY KEY AUTOINCREMENT,
        category_id        INTEGER NOT NULL REFERENCES category(id) ON DELETE CASCADE,
        generation_run_id  INTEGER REFERENCES generation_run(id) ON DELETE SET NULL,
        type               TEXT    NOT NULL,
        stem               TEXT    NOT NULL,
        payload            TEXT    NOT NULL DEFAULT '{}',
        explanation        TEXT    NOT NULL DEFAULT '',
        difficulty         INTEGER NOT NULL DEFAULT 2,
        topic              TEXT    NOT NULL DEFAULT '',
        source_ref         TEXT    NOT NULL DEFAULT '',
        content_hash       TEXT    NOT NULL DEFAULT '',
        variant_group      TEXT    NOT NULL DEFAULT '',
        variant_index      INTEGER NOT NULL DEFAULT 0,
        state              TEXT    NOT NULL DEFAULT 'active',
        created_at         TEXT    NOT NULL DEFAULT (datetime('now')),
        updated_at         TEXT    NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX idx_question_category ON question(category_id, state, type);
    CREATE INDEX idx_question_variant ON question(variant_group, variant_index);
    CREATE INDEX idx_question_hash ON question(category_id, content_hash);

    -- Odvojeno od question: pitanje sme da bude regenerisano ili prepravljeno,
    -- a korisnikova beleska i flagovi to moraju da prezive.
    CREATE TABLE question_meta (
        question_id         INTEGER PRIMARY KEY REFERENCES question(id) ON DELETE CASCADE,
        note                TEXT    NOT NULL DEFAULT '',
        flag_review         INTEGER NOT NULL DEFAULT 0,
        flag_check_source   INTEGER NOT NULL DEFAULT 0,
        flag_irrelevant     INTEGER NOT NULL DEFAULT 0,
        flag_wrong          INTEGER NOT NULL DEFAULT 0,
        ignored_at          TEXT,
        deleted_at          TEXT,
        pinned              INTEGER NOT NULL DEFAULT 0,
        updated_at          TEXT    NOT NULL DEFAULT (datetime('now'))
    );
    """
)

migration(
    """
    CREATE TABLE study_session (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        category_id      INTEGER NOT NULL REFERENCES category(id) ON DELETE CASCADE,
        include_subtree  INTEGER NOT NULL DEFAULT 1,
        mode             TEXT    NOT NULL DEFAULT 'adaptive',
        aggressiveness   INTEGER NOT NULL DEFAULT 3,
        type_filter      TEXT    NOT NULL DEFAULT '',
        planned_count    INTEGER NOT NULL DEFAULT 0,
        asked_count      INTEGER NOT NULL DEFAULT 0,
        correct_count    INTEGER NOT NULL DEFAULT 0,
        started_at       TEXT    NOT NULL DEFAULT (datetime('now')),
        ended_at         TEXT
    );
    CREATE INDEX idx_session_category ON study_session(category_id, started_at);

    CREATE TABLE session_skip (
        session_id   INTEGER NOT NULL REFERENCES study_session(id) ON DELETE CASCADE,
        question_id  INTEGER NOT NULL REFERENCES question(id) ON DELETE CASCADE,
        reason       TEXT    NOT NULL DEFAULT 'skip',
        created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (session_id, question_id)
    );

    CREATE TABLE attempt (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        question_id    INTEGER NOT NULL REFERENCES question(id) ON DELETE CASCADE,
        session_id     INTEGER REFERENCES study_session(id) ON DELETE SET NULL,
        answer         TEXT    NOT NULL DEFAULT '{}',
        answer_hash    TEXT    NOT NULL DEFAULT '',
        is_correct     INTEGER NOT NULL DEFAULT 0,
        score          REAL    NOT NULL DEFAULT 0,
        graded_by      TEXT    NOT NULL DEFAULT 'local',
        feedback       TEXT    NOT NULL DEFAULT '',
        misconception  TEXT    NOT NULL DEFAULT '',
        response_ms    INTEGER NOT NULL DEFAULT 0,
        created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX idx_attempt_question ON attempt(question_id, created_at);
    CREATE INDEX idx_attempt_session ON attempt(session_id, created_at);

    -- Isti pogresan odgovor na isto pitanje ne sme dvaput da plati AI poziv.
    CREATE TABLE explanation_cache (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        question_id   INTEGER NOT NULL REFERENCES question(id) ON DELETE CASCADE,
        answer_hash   TEXT    NOT NULL,
        is_correct    INTEGER NOT NULL DEFAULT 0,
        score         REAL    NOT NULL DEFAULT 0,
        feedback      TEXT    NOT NULL DEFAULT '',
        misconception TEXT    NOT NULL DEFAULT '',
        created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
    );
    CREATE UNIQUE INDEX idx_expl_unique ON explanation_cache(question_id, answer_hash);

    CREATE TABLE question_schedule (
        question_id   INTEGER PRIMARY KEY REFERENCES question(id) ON DELETE CASCADE,
        category_id   INTEGER NOT NULL REFERENCES category(id) ON DELETE CASCADE,
        ease          REAL    NOT NULL DEFAULT 2.5,
        interval_days REAL    NOT NULL DEFAULT 0,
        due_at        TEXT    NOT NULL DEFAULT (datetime('now')),
        streak        INTEGER NOT NULL DEFAULT 0,
        lapses        INTEGER NOT NULL DEFAULT 0,
        seen_count    INTEGER NOT NULL DEFAULT 0,
        correct_count INTEGER NOT NULL DEFAULT 0,
        mastery       REAL    NOT NULL DEFAULT 0,
        last_seen_at  TEXT,
        updated_at    TEXT    NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX idx_schedule_due ON question_schedule(category_id, due_at);
    CREATE INDEX idx_schedule_mastery ON question_schedule(category_id, mastery);
    """
)

migration(
    """
    CREATE TABLE setting (
        key         TEXT PRIMARY KEY,
        value       TEXT NOT NULL DEFAULT '',
        updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
    );

    -- "App menja sam sebe": svaka verzija strategije se cuva, vidi i vraca.
    CREATE TABLE strategy (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        category_id  INTEGER REFERENCES category(id) ON DELETE CASCADE,
        kind         TEXT    NOT NULL,
        version      INTEGER NOT NULL DEFAULT 1,
        content      TEXT    NOT NULL DEFAULT '{}',
        rationale    TEXT    NOT NULL DEFAULT '',
        author       TEXT    NOT NULL DEFAULT 'system',
        active       INTEGER NOT NULL DEFAULT 1,
        created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX idx_strategy_lookup ON strategy(category_id, kind, active, version);

    CREATE TABLE misconception (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        category_id    INTEGER NOT NULL REFERENCES category(id) ON DELETE CASCADE,
        label          TEXT    NOT NULL,
        description    TEXT    NOT NULL DEFAULT '',
        topic          TEXT    NOT NULL DEFAULT '',
        evidence_count INTEGER NOT NULL DEFAULT 1,
        resolved_at    TEXT,
        first_seen_at  TEXT    NOT NULL DEFAULT (datetime('now')),
        last_seen_at   TEXT    NOT NULL DEFAULT (datetime('now'))
    );
    CREATE UNIQUE INDEX idx_misconception_label ON misconception(category_id, label);

    CREATE TABLE material_note (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        category_id  INTEGER NOT NULL REFERENCES category(id) ON DELETE CASCADE,
        material_id  INTEGER REFERENCES material(id) ON DELETE SET NULL,
        kind         TEXT    NOT NULL DEFAULT 'summary',
        title        TEXT    NOT NULL DEFAULT '',
        body         TEXT    NOT NULL DEFAULT '',
        author       TEXT    NOT NULL DEFAULT 'ai',
        created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX idx_note_category ON material_note(category_id, created_at);

    CREATE TABLE ai_call_log (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        purpose       TEXT    NOT NULL,
        provider      TEXT    NOT NULL DEFAULT 'gemini',
        model         TEXT    NOT NULL DEFAULT '',
        ok            INTEGER NOT NULL DEFAULT 0,
        http_status   INTEGER,
        duration_ms   INTEGER NOT NULL DEFAULT 0,
        prompt_chars  INTEGER NOT NULL DEFAULT 0,
        prompt_tokens INTEGER,
        output_tokens INTEGER,
        error         TEXT    NOT NULL DEFAULT '',
        created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX idx_ai_log_created ON ai_call_log(created_at);
    """
)

migration(
    """
    -- Odakle je pitanje: 'ai' (generisano iz gradiva) ili 'exam' (doslovno
    -- uvezeno iz fiksne liste ispitnih pitanja - AI ga nije pisao ni menjao).
    ALTER TABLE question ADD COLUMN origin TEXT NOT NULL DEFAULT 'ai';
    CREATE INDEX idx_question_origin ON question(category_id, origin);

    -- Sesija sme da se ogranici na jedno poreklo ('' = sva).
    ALTER TABLE study_session ADD COLUMN origin_filter TEXT NOT NULL DEFAULT '';
    """
)


def connect() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        config.ensure_dirs()
        conn = sqlite3.connect(config.DB_PATH, timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        _local.conn = conn
    return conn


def close_thread_connection() -> None:
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None


def statements(script: str) -> list[str]:
    """Podeli SQL skriptu na naredbe, postujuci navodnike i -- komentare.

    Ne koristimo `executescript`: on izda COMMIT pre nego sto krene, pa bi
    migracija ostala van transakcije i polomljena semа bi se upisala do pola.
    """
    result: list[str] = []
    current: list[str] = []
    in_string = False
    index = 0
    while index < len(script):
        char = script[index]

        if not in_string and script[index : index + 2] == "--":
            end = script.find("\n", index)
            index = len(script) if end < 0 else end
            continue

        if char == "'":
            # '' unutar stringa je escape-ovan navodnik, ne kraj stringa.
            if in_string and script[index + 1 : index + 2] == "'":
                current.append("''")
                index += 2
                continue
            in_string = not in_string

        if char == ";" and not in_string:
            piece = "".join(current).strip()
            if piece:
                result.append(piece)
            current = []
            index += 1
            continue

        current.append(char)
        index += 1

    tail = "".join(current).strip()
    if tail:
        result.append(tail)
    return result


def init_db() -> int:
    """Primeni sve migracije koje nedostaju. Vraca broj primenjenih."""
    conn = connect()
    with _write_lock:
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        applied = 0
        for index in range(current, len(MIGRATIONS)):
            conn.execute("BEGIN")
            try:
                for statement in statements(MIGRATIONS[index]):
                    conn.execute(statement)
                # PRAGMA user_version ne prima parametar.
                conn.execute(f"PRAGMA user_version = {index + 1}")
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            applied += 1
        return applied


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    conn = connect()
    with _write_lock:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except Exception:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")


def query(sql: str, params: Sequence[Any] = ()) -> list[dict]:
    return [dict(row) for row in connect().execute(sql, params).fetchall()]


def query_one(sql: str, params: Sequence[Any] = ()) -> Optional[dict]:
    row = connect().execute(sql, params).fetchone()
    return dict(row) if row else None


def scalar(sql: str, params: Sequence[Any] = (), default: Any = None) -> Any:
    row = connect().execute(sql, params).fetchone()
    return row[0] if row else default


def execute(sql: str, params: Sequence[Any] = ()) -> int:
    """Jedan upis van eksplicitne transakcije. Vraca lastrowid."""
    with _write_lock:
        cur = connect().execute(sql, params)
        return cur.lastrowid


def executemany(sql: str, seq: Iterable[Sequence[Any]]) -> None:
    with _write_lock:
        connect().executemany(sql, seq)


def insert(table: str, values: dict) -> int:
    cols = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    return execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(values.values()))


def update(table: str, row_id: int, values: dict, id_column: str = "id") -> None:
    if not values:
        return
    sets = ", ".join(f"{col} = ?" for col in values)
    execute(
        f"UPDATE {table} SET {sets} WHERE {id_column} = ?",
        [*values.values(), row_id],
    )


def json_field(row: Optional[dict], key: str, default: Any = None) -> Any:
    """Procitaj TEXT kolonu koja nosi JSON, bez rusenja na pokvarenom sadrzaju."""
    if not row:
        return default if default is not None else {}
    raw = row.get(key) or ""
    if not raw:
        return default if default is not None else {}
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return default if default is not None else {}
