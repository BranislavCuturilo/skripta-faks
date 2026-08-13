"""docx / xlsx / pptx bez ijedne biblioteke.

Sva tri formata su ZIP arhive sa XML-om unutra, pa `zipfile` + `xml.etree`
rade posao. Stari binarni .doc/.xls/.ppt nisu OOXML i ovde ne stizu.
"""

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from . import ExtractionResult, quality_of


def extract(path: Path) -> ExtractionResult:
    handlers = {".docx": _docx, ".xlsx": _xlsx, ".pptx": _pptx}
    handler = handlers.get(path.suffix.lower())
    if handler is None:
        return ExtractionResult(status="remote_needed", method="none", note="Nije OOXML format.")

    try:
        with zipfile.ZipFile(path) as archive:
            text, pages, note = handler(archive)
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as exc:
        return ExtractionResult(
            status="remote_needed",
            method="ooxml",
            note=f"Arhiva se ne cita ({exc.__class__.__name__}); original ide AI-u.",
        )

    text = _tidy(text)
    quality = quality_of(text)
    return ExtractionResult(
        status="local_ok" if len(text) > 40 else "remote_needed",
        method="ooxml",
        text=text,
        pages=pages,
        page_count=len(pages) or None,
        quality=quality,
        note=note,
    )


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _docx(archive: zipfile.ZipFile) -> tuple[str, list[str], str]:
    root = ElementTree.fromstring(archive.read("word/document.xml"))
    lines: list[str] = []
    _walk_docx(root, lines)
    text = "\n".join(lines)
    return text, [], f"pasusa: {len(lines)}"


def _walk_docx(node, lines: list[str]) -> None:
    tag = _local(node.tag)
    if tag == "p":
        lines.append(_docx_paragraph(node))
        return
    if tag == "tbl":
        for row in node.iter():
            if _local(row.tag) != "tr":
                continue
            cells = [
                " ".join(_docx_paragraph(paragraph) for paragraph in cell.iter() if _local(paragraph.tag) == "p").strip()
                for cell in row
                if _local(cell.tag) == "tc"
            ]
            if any(cells):
                lines.append(" | ".join(cells))
        return
    for child in node:
        _walk_docx(child, lines)


def _docx_paragraph(node) -> str:
    pieces: list[str] = []
    for element in node.iter():
        tag = _local(element.tag)
        if tag == "t" and element.text:
            pieces.append(element.text)
        elif tag == "tab":
            pieces.append("\t")
        elif tag == "br":
            pieces.append("\n")
    return "".join(pieces).strip()


def _xlsx(archive: zipfile.ZipFile) -> tuple[str, list[str], str]:
    shared: list[str] = []
    if "xl/sharedStrings.xml" in archive.namelist():
        root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
        for item in root:
            pieces = [
                element.text or ""
                for element in item.iter()
                if _local(element.tag) == "t"
            ]
            shared.append("".join(pieces))

    names = _sheet_names(archive)
    sheets: list[str] = []
    sheet_files = sorted(
        name for name in archive.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)
    )
    for index, name in enumerate(sheet_files):
        root = ElementTree.fromstring(archive.read(name))
        rows: list[str] = []
        for row in root.iter():
            if _local(row.tag) != "row":
                continue
            values: list[str] = []
            for cell in row:
                if _local(cell.tag) != "c":
                    continue
                values.append(_xlsx_cell(cell, shared))
            if any(value.strip() for value in values):
                rows.append(" | ".join(values).rstrip(" |"))
        title = names[index] if index < len(names) else f"List {index + 1}"
        sheets.append(f"### {title}\n" + "\n".join(rows))

    return "\n\n".join(sheets), sheets, f"listova: {len(sheets)}"


def _sheet_names(archive: zipfile.ZipFile) -> list[str]:
    if "xl/workbook.xml" not in archive.namelist():
        return []
    root = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    return [
        element.attrib.get("name", "")
        for element in root.iter()
        if _local(element.tag) == "sheet"
    ]


def _xlsx_cell(cell, shared: list[str]) -> str:
    cell_type = cell.attrib.get("t", "")
    if cell_type == "inlineStr":
        return "".join(
            element.text or "" for element in cell.iter() if _local(element.tag) == "t"
        )
    value = ""
    for element in cell:
        if _local(element.tag) == "v":
            value = element.text or ""
            break
    if cell_type == "s":
        try:
            return shared[int(value)]
        except (ValueError, IndexError):
            return ""
    return value


def _pptx(archive: zipfile.ZipFile) -> tuple[str, list[str], str]:
    slide_files = sorted(
        (name for name in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)),
        key=lambda name: int(re.search(r"(\d+)", name).group(1)),
    )
    slides: list[str] = []
    for index, name in enumerate(slide_files, start=1):
        root = ElementTree.fromstring(archive.read(name))
        pieces = [
            element.text
            for element in root.iter()
            if _local(element.tag) == "t" and element.text
        ]
        slides.append(f"### Slajd {index}\n" + "\n".join(pieces))
    return "\n\n".join(slides), slides, f"slajdova: {len(slides)}"


def _tidy(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
