#!/usr/bin/env python3
"""Pokretac testova: python run_tests.py [ime_modula ...]

Dve stvari se dese PRE nego sto se ijedan test uveze:

1. `SKRIPTA_BLOCK_NETWORK` - nijedan AI poziv ne izlazi iz procesa, pa suite ne
   moze da potrosi kvotu ni da posalje gradivo na internet
2. `SKRIPTA_DATA_DIR` - podaci idu u privremeni folder; `tests/base.py` to jos
   jednom proverava na zivoj putanji

Izlazni kod je pravi izlazni kod suite-a. Ako ovo prosledis kroz `| tail`,
izgubices ga - status pipeline-a je status POSLEDNJE komande.
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

os.environ["SKRIPTA_BLOCK_NETWORK"] = "1"
_TEMP_DIR = tempfile.mkdtemp(prefix="skripta-suite-")
os.environ["SKRIPTA_DATA_DIR"] = _TEMP_DIR
os.environ["SKRIPTA_PROPOSALS_DIR"] = str(Path(_TEMP_DIR) / "predlozi")


def module_names() -> list[str]:
    """Svi tests/test_*.py, po imenu.

    Namerno bez `unittest.discover`: on je na Python 3.14 odbio da uveze paket
    testova, a i ovako nema nikakvog indeksa koji moze da se raziđe sa stvarnim
    fajlovima kad se test doda ili obrise.
    """
    return sorted(path.stem for path in (BASE_DIR / "tests").glob("test_*.py"))


def main(argv: list[str]) -> int:
    loader = unittest.TestLoader()
    names = argv or module_names()
    if not names:
        print("Nema nijednog test modula u tests/.")
        return 1
    suite = loader.loadTestsFromNames([f"tests.{name}" for name in names])

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print()
    print("-" * 64)
    print(f"  ukupno   : {result.testsRun}")
    print(f"  pao      : {len(result.failures)}   (test se ne slaze sa kodom)")
    print(f"  greska   : {len(result.errors)}     (nesto je puklo pre provere)")
    print(f"  preskocen: {len(result.skipped)}")
    print("-" * 64)

    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    try:
        code = main(sys.argv[1:])
    finally:
        shutil.rmtree(_TEMP_DIR, ignore_errors=True)
    raise SystemExit(code)
