"""Ekstrakcija: tekst, OOXML, PDF, deljenje na komade.

Fixtures su pravi fajlovi tih formata, sastavljeni ovde - ne izmisljen oblik
koji odgovara parseru. Ako parser sutra pogresno pretpostavi strukturu, ovi
testovi padnu.
"""

import zipfile
import zlib
from pathlib import Path

from app import extract
from app.extract import chunking

from .base import AppTestCase


def _write_docx(path: Path, paragraphs: list[str]) -> None:
    body = "".join(
        f'<w:p><w:r><w:t>{text}</w:t></w:r></w:p>' for text in paragraphs
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/></Types>',
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="word/document.xml" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"/>'
            "</Relationships>",
        )
        archive.writestr("word/document.xml", document)


def _write_pdf(path: Path, text: str, compress: bool = True) -> None:
    content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("cp1252")
    stream = zlib.compress(content) if compress else content
    filter_entry = b"/Filter /FlateDecode " if compress else b""

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< " + filter_entry + f"/Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    for number, body in enumerate(objects, start=1):
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    out += b"trailer << /Root 1 0 R /Size 6 >>\n%%EOF\n"
    path.write_bytes(bytes(out))


class PlainTextTests(AppTestCase):
    def test_utf8_is_read(self):
        path = Path(self._temp_dir) / "a.txt"
        path.write_text("Čvrsto rešenje\nDruga linija", "utf-8")
        result = extract.extract(path)
        self.assertEqual(result.status, "local_ok")
        self.assertIn("Čvrsto rešenje", result.text)

    def test_cp1250_is_detected(self):
        path = Path(self._temp_dir) / "b.txt"
        path.write_bytes("Čvrsto rešenje".encode("cp1250"))
        result = extract.extract(path)
        self.assertIn("rešenje", result.text)

    def test_subtitle_timing_is_stripped(self):
        path = Path(self._temp_dir) / "c.srt"
        path.write_text(
            "1\n00:00:01,000 --> 00:00:04,000\nPrva recenica predavanja.\n\n"
            "2\n00:00:04,000 --> 00:00:07,000\nDruga recenica.\n",
            "utf-8",
        )
        result = extract.extract(path)
        self.assertIn("Prva recenica predavanja.", result.text)
        self.assertNotIn("-->", result.text)
        self.assertNotIn("00:00:01", result.text)


class OoxmlTests(AppTestCase):
    def test_docx_paragraphs_are_extracted(self):
        path = Path(self._temp_dir) / "skripta.docx"
        _write_docx(path, ["Definicija integrala", "Integral je granicna vrednost sume."])
        result = extract.extract(path)
        self.assertEqual(result.status, "local_ok")
        self.assertEqual(result.method, "ooxml")
        self.assertIn("Definicija integrala", result.text)
        self.assertIn("granicna vrednost", result.text)

    def test_broken_archive_falls_back_to_remote(self):
        path = Path(self._temp_dir) / "pokvaren.docx"
        path.write_bytes(b"ovo nije zip")
        result = extract.extract(path)
        self.assertEqual(result.status, "remote_needed")
        self.assertIn("ne cita", result.note)


class PdfTests(AppTestCase):
    def test_compressed_text_stream_is_read(self):
        path = Path(self._temp_dir) / "skripta.pdf"
        _write_pdf(path, "Lekcija 1 Uvod u verovatnocu i statistiku")
        result = extract.extract(path)
        self.assertEqual(result.method, "pdf_text")
        self.assertIn("Lekcija 1", result.text)
        self.assertIn("verovatnocu", result.text)
        self.assertEqual(result.page_count, 1)

    def test_uncompressed_text_stream_is_read(self):
        path = Path(self._temp_dir) / "plain.pdf"
        _write_pdf(path, "Sadrzaj bez kompresije u jednom redu", compress=False)
        result = extract.extract(path)
        self.assertIn("bez kompresije", result.text)

    def test_pdf_without_text_layer_goes_remote(self):
        """Skeniran PDF nema tekst - to je bas slucaj koji ide Gemini-ju."""
        path = Path(self._temp_dir) / "sken.pdf"
        path.write_bytes(
            b"%PDF-1.4\n1 0 obj\n<< /Type /Page >>\nendobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"
        )
        result = extract.extract(path)
        self.assertEqual(result.status, "remote_needed")
        self.assertEqual(result.text, "")

    def test_not_a_pdf_goes_remote(self):
        path = Path(self._temp_dir) / "lazni.pdf"
        path.write_bytes(b"ovo nije pdf")
        result = extract.extract(path)
        self.assertEqual(result.status, "remote_needed")


class KindTests(AppTestCase):
    def test_media_is_routed_to_remote(self):
        for name in ("slika.png", "snimak.mp3", "predavanje.mp4"):
            path = Path(self._temp_dir) / name
            path.write_bytes(b"\x00\x01\x02")
            result = extract.extract(path)
            self.assertEqual(result.status, "remote_needed", name)
            self.assertEqual(result.text, "", name)

    def test_kind_mapping(self):
        self.assertEqual(extract.kind_for(".pdf"), "pdf")
        self.assertEqual(extract.kind_for(".jpg"), "image")
        self.assertEqual(extract.kind_for(".m4a"), "audio")
        self.assertEqual(extract.kind_for(".docx"), "document")
        self.assertEqual(extract.kind_for(".zip"), "other")


class QualityTests(AppTestCase):
    def test_real_sentences_score_high(self):
        text = (
            "Integral funkcije predstavlja granicnu vrednost sume proizvoda. "
            "Osnovna teorema povezuje izvod i integral u jednu celinu."
        )
        self.assertGreater(extract.quality_of(text), extract.MIN_QUALITY)

    def test_glyph_soup_scores_low(self):
        # Ovako izgleda CID font bez ToUnicode mape: nizovi bez razmaka.
        self.assertLess(extract.quality_of("\x03\x05\x07\x02\x04" * 200), extract.MIN_QUALITY)

    def test_empty_text_scores_zero(self):
        self.assertEqual(extract.quality_of(""), 0.0)


class ChunkingTests(AppTestCase):
    def test_short_text_is_one_chunk(self):
        chunks = chunking.split("Kratak tekst.\n\nDrugi pasus.", budget=60000)
        self.assertEqual(len(chunks), 1)
        self.assertIn("Drugi pasus.", chunks[0]["text"])

    def test_long_text_is_split_within_budget(self):
        paragraph = "Recenica koja se ponavlja da bi tekst bio dugacak. " * 20
        text = "\n\n".join([paragraph] * 30)
        chunks = chunking.split(text, budget=4000, overlap=0)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(chunk["char_count"], 4600, "komad je znatno preko budzeta")

    def test_headings_become_labels(self):
        text = "Lekcija 1\n\nUvodni pojmovi i definicije.\n\nLekcija 2\n\nDrugi deo gradiva."
        chunks = chunking.split(text, budget=40)
        labels = [chunk["label"] for chunk in chunks]
        self.assertTrue(any("Lekcija" in label for label in labels), labels)

    def test_outline_lists_headings_once(self):
        text = "Lekcija 1\n\ntekst\n\nLekcija 2\n\ntekst\n\nLekcija 1\n\ntekst"
        found = chunking.outline(text)
        self.assertEqual(found.count("Lekcija 1"), 1)
        self.assertIn("Lekcija 2", found)

    def test_empty_text_gives_no_chunks(self):
        self.assertEqual(chunking.split("   "), [])
