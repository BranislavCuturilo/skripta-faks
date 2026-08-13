"""Poslovi koji traju duze od jednog zahteva.

Generisanje pitanja iz cele skripte je nekoliko AI poziva i traje minutima.
Browser to ne sme da ceka u jednom zahtevu, pa posao ide u nit, a frontend
pita za napredak.

Registar je u memoriji namerno: restart aplikacije nema sta da nastavi, a
lazirati trajnost posla koji je prekinut usred AI poziva bilo bi gore od
posteno prijavljenog "prekinuto".
"""

import threading
import traceback
import uuid
from typing import Any, Callable, Optional

_jobs: dict[str, dict] = {}
_lock = threading.RLock()
_MAX_KEPT = 50


class Job:
    def __init__(self, job_id: str, kind: str, title: str):
        self.id = job_id
        self.kind = kind
        self.title = title

    def progress(self, done: int, total: int, message: str = "") -> None:
        with _lock:
            record = _jobs.get(self.id)
            if not record:
                return
            record["done"] = done
            record["total"] = total
            if message:
                record["message"] = message
                record["log"].append(message)
                del record["log"][:-40]

    def log(self, message: str) -> None:
        with _lock:
            record = _jobs.get(self.id)
            if record:
                record["log"].append(message)
                record["message"] = message
                del record["log"][:-40]

    @property
    def cancelled(self) -> bool:
        with _lock:
            record = _jobs.get(self.id)
            return bool(record and record.get("cancel"))


def start(kind: str, title: str, target: Callable[[Job], Any]) -> dict:
    job_id = uuid.uuid4().hex
    with _lock:
        _prune()
        _jobs[job_id] = {
            "id": job_id,
            "kind": kind,
            "title": title,
            "status": "running",
            "done": 0,
            "total": 0,
            "message": "Pokrenuto.",
            "log": [],
            "result": None,
            "error": "",
        }

    handle = Job(job_id, kind, title)

    def wrapper() -> None:
        try:
            result = target(handle)
            _finish(job_id, "done", result=result)
        except Exception as exc:  # noqa: BLE001 - granica niti
            traceback.print_exc()
            _finish(job_id, "failed", error=str(exc))

    threading.Thread(target=wrapper, name=f"job-{kind}", daemon=True).start()
    return snapshot(job_id)


def snapshot(job_id: str) -> Optional[dict]:
    with _lock:
        record = _jobs.get(job_id)
        return dict(record) if record else None


def listing(limit: int = 20) -> list[dict]:
    with _lock:
        return [dict(record) for record in list(_jobs.values())[-limit:]][::-1]


def cancel(job_id: str) -> bool:
    with _lock:
        record = _jobs.get(job_id)
        if not record or record["status"] != "running":
            return False
        record["cancel"] = True
        record["message"] = "Otkazivanje..."
        return True


def _finish(job_id: str, status: str, result: Any = None, error: str = "") -> None:
    with _lock:
        record = _jobs.get(job_id)
        if not record:
            return
        record["status"] = status
        record["result"] = result
        record["error"] = error
        if status == "done" and record["total"]:
            record["done"] = record["total"]


def _prune() -> None:
    if len(_jobs) <= _MAX_KEPT:
        return
    finished = [key for key, value in _jobs.items() if value["status"] != "running"]
    for key in finished[: len(_jobs) - _MAX_KEPT]:
        _jobs.pop(key, None)
