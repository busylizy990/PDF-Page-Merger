@echo off
REM PDF Page Merger - double-click me, or drag PDFs, images, Word docs and
REM spreadsheets onto me.
REM  - No files dropped : merges everything in .\input (or follows order.txt)
REM  - Files dropped    : merges those files, in the order Windows hands them over
cd /d "%~dp0"

REM Prefer this project's own interpreter (.python\, built from
REM requirements-build.txt) over whatever is on PATH; fall back to PATH, then
REM to the py launcher, so a copy without .python\ still works.
set "PYEXE=.python\python.exe"
if not exist "%PYEXE%" (
    set "PYEXE=python"
    where python >nul 2>&1 || set "PYEXE=py"
)

"%PYEXE%" merge.py %*

echo.
pause
