"""Testovi samo-azuriranja.

Tezina je na jednoj stvari: azuriranje ne sme da dodirne `data/`. Sve ostalo je
neprijatnost koja se resava ponovnim preuzimanjem; izgubljena baza sa pitanjima
i napretkom je jedina steta koju korisnik ne moze da povrati.

Nijedan test ovde ne pusta `apply_tree` na pravi folder projekta: izvor i cilj
su uvek privremeni folderi, a `_assert_not_project` to proverava na zivoj
putanji, ne na konfiguraciji.
"""

import io
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from unittest import mock

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


OLD = "a" * 40
NEW = "b" * 40


def commit(sha, message="fix: nesto", date="2026-10-21T10:00:00Z"):
    return {"sha": sha, "commit": {"message": message, "committer": {"date": date}}}


class InstalledCommitTest(UpdaterTestCase):
    def test_git_copy_is_read_from_the_ref_file(self):
        git = config.BASE_DIR / ".git"
        (git / "refs" / "heads").mkdir(parents=True)
        (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        (git / "refs" / "heads" / "main").write_text(OLD + "\n", encoding="utf-8")
        self.assertEqual(updater.installed_commit(), OLD)

    def test_git_copy_with_packed_refs(self):
        """Posle `git gc` ref stoji samo u packed-refs."""
        git = config.BASE_DIR / ".git"
        git.mkdir()
        (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        (git / "packed-refs").write_text(f"# pack-refs\n{NEW} refs/heads/main\n", encoding="utf-8")
        self.assertEqual(updater.installed_commit(), NEW)

    def test_zip_install_is_read_from_verzija_json(self):
        (config.BASE_DIR / updater.INSTALLED_NAME).write_text(f'{{"sha": "{OLD}"}}', encoding="utf-8")
        self.assertEqual(updater.installed_commit(), OLD)

    def test_unknown_install_reads_as_empty(self):
        self.assertEqual(updater.installed_commit(), "")


class CheckAgainstMainTest(UpdaterTestCase):
    """Prvi updater je pitao `releases/latest`; release se nikad ne pravi, pa je
    odgovor uvek bio 404 i "imas najnoviju". Izvor istine je commit na main-u."""

    def check(self, installed, responses):
        if installed:
            (config.BASE_DIR / updater.INSTALLED_NAME).write_text(
                f'{{"sha": "{installed}"}}', encoding="utf-8")
        with mock.patch.object(updater, "_network_blocked", return_value=False), \
                mock.patch.object(updater, "_github_json", side_effect=responses) as fetch:
            state = updater.check()
        return state, fetch

    def test_newer_commit_on_main_is_offered(self):
        compare = {"status": "ahead", "html_url": "https://github.com/x/compare",
                   "commits": [commit(OLD[:39] + "1", "feat: prvo"), commit(NEW, "fix: drugo")]}
        state, _ = self.check(OLD, [commit(NEW, "fix: drugo"), compare])

        self.assertTrue(state["available"])
        self.assertEqual(state["latest_sha"], NEW)
        self.assertEqual(state["latest"], "bbbbbbb od 21.10.2026.")
        self.assertEqual(state["notes"], "- fix: drugo\n- feat: prvo", "najnovije prvo")

    def test_same_commit_is_up_to_date_without_a_second_request(self):
        state, fetch = self.check(NEW, [commit(NEW)])
        self.assertFalse(state["available"])
        self.assertEqual(fetch.call_count, 1)

    def test_copy_ahead_of_main_is_not_offered_anything(self):
        """Racunar na kome se programira ima commit-e koje GitHub jos nema."""
        state, _ = self.check(OLD, [commit(NEW), {"status": "behind", "commits": []}])
        self.assertFalse(state["available"])

    def test_commit_github_does_not_know_is_not_offered_anything(self):
        state, _ = self.check(OLD, [commit(NEW), None])
        self.assertFalse(state["available"])
        self.assertEqual(state["error"], "")

    def test_unknown_install_is_offered_the_newest(self):
        state, _ = self.check("", [commit(NEW)])
        self.assertTrue(state["available"])

    def test_github_failure_is_shown_not_thrown(self):
        state, _ = self.check(OLD, updater.UpdateError("Nema veze sa internetom."))
        self.assertFalse(state["available"])
        self.assertIn("Nema veze", state["error"])


class PrepareModesTest(UpdaterTestCase):
    def test_git_copy_is_not_downloaded_only_marked(self):
        with mock.patch.object(updater, "install_kind", return_value="git"), \
                mock.patch.object(updater, "download", side_effect=AssertionError("ne skida se")):
            info = updater.prepare(NEW, updater.ZIP_URL)
        self.assertEqual(info["mode"], "git")
        self.assertTrue((updater.staging_dir() / updater.GIT_MARKER_NAME).is_file())
        self.assertEqual(updater.pending_info()["version"], NEW[:7])

    def test_zip_install_remembers_the_commit_from_the_archive(self):
        """GitHub upisuje commit u komentar ZIP-a; tacniji je od upita pre
        preuzimanja, jer se main mogao pomeriti izmedju."""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("skripta-faks-main/run.py", "print('novo')")
            archive.writestr("skripta-faks-main/app/__init__.py", "x = 1")
            archive.comment = NEW.encode("ascii")
        staged = self.write_archive(buffer.getvalue())

        with mock.patch.object(updater, "install_kind", return_value="zip"), \
                mock.patch.object(updater, "download", return_value=staged):
            info = updater.prepare(OLD, updater.ZIP_URL)

        written = (Path(info["folder"]) / updater.INSTALLED_NAME).read_text(encoding="utf-8")
        self.assertIn(NEW, written)
        self.assertEqual(info["version"], NEW[:7])

    def test_install_pending_pulls_a_git_copy(self):
        with mock.patch.object(updater, "install_kind", return_value="git"):
            updater.prepare(NEW, updater.ZIP_URL)
        with mock.patch.object(updater, "git_pull", return_value=(True, "Fast-forward")) as pull:
            info = updater.install_pending()
        pull.assert_called_once()
        self.assertEqual(info["mode"], "git")
        self.assertIsNone(updater.pending_info(), "oznaka se brise i kad pull uspe")


class ManualRunTest(UpdaterTestCase):
    """`azuriraj.bat` pokrenut duplim klikom u ZIP instalaciji."""

    def test_up_to_date_prepares_nothing(self):
        state = {"error": "", "available": False, "installed": NEW}
        with mock.patch.object(updater, "check", return_value=state), \
                mock.patch.object(updater, "prepare") as prepare:
            self.assertEqual(updater.main(), 0)
        prepare.assert_not_called()

    def test_newer_version_is_prepared_for_the_bat_to_install(self):
        state = {"error": "", "available": True, "latest": "bbbbbbb", "latest_sha": NEW,
                 "download": updater.ZIP_URL}
        with mock.patch.object(updater, "check", return_value=state), \
                mock.patch.object(updater, "prepare") as prepare:
            self.assertEqual(updater.main(), 0)
        prepare.assert_called_once_with(NEW, updater.ZIP_URL)

    def test_failure_returns_an_error_code(self):
        with mock.patch.object(updater, "check", return_value={"error": "GitHub ne odgovara."}):
            self.assertEqual(updater.main(), 1)


class BatchFileTest(AppTestCase):
    """START.bat i azuriraj.bat se prepisuju dok se izvrsavaju. cmd ih cita sa
    diska red po red; posle prepisivanja bi nastavio na pogresnom mestu u novom
    fajlu. Ovo pinuje pravila koja to cine bezbednim."""

    def read(self, name):
        return (PROJECT_ROOT / name).read_text(encoding="utf-8")

    def test_no_labels_or_goto(self):
        """ZIP sa GitHub-a stize sa LF krajevima; cmd tada ume da promasi labelu."""
        for name in ("START.bat", "azuriraj.bat"):
            code = [line.strip().lower() for line in self.read(name).splitlines()
                    if line.strip() and not line.strip().lower().startswith("rem")]
            self.assertFalse(
                [line for line in code if line.startswith(":") or re.search(r"\bgoto\b", line)],
                f"{name} ima labelu ili goto")

    def test_start_runs_everything_in_one_block(self):
        code = self.read("START.bat")
        block = code[code.index("(\n"):]
        self.assertIn('call "%~dp0azuriraj.bat"', block)
        self.assertIn("run.py", block)
        self.assertTrue(block.rstrip().endswith(")"))

    def test_update_never_overwrites_data_or_itself_mid_run(self):
        code = self.read("azuriraj.bat")
        robocopy = next(line for line in code.splitlines() if line.strip().startswith("robocopy"))
        self.assertIn("/XD data", robocopy)
        self.assertIn("/XF azuriraj.bat", robocopy)
        self.assertIn('copy /y ".update\\novo\\azuriraj.bat" "%~f0"', code)

    def test_git_copy_is_updated_without_merging(self):
        code = self.read("azuriraj.bat")
        self.assertIn("git pull --ff-only", code)
        self.assertNotIn("reset --hard", code)


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
