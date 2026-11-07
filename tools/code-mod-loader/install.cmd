@echo off
rem Install the code-mod loader and its mods in one step. Close the game first.
rem   install.cmd                   every bundled mod except the memory-add sample
rem   install.cmd portals floors    only the mods you name
rem   install.cmd --game "E:\Games\Anywhere RPG"   if the game isn't in a Steam library
setlocal
where node >nul 2>nul || (
  echo error: Node.js was not found on PATH. Install it from https://nodejs.org/
  set FAILED=1
  goto done
)
node "%~dp0patch.mjs" add %*
if errorlevel 1 set FAILED=1

:done
rem Keep the window open when started by double-click (this cmd.exe's parent is Explorer).
powershell -NoProfile -Command "$cmd=(Get-CimInstance Win32_Process -Filter ('ProcessId='+$PID)).ParentProcessId; $parent=(Get-CimInstance Win32_Process -Filter ('ProcessId='+$cmd)).ParentProcessId; if ((Get-Process -Id $parent -ErrorAction SilentlyContinue).Name -eq 'explorer') { exit 0 } else { exit 1 }" && pause
if defined FAILED exit /b 1
exit /b 0
