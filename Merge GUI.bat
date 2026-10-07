@echo off
REM PDF Page Merger - the window version. Double-click me, or drop files onto me
REM to start with them already listed.
cd /d "%~dp0"

REM Prefer this project's own interpreter (.python\, built from
REM requirements-build.txt) over whatever is on PATH, which on the development
REM machine is a Python shared with an unrelated project. A copy of this folder
REM without .python\ falls back to PATH as before.
REM pythonw runs it without a console window behind it; python is the fallback.
set "PYEXE=.python\pythonw.exe"
if not exist "%PYEXE%" (
    set "PYEXE=pythonw"
    where pythonw >nul 2>&1 || set "PYEXE=python"
)

start "" "%PYEXE%" merge_gui.pyw %*
