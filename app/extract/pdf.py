"""Citanje teksta iz PDF-a samo standardnom bibliotekom.

Pokriva ono sto pokriva vecinu skripti i knjiga: FlateDecode streamove, object
streamove (PDF 1.5+), stablo strana i ToUnicode CMap mape preko kojih se kodovi
glifova vracaju u citljiva slova - bez toga cirilica i nasi znaci izadju kao
smece.

Ono sto NE pokriva je skenirani PDF (slika bez teksta) i egzoticne filtere.
Tada `extract` vrati remote_needed i original ide u Gemini, koji PDF cita
nativno. To je bas ona hibridna podela koja je dogovorena.
"""

import re
import zlib
from pathlib import Path

from . import MIN_QUALITY, ExtractionResult, quality_of

_OBJ_START = re.compile(rb"(?<![0-9])(\d+)\s+(\d+)\s+obj\b")
_HEX_TOKEN = re.compile(rb"<([0-9A-Fa-f\s]*)>")
_NAME_TOKEN = re.compile(rb"/([#\w.\-+]+)")


def extract(path: Path) -> ExtractionResult:
    try:
        data = path.read_bytes()
    except OSError as exc:
        return ExtractionResult(status="failed", method="pdf_text", note=str(exc))

    if not data.startswith(b"%PDF"):
        return ExtractionResult(
            status="remote_needed", method="pdf_text", note="Fajl ne pocinje sa %PDF."
        )

    try:
        document = _Document(data)
        pages = document.page_texts()
    except Exception as exc:  # noqa: BLE001 - polomljen PDF ne sme da obori upload
        return ExtractionResult(
            status="remote_needed",
            method="pdf_text",
            note=f"Lokalno citanje nije uspelo ({exc.__class__.__name__}); original ide AI-u.",
        )

    page_count = len(pages) or document.page_count_hint
    text = "\n\n".join(
        f"[strana {index}]\n{content}" for index, content in enumerate(pages, start=1) if content.strip()
    )
    quality = quality_of(text, page_count)

    if not text.strip():
        return ExtractionResult(
            status="remote_needed",
            method="pdf_text",
            page_count=page_count,
            quality=0.0,
            note="Nema tekstualnog sloja - verovatno skeniran dokument.",
        )

    status = "local_ok" if quality >= MIN_QUALITY else "remote_needed"
    note = (
        f"strana: {page_count}, kvalitet teksta: {quality:.2f}"
        if status == "local_ok"
        else f"Izvuceni tekst je loseg kvaliteta ({quality:.2f}); original ide AI-u."
    )
    return ExtractionResult(
        status=status,
        method="pdf_text",
        text=text,
        pages=pages,
        page_count=page_count,
        quality=quality,
        note=note,
    )


# --------------------------------------------------------------------------


class _Document:
    def __init__(self, data: bytes):
        self.data = data
        self.bodies: dict[int, bytes] = {}
        self.streams: dict[int, bytes] = {}
        self.page_count_hint = 0
        self._cmap_cache: dict[int, "_CMap"] = {}
        self._scan_objects()
        self._expand_object_streams()

    # ---------------------------------------------------------------- objects

    def _scan_objects(self) -> None:
        for found in _OBJ_START.finditer(self.data):
            number = int(found.group(1))
            start = found.end()
            end = self.data.find(b"endobj", start)
            if end < 0:
                end = min(start + 200_000, len(self.data))
            body = self.data[start:end]

            stream_at = body.find(b"stream")
            if stream_at >= 0:
                dictionary = body[:stream_at]
                cursor = stream_at + len(b"stream")
                if self.data[start + cursor : start + cursor + 2] == b"\r\n":
                    cursor += 2
                elif body[cursor : cursor + 1] in (b"\n", b"\r"):
                    cursor += 1
                stream_end = body.find(b"endstream", cursor)
                raw = body[cursor:stream_end] if stream_end >= 0 else body[cursor:]
                self.bodies[number] = dictionary
                decoded = _decode_stream(dictionary, raw)
                if decoded is not None:
                    self.streams[number] = decoded
            else:
                self.bodies[number] = body

    def _expand_object_streams(self) -> None:
        """PDF 1.5+ pakuje recnike u /ObjStm; bez raspakivanja nema fontova."""
        for number, body in list(self.bodies.items()):
            if b"/ObjStm" not in body:
                continue
            payload = self.streams.get(number)
            if not payload:
                continue
            count = _int_value(body, b"/N") or 0
            first = _int_value(body, b"/First") or 0
            header = payload[:first].split()
            try:
                pairs = [
                    (int(header[index]), int(header[index + 1]))
                    for index in range(0, min(len(header), count * 2), 2)
                ]
            except (ValueError, IndexError):
                continue
            for position, (object_number, offset) in enumerate(pairs):
                start = first + offset
                end = first + pairs[position + 1][1] if position + 1 < len(pairs) else len(payload)
                if object_number not in self.bodies:
                    self.bodies[object_number] = payload[start:end]

    def resolve(self, value: bytes) -> bytes:
        """Prati `N 0 R` referencu do tela objekta."""
        reference = re.match(rb"\s*(\d+)\s+\d+\s+R\b", value)
        if reference:
            return self.bodies.get(int(reference.group(1)), b"")
        return value

    # ------------------------------------------------------------------ pages

    def page_objects(self) -> list[int]:
        pages = [
            number
            for number, body in self.bodies.items()
            if re.search(rb"/Type\s*/Page\b(?!s)", body)
        ]
        self.page_count_hint = len(pages)
        ordered = self._ordered_from_tree()
        if ordered:
            known = set(pages)
            merged = [number for number in ordered if number in known]
            merged.extend(number for number in pages if number not in set(ordered))
            return merged
        return sorted(pages)

    def _ordered_from_tree(self) -> list[int]:
        """Redosled strana iz /Pages /Kids; bez toga strane idu po broju objekta."""
        root = None
        for number, body in self.bodies.items():
            if re.search(rb"/Type\s*/Pages\b", body) and b"/Parent" not in body:
                root = number
                break
        if root is None:
            return []

        order: list[int] = []
        seen: set[int] = set()
        queue = [root]
        while queue:
            current = queue.pop(0)
            if current in seen:
                continue
            seen.add(current)
            body = self.bodies.get(current, b"")
            if re.search(rb"/Type\s*/Page\b(?!s)", body):
                order.append(current)
                continue
            kids = re.search(rb"/Kids\s*\[(.*?)\]", body, re.S)
            if not kids:
                continue
            children = [int(item) for item in re.findall(rb"(\d+)\s+\d+\s+R", kids.group(1))]
            queue = children + queue
        return order

    def page_texts(self) -> list[str]:
        result: list[str] = []
        for number in self.page_objects():
            body = self.bodies.get(number, b"")
            content = self._page_content(body)
            if not content:
                result.append("")
                continue
            fonts = self._page_fonts(body)
            result.append(_render(content, fonts))
        return result

    def _page_content(self, body: bytes) -> bytes:
        found = re.search(rb"/Contents\s*(\[[^\]]*\]|\d+\s+\d+\s+R)", body)
        if not found:
            return b""
        token = found.group(1)
        numbers = [int(item) for item in re.findall(rb"(\d+)\s+\d+\s+R", token)]
        return b"\n".join(self.streams.get(number, b"") for number in numbers)

    def _page_fonts(self, body: bytes) -> dict[str, "_CMap"]:
        resources = re.search(rb"/Resources\s*(<<.*?>>|\d+\s+\d+\s+R)", body, re.S)
        if not resources:
            return {}
        block = self.resolve(resources.group(1))
        fonts_at = block.find(b"/Font")
        if fonts_at < 0:
            return {}
        segment = self.resolve(block[fonts_at + len(b"/Font") :])
        window = segment[: segment.find(b">>") + 2] if b">>" in segment[:4000] else segment[:4000]

        mapping: dict[str, _CMap] = {}
        for name, number in re.findall(rb"/([#\w.\-+]+)\s+(\d+)\s+\d+\s+R", window):
            cmap = self._font_cmap(int(number))
            if cmap is not None:
                mapping[name.decode("latin-1")] = cmap
        return mapping

    def _font_cmap(self, font_number: int) -> "_CMap | None":
        if font_number in self._cmap_cache:
            return self._cmap_cache[font_number]
        body = self.bodies.get(font_number, b"")
        found = re.search(rb"/ToUnicode\s+(\d+)\s+\d+\s+R", body)
        cmap = None
        if found:
            payload = self.streams.get(int(found.group(1)))
            if payload:
                cmap = _CMap.parse(payload)
        if cmap is None:
            cmap = _CMap.identity(two_byte=b"/Type0" in body)
        self._cmap_cache[font_number] = cmap
        return cmap


# --------------------------------------------------------------------------


class _CMap:
    def __init__(self, mapping: dict[int, str], code_bytes: int):
        self.mapping = mapping
        self.code_bytes = code_bytes

    @classmethod
    def identity(cls, two_byte: bool = False) -> "_CMap":
        return cls({}, 2 if two_byte else 1)

    @classmethod
    def parse(cls, payload: bytes) -> "_CMap | None":
        mapping: dict[int, str] = {}
        code_bytes = 1

        for block in re.findall(rb"beginbfchar(.*?)endbfchar", payload, re.S):
            tokens = _HEX_TOKEN.findall(block)
            for index in range(0, len(tokens) - 1, 2):
                source = _clean_hex(tokens[index])
                target = _clean_hex(tokens[index + 1])
                if not source:
                    continue
                code_bytes = max(code_bytes, len(source) // 2)
                mapping[int(source, 16)] = _hex_to_text(target)

        for block in re.findall(rb"beginbfrange(.*?)endbfrange", payload, re.S):
            _parse_bfrange(block, mapping)
            for token in _HEX_TOKEN.findall(block)[:1]:
                cleaned = _clean_hex(token)
                if cleaned:
                    code_bytes = max(code_bytes, len(cleaned) // 2)

        for block in re.findall(rb"begincodespacerange(.*?)endcodespacerange", payload, re.S):
            for token in _HEX_TOKEN.findall(block):
                cleaned = _clean_hex(token)
                if cleaned:
                    code_bytes = max(code_bytes, len(cleaned) // 2)

        if not mapping:
            return None
        return cls(mapping, min(code_bytes, 2))

    def decode(self, raw: bytes) -> str:
        if not self.mapping:
            if self.code_bytes == 2:
                return "".join(
                    chr(int.from_bytes(raw[index : index + 2], "big"))
                    for index in range(0, len(raw) - 1, 2)
                )
            return raw.decode("cp1252", "replace")

        pieces: list[str] = []
        step = self.code_bytes
        for index in range(0, len(raw), step):
            chunk = raw[index : index + step]
            if not chunk:
                break
            code = int.from_bytes(chunk, "big")
            pieces.append(self.mapping.get(code, ""))
        return "".join(pieces)


def _parse_bfrange(block: bytes, mapping: dict[int, str]) -> None:
    cursor = 0
    while cursor < len(block):
        first = _HEX_TOKEN.search(block, cursor)
        if not first:
            return
        second = _HEX_TOKEN.search(block, first.end())
        if not second:
            return

        low = _clean_hex(first.group(1))
        high = _clean_hex(second.group(1))
        if not low or not high:
            return
        low_value, high_value = int(low, 16), int(high, 16)
        if high_value < low_value or high_value - low_value > 65535:
            cursor = second.end()
            continue

        after = block[second.end() :].lstrip()
        if after.startswith(b"["):
            end_at = block.find(b"]", second.end())
            if end_at < 0:
                return
            targets = _HEX_TOKEN.findall(block[second.end() : end_at])
            for offset, target in enumerate(targets):
                mapping[low_value + offset] = _hex_to_text(_clean_hex(target))
            cursor = end_at + 1
        else:
            third = _HEX_TOKEN.search(block, second.end())
            if not third:
                return
            base = _clean_hex(third.group(1))
            if base:
                base_value = int(base, 16)
                for offset in range(high_value - low_value + 1):
                    mapping[low_value + offset] = _hex_to_text(f"{base_value + offset:04X}")
            cursor = third.end()


def _clean_hex(token) -> str:
    if isinstance(token, bytes):
        token = token.decode("latin-1")
    token = re.sub(r"\s+", "", token)
    return token if len(token) % 2 == 0 else token + "0"


def _hex_to_text(value: str) -> str:
    if not value:
        return ""
    pieces = []
    for index in range(0, len(value) - 3, 4):
        try:
            pieces.append(chr(int(value[index : index + 4], 16)))
        except ValueError:
            continue
    if not pieces and len(value) >= 2:
        try:
            pieces.append(chr(int(value[:2], 16)))
        except ValueError:
            return ""
    return "".join(pieces)


# --------------------------------------------------------------------------


def _render(content: bytes, fonts: dict[str, _CMap]) -> str:
    """Prodji kroz operatore ispisa teksta i sastavi strane u redove."""
    output: list[str] = []
    current: _CMap | None = None
    cursor = 0
    length = len(content)

    while cursor < length:
        char = content[cursor : cursor + 1]

        if char == b"(":
            literal, cursor = _read_literal(content, cursor)
            operator, next_cursor = _peek_operator(content, cursor)
            if operator in (b"Tj", b"'", b'"'):
                if operator in (b"'", b'"'):
                    output.append("\n")
                output.append(_decode(literal, current))
                cursor = next_cursor
            continue

        if char == b"<" and content[cursor : cursor + 2] != b"<<":
            end_at = content.find(b">", cursor)
            if end_at < 0:
                break
            raw = bytes.fromhex(_clean_hex(content[cursor + 1 : end_at].decode("latin-1")) or "00")
            operator, next_cursor = _peek_operator(content, end_at + 1)
            if operator in (b"Tj", b"'", b'"'):
                output.append(_decode(raw, current))
                cursor = next_cursor
                continue
            cursor = end_at + 1
            continue

        if char == b"[":
            end_at = _match_array(content, cursor)
            operator, next_cursor = _peek_operator(content, end_at)
            if operator == b"TJ":
                output.append(_decode_array(content[cursor + 1 : end_at - 1], current))
                cursor = next_cursor
                continue
            cursor = end_at
            continue

        if char == b"/":
            found = _NAME_TOKEN.match(content, cursor)
            if found:
                operator, next_cursor = _peek_operator(content, found.end(), skip_numbers=True)
                if operator == b"Tf":
                    current = fonts.get(found.group(1).decode("latin-1"))
                    cursor = next_cursor
                    continue
                cursor = found.end()
                continue

        if content[cursor : cursor + 2] in (b"Td", b"TD", b"T*"):
            output.append("\n")
            cursor += 2
            continue
        if content[cursor : cursor + 2] == b"ET":
            output.append("\n")
            cursor += 2
            continue

        cursor += 1

    return _tidy("".join(output))


def _decode(raw: bytes, cmap: _CMap | None) -> str:
    if cmap is None:
        return raw.decode("cp1252", "replace")
    return cmap.decode(raw)


def _decode_array(block: bytes, cmap: _CMap | None) -> str:
    """TJ niz meša stringove i pomeraje; veliki negativan pomeraj je razmak."""
    pieces: list[str] = []
    cursor = 0
    while cursor < len(block):
        char = block[cursor : cursor + 1]
        if char == b"(":
            literal, cursor = _read_literal(block, cursor)
            pieces.append(_decode(literal, cmap))
            continue
        if char == b"<":
            end_at = block.find(b">", cursor)
            if end_at < 0:
                break
            hex_text = _clean_hex(block[cursor + 1 : end_at].decode("latin-1"))
            pieces.append(_decode(bytes.fromhex(hex_text or "00"), cmap))
            cursor = end_at + 1
            continue
        number = re.match(rb"\s*(-?\d+(?:\.\d+)?)", block[cursor:])
        if number:
            if float(number.group(1)) <= -180:
                pieces.append(" ")
            cursor += number.end()
            continue
        cursor += 1
    return "".join(pieces)


def _read_literal(data: bytes, start: int) -> tuple[bytes, int]:
    cursor = start + 1
    depth = 1
    out = bytearray()
    escapes = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f"}
    while cursor < len(data):
        char = data[cursor : cursor + 1]
        if char == b"\\":
            nxt = data[cursor + 1 : cursor + 2]
            if nxt in escapes:
                out += escapes[nxt]
                cursor += 2
                continue
            octal = re.match(rb"[0-7]{1,3}", data[cursor + 1 : cursor + 4])
            if octal:
                out.append(int(octal.group(0), 8) & 0xFF)
                cursor += 1 + octal.end()
                continue
            if nxt == b"\n":
                cursor += 2
                continue
            out += nxt
            cursor += 2
            continue
        if char == b"(":
            depth += 1
        elif char == b")":
            depth -= 1
            if depth == 0:
                return bytes(out), cursor + 1
        out += char
        cursor += 1
    return bytes(out), cursor


def _match_array(data: bytes, start: int) -> int:
    cursor = start + 1
    while cursor < len(data):
        char = data[cursor : cursor + 1]
        if char == b"(":
            _, cursor = _read_literal(data, cursor)
            continue
        if char == b"]":
            return cursor + 1
        cursor += 1
    return cursor


def _peek_operator(data: bytes, start: int, skip_numbers: bool = False) -> tuple[bytes, int]:
    cursor = start
    while cursor < len(data) and data[cursor : cursor + 1] in b" \t\r\n":
        cursor += 1
    if skip_numbers:
        number = re.match(rb"-?\d+(?:\.\d+)?\s*", data[cursor:])
        if number:
            cursor += number.end()
    found = re.match(rb"(T[jJfdD*Lc]|'|\"|ET|BT)", data[cursor:])
    if not found:
        return b"", start
    return found.group(1), cursor + found.end()


def _tidy(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# --------------------------------------------------------------------------


def _decode_stream(dictionary: bytes, raw: bytes) -> bytes | None:
    if b"/FlateDecode" not in dictionary:
        # Nekomprimovan content stream je redak ali validan.
        return raw if b"/Filter" not in dictionary else None
    try:
        data = zlib.decompress(raw)
    except zlib.error:
        try:
            data = zlib.decompressobj().decompress(raw)
        except zlib.error:
            return None
    predictor = _int_value(dictionary, b"/Predictor") or 1
    if predictor >= 10:
        columns = _int_value(dictionary, b"/Columns") or 1
        colors = _int_value(dictionary, b"/Colors") or 1
        bits = _int_value(dictionary, b"/BitsPerComponent") or 8
        data = _undo_png_predictor(data, columns, colors, bits)
    return data


def _undo_png_predictor(data: bytes, columns: int, colors: int, bits: int) -> bytes:
    sample = max(1, (colors * bits + 7) // 8)
    row_length = (columns * colors * bits + 7) // 8
    out = bytearray()
    previous = bytearray(row_length)
    cursor = 0
    while cursor + 1 + row_length <= len(data):
        tag = data[cursor]
        row = bytearray(data[cursor + 1 : cursor + 1 + row_length])
        cursor += 1 + row_length

        if tag == 1:
            for index in range(sample, row_length):
                row[index] = (row[index] + row[index - sample]) & 0xFF
        elif tag == 2:
            for index in range(row_length):
                row[index] = (row[index] + previous[index]) & 0xFF
        elif tag == 3:
            for index in range(row_length):
                left = row[index - sample] if index >= sample else 0
                row[index] = (row[index] + ((left + previous[index]) >> 1)) & 0xFF
        elif tag == 4:
            for index in range(row_length):
                left = row[index - sample] if index >= sample else 0
                up = previous[index]
                upper_left = previous[index - sample] if index >= sample else 0
                estimate = left + up - upper_left
                distance_left = abs(estimate - left)
                distance_up = abs(estimate - up)
                distance_diagonal = abs(estimate - upper_left)
                if distance_left <= distance_up and distance_left <= distance_diagonal:
                    nearest = left
                elif distance_up <= distance_diagonal:
                    nearest = up
                else:
                    nearest = upper_left
                row[index] = (row[index] + nearest) & 0xFF

        out += row
        previous = row
    return bytes(out)


def _int_value(dictionary: bytes, key: bytes) -> int | None:
    found = re.search(re.escape(key) + rb"\s+(\d+)", dictionary)
    return int(found.group(1)) if found else None
