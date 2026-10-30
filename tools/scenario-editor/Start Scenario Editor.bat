@echo off
rem Double-click to open the Scenario Editor. Close this window to stop it.
setlocal
cd /d "%~dp0"

rem "python" may be the Microsoft Store placeholder, so check each one actually runs.
set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY python --version >nul 2>&1 && set "PY=python"
if not defined PY python3 --version >nul 2>&1 && set "PY=python3"

if not defined PY (
  echo Python 3 is needed to run the Scenario Editor.
  echo Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH",
  echo then double-click this file again.
  echo.
  pause
  exit /b 1
)

echo Starting the Scenario Editor. It opens in your browser; close this window to stop it.
echo.
%PY% scenario_editor.py %*
if errorlevel 1 (
  echo.
  pause
)
