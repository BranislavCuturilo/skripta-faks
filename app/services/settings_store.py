"""Podesavanja: kljuc-vrednost u bazi, sa tipiziranim podrazumevanim vrednostima.

API kljuc stoji u SQLite fajlu na tvom racunaru, u citljivom obliku. Sifrovanje
bez odvojenog mesta za kljuc sifre bilo bi pozoriste - kljuc bi morao da stoji
u istom folderu. Zastita je to sto fajl nikad ne napusta masinu i van je gita;
prema browseru se kljuc uvek vraca maskiran.
"""

import json
from typing import Any

from .. import db

DEFAULTS: dict[str, Any] = {
    "gemini_api_key": "",
    "provider": "gemini",
    # Prazno = automatski. Naziv modela se NE upisuje ovde tvrdo: Google ih
    # penzionise, a aplikacija koja nosi zamrznut naziv jednog dana prestane da
    # radi bez objasnjenja. Izbor pravi `services/ai_models.py` iz spiska koji
    # vrati sam kljuc; ovde zavrsi tek kad je razresen ili rucno izabran.
    "model_fast": "",
    "model_standard": "",
    "model_strong": "",
    "model_tts": "",
    "models_available": "[]",
    "models_checked_at": "",
    "ui_language": "sr",
    "question_language": "sr",
    # 1 = opusteno ("moze po nesto i da ne znam"), 5 = "moram sve da znam"
    "aggressiveness": 3,
    "session_length": 20,
    "tts_enabled": False,
    "tts_engine": "browser",
    "tts_voice": "",
    "tts_rate": 1.0,
    "auto_explain": True,
    "auto_strategy": True,
    "generate_variants": 2,
    "batch_char_budget": 60000,
    "theme": "dark",
    "onboarded": False,
}

SECRET_KEYS = {"gemini_api_key"}


def all_settings() -> dict[str, Any]:
    stored = {row["key"]: row["value"] for row in db.query("SELECT key, value FROM setting")}
    result: dict[str, Any] = {}
    for key, fallback in DEFAULTS.items():
        result[key] = _coerce(stored.get(key), fallback)
    for key, value in stored.items():
        if key not in result:
            result[key] = value
    return result


def public_settings() -> dict[str, Any]:
    """Za browser: tajne se vracaju maskirane, nikad u celini."""
    values = all_settings()
    for key in SECRET_KEYS:
        raw = str(values.get(key) or "")
        values[key] = ""
        values[f"{key}_set"] = bool(raw)
        values[f"{key}_hint"] = f"{raw[:4]}...{raw[-4:]}" if len(raw) >= 12 else ""
    return values


def get(key: str, fallback: Any = None) -> Any:
    row = db.query_one("SELECT value FROM setting WHERE key = ?", (key,))
    default = DEFAULTS.get(key, fallback)
    if row is None:
        return default
    return _coerce(row["value"], default)


def set_value(key: str, value: Any) -> None:
    stored = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
    db.execute(
        """
        INSERT INTO setting (key, value, updated_at) VALUES (?, ?, datetime('now'))
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')
        """,
        (key, stored),
    )


def set_many(values: dict) -> None:
    for key, value in values.items():
        # Prazan string na tajni znaci "nisam menjao", ne "obrisi".
        if key in SECRET_KEYS and value == "":
            continue
        set_value(key, value)


def clear(key: str) -> None:
    db.execute("DELETE FROM setting WHERE key = ?", (key,))


def _coerce(raw: Any, fallback: Any) -> Any:
    if raw is None:
        return fallback
    if isinstance(fallback, bool):
        return str(raw).strip().lower() in ("1", "true", "on", "yes", "da")
    if isinstance(fallback, int):
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            return fallback
    if isinstance(fallback, float):
        try:
            return float(raw)
        except (TypeError, ValueError):
            return fallback
    if isinstance(fallback, (dict, list)):
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return fallback
    return raw
