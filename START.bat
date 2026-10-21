@echo off
setlocal
title skripta-faks
cd /d "%~dp0"

set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

rem  Ceo ostatak je JEDAN blok: azuriraj.bat ume da prepise i ovaj fajl dok se
rem  izvrsava (git pull, robocopy), a cmd bi posle toga nastavio da cita na
rem  pogresnom mestu u novom fajlu. Blok se procita ceo pre nego sto krene.
rem  Bez goto i labela iz istog razloga - i zato sto ZIP sa GitHub-a stize sa
rem  LF krajevima redova, a cmd sa njima ume da promasi labelu.
rem
rem  Ako je nova verzija preuzeta iz aplikacije, ugradjuje se na pocetku - dok
rem  Python jos nije startovao i dok nijedan .py fajl nije zauzet. Puna putanja:
rem  uz NoDefaultCurrentDirectoryInExePath cmd ne trazi .bat u tekucem folderu,
rem  i ugradnja se tada ne bi desila nikad.
(
    if exist "%~dp0azuriraj.bat" call "%~dp0azuriraj.bat"
    where py >nul 2>nul
    if not errorlevel 1 (
        py -3 run.py
    ) else (
        where python >nul 2>nul
        if not errorlevel 1 (
            python run.py
        ) else (
            echo.
            echo   Python nije pronadjen na ovom racunaru.
            echo   Instaliraj Python 3.11 ili noviji sa https://www.python.org/downloads/
            echo   i pri instalaciji cekiraj "Add python.exe to PATH".
        )
    )
    echo.
    pause
    exit /b
)
