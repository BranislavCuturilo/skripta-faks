"""Minimalni ruter: sablon putanje -> funkcija.

Sablon nosi konvertore: /api/categories/<int:category_id>/materials
Podrzani su int, str (bez kose crte) i path (sa kosim crtama).
"""

import re
from typing import Callable, Optional

from .http_util import HttpError, Request, Response

Handler = Callable[[Request], Response]

_CONVERTERS = {
    "int": (r"[0-9]+", int),
    "str": (r"[^/]+", str),
    "path": (r".+", str),
}

_PLACEHOLDER = re.compile(r"<(int|str|path):([a-zA-Z_][a-zA-Z0-9_]*)>")


class Route:
    def __init__(self, method: str, pattern: str, handler: Handler, name: str):
        self.method = method.upper()
        self.pattern = pattern
        self.handler = handler
        self.name = name
        self.regex, self.casters = _compile(pattern)

    def match(self, path: str) -> Optional[dict]:
        found = self.regex.match(path)
        if not found:
            return None
        return {key: self.casters[key](value) for key, value in found.groupdict().items()}


def _compile(pattern: str) -> tuple[re.Pattern, dict]:
    casters: dict = {}
    cursor = 0
    parts: list[str] = []
    for found in _PLACEHOLDER.finditer(pattern):
        parts.append(re.escape(pattern[cursor : found.start()]))
        kind, name = found.group(1), found.group(2)
        expression, caster = _CONVERTERS[kind]
        parts.append(f"(?P<{name}>{expression})")
        casters[name] = caster
        cursor = found.end()
    parts.append(re.escape(pattern[cursor:]))
    return re.compile("^" + "".join(parts) + "$"), casters


class Router:
    def __init__(self) -> None:
        self._routes: list[Route] = []

    def add(self, method: str, pattern: str, handler: Handler, name: str = "") -> None:
        self._routes.append(Route(method, pattern, handler, name or handler.__name__))

    def route(self, method: str, pattern: str, name: str = ""):
        def decorator(handler: Handler) -> Handler:
            self.add(method, pattern, handler, name)
            return handler

        return decorator

    def get(self, pattern: str, name: str = ""):
        return self.route("GET", pattern, name)

    def post(self, pattern: str, name: str = ""):
        return self.route("POST", pattern, name)

    def put(self, pattern: str, name: str = ""):
        return self.route("PUT", pattern, name)

    def patch(self, pattern: str, name: str = ""):
        return self.route("PATCH", pattern, name)

    def delete(self, pattern: str, name: str = ""):
        return self.route("DELETE", pattern, name)

    def include(self, other: "Router") -> None:
        self._routes.extend(other._routes)

    def resolve(self, method: str, path: str) -> tuple[Handler, dict]:
        allowed: set[str] = set()
        for candidate in self._routes:
            params = candidate.match(path)
            if params is None:
                continue
            if candidate.method != method.upper():
                allowed.add(candidate.method)
                continue
            return candidate.handler, params
        if allowed:
            raise HttpError(405, f"Metoda {method} nije dozvoljena za {path}.", sorted(allowed))
        raise HttpError(404, f"Ruta ne postoji: {path}")

    def __len__(self) -> int:
        return len(self._routes)


router = Router()
