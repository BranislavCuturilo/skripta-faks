@echo off
setlocal enabledelayedexpansion
title Instalacija - skripta-faks
color 0B

rem  Jedini fajl koji korisnik skida rucno. Odavde nadalje sve ide samo:
rem  Python (ako fali) -> aplikacija -> precica na desktopu -> pokretanje.
rem
rem  Sve se instalira u %LOCALAPPDATA%\skripta-faks, ne u Program Files:
rem  tamo se pise bez admin prava, pa instalacija nikad ne trazi lozinku.

set "APP_DIR=%LOCALAPPDATA%\skripta-faks"
set "ZIP_URL=https://github.com/BranislavCuturilo/skripta-faks/archive/refs/heads/main.zip"
set "TEMP_ZIP=%TEMP%\skripta-faks-install.zip"
set "TEMP_OUT=%TEMP%\skripta-faks-install"

echo.
echo   ================================================
echo     skripta-faks - instalacija
echo   ================================================
echo.
echo   Instalira se u: %APP_DIR%
echo.

rem ---------------------------------------------------------------- Python

set "PYCMD="
where py >nul 2>nul && set "PYCMD=py -3"
if not defined PYCMD ( where python >nul 2>nul && set "PYCMD=python" )

if defined PYCMD (
    rem  Postojeci Python moze da bude prestar. Aplikacija tone na 3.10 i nize
    rem  zbog sintakse tipova, pa je bolje da to pukne sada nego pri prvom
    rem  pokretanju, sa greskom koju niko ne prepoznaje.
    %PYCMD% -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>nul
    if errorlevel 1 (
        echo   [!] Pronadjen Python je stariji od 3.11 - instaliram noviji.
        set "PYCMD="
    ) else (
        echo   [1/4] Python je vec instaliran.
    )
)

if not defined PYCMD (
    echo   [1/4] Python nije pronadjen - preuzimam i instaliram...
    echo         ^(ovo traje minut-dva^)
    set "PY_URL=https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe"
    set "PY_EXE=%TEMP%\python-instalacija.exe"

    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
        "[Net.ServicePointManager]::SecurityProtocol='Tls12'; Invoke-WebRequest -Uri '!PY_URL!' -OutFile '!PY_EXE!' -UseBasicParsing" 2>nul

    if not exist "!PY_EXE!" (
        echo.
        echo   [X] Preuzimanje Pythona nije uspelo.
        echo       Instaliraj ga rucno sa https://www.python.org/downloads/
        echo       i pri instalaciji cekiraj "Add python.exe to PATH".
        echo.
        pause
        exit /b 1
    )

    rem  InstallAllUsers=0 = instalacija za trenutnog korisnika, bez admina.
    "!PY_EXE!" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0
    del /q "!PY_EXE!" >nul 2>nul

    rem  PATH iz ove sesije je snimljen pre instalacije, pa `py` jos ne postoji
    rem  u njemu. Zovemo launcher preko njegove poznate putanje.
    set "PYCMD=%LOCALAPPDATA%\Programs\Python\Launcher\py.exe -3"
    if not exist "%LOCALAPPDATA%\Programs\Python\Launcher\py.exe" (
        where py >nul 2>nul && set "PYCMD=py -3"
    )
    if not exist "%LOCALAPPDATA%\Programs\Python\Launcher\py.exe" (
        where py >nul 2>nul || (
            echo.
            echo   [X] Python je instaliran, ali ga ova sesija jos ne vidi.
            echo       Zatvori ovaj prozor i pokreni instalaciju jos jednom.
            echo.
            pause
            exit /b 1
        )
    )
    echo   [1/4] Python instaliran.
)

rem ------------------------------------------------------------ aplikacija

echo   [2/4] Preuzimam aplikaciju...

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "[Net.ServicePointManager]::SecurityProtocol='Tls12'; Invoke-WebRequest -Uri '%ZIP_URL%' -OutFile '%TEMP_ZIP%' -UseBasicParsing" 2>nul

if not exist "%TEMP_ZIP%" (
    echo.
    echo   [X] Preuzimanje aplikacije nije uspelo. Proveri internet vezu.
    echo.
    pause
    exit /b 1
)

if exist "%TEMP_OUT%" rmdir /s /q "%TEMP_OUT%"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "Expand-Archive -Path '%TEMP_ZIP%' -DestinationPath '%TEMP_OUT%' -Force"
del /q "%TEMP_ZIP%" >nul 2>nul

rem  GitHub pakuje sve u jedan koreni folder (skripta-faks-main).
set "SRC="
for /d %%D in ("%TEMP_OUT%\*") do set "SRC=%%D"
if not defined SRC (
    echo   [X] Preuzeta arhiva je prazna.
    pause
    exit /b 1
)

rem  /XD data = postojeci podaci se NE diraju pri ponovnoj instalaciji. Ovo je
rem  jedina linija koja deli "instalacija" od "brisanje svega sto si naucio".
robocopy "%SRC%" "%APP_DIR%" /E /XD data .git __pycache__ /NFL /NDL /NJH /NJS /NC /NS >nul
rmdir /s /q "%TEMP_OUT%" >nul 2>nul
echo   [2/4] Aplikacija je na disku.

rem --------------------------------------------------------------- precica

echo   [3/4] Pravim precicu na desktopu...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\skripta-faks.lnk'); $s.TargetPath='%APP_DIR%\START.bat'; $s.WorkingDirectory='%APP_DIR%'; $s.IconLocation='%SystemRoot%\System32\shell32.dll,21'; $s.Description='skripta-faks - ucenje uz AI'; $s.Save()" 2>nul

echo   [4/4] Gotovo.
echo.
echo   ================================================
echo     Instalirano. Pokrecem aplikaciju...
echo.
echo     Ubuduce: ikonica "skripta-faks" na desktopu.
echo     Azuriranje: dugme u aplikaciji, tab Podesavanja.
echo   ================================================
echo.

start "" "%APP_DIR%\START.bat"
timeout /t 3 >nul
exit /b 0
