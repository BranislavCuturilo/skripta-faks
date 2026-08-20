@echo off
setlocal
cd /d "%~dp0"

rem  Ugradnja preuzete verzije. Zove ga START.bat, PRE nego sto Python krene -
rem  jedini trenutak u kome aplikacija ne drzi nijedan svoj .py fajl. Iz ziveg
rem  procesa se ovo na Windows-u ne moze uraditi.
rem
rem  Ako nema sta da se ugradi, izlazi tiho: START.bat ga zove svaki put.

if not exist ".update\spremno.json" exit /b 0
if not exist ".update\novo\run.py" (
    rem  Marker postoji, ali raspakovanog koda nema - prekinuto preuzimanje.
    rem  Brise se, da se ne pokusava ugradnja praznog foldera do kraja sveta.
    rmdir /s /q ".update" >nul 2>nul
    exit /b 0
)

echo.
echo   Ugradjujem novu verziju...

rem  /XD data = podaci se ne diraju, nikad. Bez ovoga bi azuriranje obrisalo
rem  bazu sa pitanjima i napretkom.
robocopy ".update\novo" "." /E /XD data .git __pycache__ /NFL /NDL /NJH /NJS /NC /NS >nul

rem  robocopy vraca 0-7 kao uspeh; 8 i vise je prava greska.
if errorlevel 8 (
    echo   Ugradnja nije uspela. Aplikacija se pokrece u staroj verziji.
    echo   Preuzeti fajlovi ostaju u .update\novo ako zelis rucno.
    timeout /t 4 >nul
    exit /b 1
)

rmdir /s /q ".update" >nul 2>nul

rem  Stari .pyc-evi znaju da nadzive svoj .py i tada se izvrsava kod koji vise
rem  ne postoji u izvoru.
for /d /r "%~dp0" %%D in (__pycache__) do rmdir /s /q "%%D" >nul 2>nul

echo   Nova verzija je ugradjena.
echo.
exit /b 0
