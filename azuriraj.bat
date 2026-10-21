@echo off
setlocal
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

rem  Azuriranje aplikacije. Dva nacina pokretanja:
rem
rem    1. START.bat ga zove pri SVAKOM startu: ugradi samo ono sto je dugme u
rem       aplikaciji pripremilo u .update\. Kad nema nicega, izlazi tiho.
rem    2. Dupli klik (ili "azuriraj.bat /sada" iz terminala): azurira ODMAH.
rem         git kopija  -> git pull --ff-only (nikad ne spaja, ne brise izmene)
rem         ZIP kopija  -> Python preuzme najnoviji main sa GitHub-a u .update\,
rem                        a ugradnja ide isto kao u slucaju 1
rem
rem  Ovaj fajl i START.bat se PREPISUJU DOK SE IZVRSAVAJU (git pull, robocopy).
rem  cmd cita .bat red po red sa diska, pa bi posle prepisivanja nastavio na
rem  pogresnom mestu u novom fajlu. Zato je svaki korak koji menja fajlove u
rem  jednom bloku ( ... ) koji se zavrsava sa exit: blok se procita ceo pre
rem  izvrsavanja, i posle njega se iz fajla vise nista ne cita.
rem  Bez goto i labela: ZIP sa GitHub-a stize sa LF krajevima redova, a cmd sa
rem  njima ume da promasi labelu.

rem  findstr, ne find: Git za Windows ume da stavi svoj Unix `find` u PATH
rem  ispred Windows-ovog, i tada se dupli klik ne bi prepoznao.
set "RUCNO="
if /i "%~1"=="/sada" set "RUCNO=1"
echo %cmdcmdline% | findstr /i /c:"%~nx0" >nul && set "RUCNO=1"

set "GIT="
if exist ".git\" where git >nul 2>nul && set "GIT=1"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"

rem ------------------------------------------------- rucno, git kopija

if defined RUCNO if defined GIT (
    echo.
    echo   Azuriram preko git-a...
    echo.
    git pull --ff-only
    if errorlevel 1 (
        echo.
        echo   [X] Azuriranje nije uspelo. Najcesce: u kodu imas izmene koje nisu
        echo       poslate. Otvori terminal u ovom folderu i pokreni: git status
    ) else (
        echo.
        echo   Gotovo. Ako je aplikacija otvorena, zatvori je i pokreni ponovo.
    )
    echo.
    pause
    exit /b
)

rem ------------------------------------------------- rucno, ZIP kopija

if defined RUCNO if not defined PY (
    echo.
    echo   [X] Python nije pronadjen - ne mogu da preuzmem novu verziju.
    echo.
    pause
    exit /b 1
)

if defined RUCNO (
    echo.
    echo   Proveravam ima li novije verzije...
    %PY% -m app.services.updater
    if errorlevel 1 (
        echo.
        pause
        exit /b 1
    )
)

rem ------------------------------------------- pripremljeno: git pull

if exist ".update\git" (
    rmdir /s /q ".update" >nul 2>nul
    if defined GIT (
        echo.
        echo   Ugradjujem novu verziju preko git-a...
        git pull --ff-only
        if errorlevel 1 (
            echo   [X] git pull nije uspeo - aplikacija se pokrece u staroj verziji.
            timeout /t 5 >nul
        )
    )
    exit /b 0
)

rem -------------------------------------------- pripremljeno: ZIP kod

if not exist ".update\spremno.json" (
    if defined RUCNO pause
    exit /b 0
)
if not exist ".update\novo\run.py" (
    rem  Marker postoji, ali raspakovanog koda nema - prekinuto preuzimanje.
    rem  Brise se, da se ne pokusava ugradnja praznog foldera do kraja sveta.
    rmdir /s /q ".update" >nul 2>nul
    exit /b 0
)

rem  /XD data = podaci se ne diraju, nikad. Bez ovoga bi azuriranje obrisalo
rem  bazu sa pitanjima i napretkom. /XF azuriraj.bat = ovaj fajl se menja tek
rem  na kraju bloka, posle cega se iz njega vise ne cita.
rem  robocopy vraca 0-7 kao uspeh; 8 i vise je prava greska.
rem  Stari .pyc-evi znaju da nadzive svoj .py i tada se izvrsava kod koji vise
rem  ne postoji u izvoru - zato se brisu.
(
    echo.
    echo   Ugradjujem novu verziju...
    robocopy ".update\novo" "." /E /XD data .git __pycache__ /XF azuriraj.bat /NFL /NDL /NJH /NJS /NC /NS >nul
    if errorlevel 8 (
        echo   Ugradnja nije uspela. Aplikacija se pokrece u staroj verziji.
        echo   Preuzeti fajlovi ostaju u .update\novo ako zelis rucno.
        timeout /t 4 >nul
        exit /b 1
    )
    for /d /r "%~dp0" %%D in (__pycache__) do rmdir /s /q "%%D" >nul 2>nul
    if exist ".update\novo\azuriraj.bat" copy /y ".update\novo\azuriraj.bat" "%~f0" >nul
    rmdir /s /q ".update" >nul 2>nul
    echo   Nova verzija je ugradjena.
    if defined RUCNO echo   Ako je aplikacija otvorena, zatvori je i pokreni ponovo.
    echo.
    if defined RUCNO pause
    exit /b 0
)
