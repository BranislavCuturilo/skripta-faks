"""Zdravlje aplikacije i jedan poziv koji browser radi na startu."""

from .. import __version__, db, netinfo
from ..http_util import Request, Response, json_response
from ..quiz import types as question_types
from ..router import router
from ..services import categories, settings_store


@router.get("/api/health")
def health(request: Request) -> Response:
    return json_response({"ok": True, "version": __version__})


@router.get("/api/bootstrap")
def bootstrap(request: Request) -> Response:
    """Sve sto ljuska treba da nacrta prvi ekran, u jednom zahtevu."""
    return json_response(
        {
            "ok": True,
            "version": __version__,
            "settings": settings_store.public_settings(),
            "tree": categories.tree(),
            "question_types": question_types.catalog(),
            "stats": _global_stats(),
            "network": netinfo.info(),
        }
    )


@router.get("/api/network")
def network(request: Request) -> Response:
    """Adrese pod kojima je app dostupan - za 'otvori na telefonu'.

    Racuna se na svaki poziv, a ne jednom na startu: Wi-Fi se menja, laptop
    prelazi sa kabla na bezicnu, VPN se pali i gasi.
    """
    return json_response({"ok": True, "network": netinfo.info()})


def _global_stats() -> dict:
    return {
        "categories": db.scalar("SELECT COUNT(*) FROM category", default=0),
        "materials": db.scalar("SELECT COUNT(*) FROM material", default=0),
        "questions": db.scalar(
            "SELECT COUNT(*) FROM question WHERE state = 'active'", default=0
        ),
        "attempts": db.scalar("SELECT COUNT(*) FROM attempt", default=0),
        "due_now": db.scalar(
            """
            SELECT COUNT(*) FROM question_schedule s
            JOIN question q ON q.id = s.question_id
            LEFT JOIN question_meta m ON m.question_id = q.id
            WHERE s.due_at <= datetime('now') AND q.state = 'active'
                  AND m.deleted_at IS NULL AND m.ignored_at IS NULL
            """,
            default=0,
        ),
    }
