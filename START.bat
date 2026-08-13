@echo off
setlocal
title skripta-faks
cd /d "%~dp0"

set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 run.py
    goto :done
)

where python >nul 2>nul
if %errorlevel%==0 (
    python run.py
    goto :done
)

echo.
echo   Python nije pronadjen na ovom racunaru.
echo   Instaliraj Python 3.11 ili noviji sa https://www.python.org/downloads/
echo   i pri instalaciji cekiraj "Add python.exe to PATH".
echo.

:done
echo.
pause
