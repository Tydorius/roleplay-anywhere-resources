@echo off
rem Restore the game's original files. Your code-mods folder is left as it is.
rem Extra arguments pass through, e.g.  uninstall.cmd --game "E:\Games\Anywhere RPG"
setlocal
where node >nul 2>nul || (
  echo error: Node.js was not found on PATH. Install it from https://nodejs.org/
  set FAILED=1
  goto done
)
node "%~dp0patch.mjs" uninstall %*
if errorlevel 1 set FAILED=1

:done
rem Keep the window open when started by double-click (this cmd.exe's parent is Explorer).
powershell -NoProfile -Command "$cmd=(Get-CimInstance Win32_Process -Filter ('ProcessId='+$PID)).ParentProcessId; $parent=(Get-CimInstance Win32_Process -Filter ('ProcessId='+$cmd)).ParentProcessId; if ((Get-Process -Id $parent -ErrorAction SilentlyContinue).Name -eq 'explorer') { exit 0 } else { exit 1 }" && pause
if defined FAILED exit /b 1
exit /b 0
