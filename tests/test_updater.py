"""Testovi samo-azuriranja.

Tezina je na jednoj stvari: azuriranje ne sme da dodirne `data/`. Sve ostalo je
neprijatnost koja se resava ponovnim preuzimanjem; izgubljena baza sa pitanjima
i napretkom je jedina steta koju korisnik ne moze da povrati.

Nijedan test ovde ne pusta `apply_tree` na pravi folder projekta: izvor i cilj
su uvek privremeni folderi, a `_assert_not_project` to proverava na zivoj
putanji, ne na konfiguraciji.
"""

import io
import shutil
import tempfile
import zipfile
from pathlib import Path

from app import config
from app.services import updater

from .base import PROJECT_ROOT, AppTestCase


def build_zip(entries: dict, root: str = "skripta-faks-main") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in entries.items():
            archive.writestr(f"{root}/{name}" if root else name, content)
    return buffer.getvalue()


class UpdaterTestCase(AppTestCase):
    """Osnova koja garantuje da nijedno pisanje ne ide u pravi projekat."""

    def setUp(self) -> None:
        super().setUp()
        self.work = Path(tempfile.mkdtemp(prefix="skripta-update-"))
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

        # `staging_dir()` racuna se iz config.BASE_DIR, koji pokazuje na pravi
        # projekat. Bez ovoga bi svaki test pisao .update/ u radni folder.
        self._real_base = config.BASE_DIR
        config.BASE_DIR = self.work / "instalacija"
        (config.BASE_DIR / "app").mkdir(parents=True)
        self.addCleanup(setattr, config, "BASE_DIR", self._real_base)

    def _assert_not_project(self, path: Path) -> None:
        if path.resolve() == PROJECT_ROOT:
            raise AssertionError("Test pokazuje na pravi folder projekta. Prekidam.")

    def write_archive(self, data: bytes) -> Path:
        path = self.work / "verzija.zip"
        path.write_bytes(data)
        return path


class VersionTest(AppTestCase):
    def test_parses_tag_with_prefix(self):
        self.assertEqual(updater.parse_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(updater.parse_version("0.1.0"), (0, 1, 0))

    def test_non_numeric_tag_is_not_newer(self):
        """'main' ili 'latest' ne smeju da se protumace kao nova verzija."""
        self.assertEqual(updater.parse_version("main"), ())
        self.assertFalse(updater.is_newer("main", "0.1.0"))

    def test_compares_numerically_not_as_text(self):
        # Kao tekst je '0.10.0' < '0.9.0'; numericki nije. To je jedini razlog
        # zasto parse_version uopste postoji.
        self.assertTrue(updater.is_newer("0.10.0", "0.9.0"))
        self.assertFalse(updater.is_newer("0.9.0", "0.10.0"))

    def test_same_version_is_not_newer(self):
        self.assertFalse(updater.is_newer("1.0.0", "1.0.0"))

    def test_shorter_tag_compares_by_leading_parts(self):
        self.assertTrue(updater.is_newer("2.0", "1.9.9"))


class ExtractTest(UpdaterTestCase):
    def test_rejects_archive_without_app(self):
        """Arhiva koja nije skripta-faks ne sme da prepise instalaciju."""
        archive = self.write_archive(build_zip({"README.md": "nesto drugo"}))
        with self.assertRaises(updater.UpdateError) as caught:
            updater.extract(archive)
        self.assertIn("ne lici na skripta-faks", str(caught.exception))

    def test_rejects_empty_archive(self):
        archive = self.write_archive(build_zip({}))
        with self.assertRaises(updater.UpdateError):
            updater.extract(archive)

    def test_rejects_corrupted_archive(self):
        archive = self.write_archive(b"ovo nije zip")
        with self.assertRaises(updater.UpdateError):
            updater.extract(archive)

    def test_strips_github_root_folder(self):
        archive = self.write_archive(build_zip({
            "run.py": "print('novo')",
            "app/__init__.py": "__version__ = '9.9.9'",
        }))
        folder = updater.extract(archive)
        self.assertTrue((folder / "run.py").is_file())
        self.assertEqual((folder / "run.py").read_text(encoding="utf-8"), "print('novo')")

    def test_skips_data_and_escape_paths(self):
        """Zip slip i tudji `data/`: ni jedno ni drugo ne sme da izadje iz ZIP-a.

        Uz svaku proveru odsustva stoji i provera prisustva istog raspakivanja -
        inace bi test prosao i kad `extract` ne bi raspakovao bas nista.
        """
        archive = self.write_archive(build_zip({
            "run.py": "print('novo')",
            "app/__init__.py": "x = 1",
            "data/skripta.db": "TUDJA BAZA",
            "../pobegao.txt": "van foldera",
        }))
        folder = updater.extract(archive)

        self.assertTrue((folder / "run.py").is_file(), "nista nije raspakovano")
        self.assertFalse((folder / "data").exists(), "data/ iz arhive je raspakovan")
        self.assertFalse((folder.parent / "pobegao.txt").exists(),
                         "putanja je pobegla iz foldera")


class ApplyTreeTest(UpdaterTestCase):
    """Ugradnja preko zive instalacije."""

    def setUp(self):
        super().setUp()
        self.source = self.work / "novo"
        self.installed = config.BASE_DIR
        self._assert_not_project(self.installed)
        (self.source / "app").mkdir(parents=True)
        (self.installed / "data").mkdir(parents=True)

    def test_never_touches_data(self):
        (self.installed / "data" / "skripta.db").write_text("MOJA PITANJA", encoding="utf-8")
        (self.source / "data").mkdir()
        (self.source / "data" / "skripta.db").write_text("PRAZNA BAZA", encoding="utf-8")
        (self.source / "run.py").write_text("novo", encoding="utf-8")

        updater.apply_tree(self.source, self.installed)

        self.assertEqual(
            (self.installed / "data" / "skripta.db").read_text(encoding="utf-8"),
            "MOJA PITANJA",
            "azuriranje je pregazilo korisnikovu bazu",
        )
        # Prisustvo uz odsustvo: dokazuje da je kopiranje uopste radilo.
        self.assertTrue((self.installed / "run.py").is_file(), "nista nije kopirano")

    def test_overwrites_code(self):
        (self.installed / "app" / "server.py").write_text("staro", encoding="utf-8")
        (self.source / "app" / "server.py").write_text("novo", encoding="utf-8")

        count = updater.apply_tree(self.source, self.installed)

        self.assertEqual((self.installed / "app" / "server.py").read_text(encoding="utf-8"), "novo")
        self.assertEqual(count, 1)

    def test_adds_new_files(self):
        (self.source / "app" / "novi_modul.py").write_text("x = 1", encoding="utf-8")
        updater.apply_tree(self.source, self.installed)
        self.assertTrue((self.installed / "app" / "novi_modul.py").is_file())


class PrepareTest(UpdaterTestCase):
    def test_marker_survives_and_discard_removes_it(self):
        folder = updater.extract(self.write_archive(build_zip({
            "run.py": "print('novo')",
            "app/__init__.py": "x = 1",
        })))
        (updater.staging_dir() / updater.MARKER_NAME).write_text(
            '{"version": "9.9.9", "folder": "%s"}' % folder.as_posix(), encoding="utf-8"
        )

        info = updater.pending_info()
        self.assertIsNotNone(info)
        self.assertEqual(info["version"], "9.9.9")

        updater.discard()
        self.assertIsNone(updater.pending_info())
        self.assertFalse(updater.staging_dir().exists())

    def test_broken_marker_reads_as_nothing_pending(self):
        updater.staging_dir().mkdir(parents=True, exist_ok=True)
        (updater.staging_dir() / updater.MARKER_NAME).write_text("{ ovo nije json",
                                                                encoding="utf-8")
        self.assertIsNone(updater.pending_info())


class CheckTest(UpdaterTestCase):
    def test_check_is_blocked_in_tests(self):
        """Suite ne sme da izlazi na GitHub API - isti prekidac kao za AI pozive."""
        state = updater.check()
        self.assertTrue(state["ok"])
        self.assertFalse(state["available"])
        self.assertIn("iskljucene", state["error"])

    def test_pending_is_none_without_staging(self):
        updater.discard()
        self.assertIsNone(updater.pending_info())

    def test_install_pending_without_staging_does_nothing(self):
        updater.discard()
        self.assertIsNone(updater.install_pending())
