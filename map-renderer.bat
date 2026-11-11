@echo off
rem Starts the map-renderer tool (tools\map_renderer). All arguments are passed through.
rem Without arguments the interactive assistant starts, e.g. by double-click.
setlocal
set "MAP_RENDERER=%~dp0tools\map_renderer"
set "CHECK=import sys; sys.exit(sys.version_info < (3, 10))"

rem Prefer the Python launcher, then python on PATH. The Microsoft Store stub
rem "python.exe" fails the version check and is skipped.
py -3 -c "%CHECK%" >nul 2>nul
if not errorlevel 1 (
    py -3 "%MAP_RENDERER%" %*
    goto done
)
python -c "%CHECK%" >nul 2>nul
if not errorlevel 1 (
    python "%MAP_RENDERER%" %*
    goto done
)

echo Python 3.10 or newer was not found. 1>&2
echo Install it from https://www.python.org/downloads/ and enable "Add python.exe to PATH". 1>&2
set "CODE=9009"
goto finish

:done
set "CODE=%errorlevel%"

:finish
rem Started by double-click? Only Explorer appends a quoted space:
rem   cmd.exe /c ""...\map-renderer.bat" "    (PowerShell: ...bat"", Git Bash: no quotes)
rem Then keep the window open so the result can be read.
setlocal EnableDelayedExpansion
set "CMDLINE=!cmdcmdline!"
set "STRIPPED=!CMDLINE:%~nx0" "=!"
if "!STRIPPED!" neq "!CMDLINE!" pause
endlocal & exit /b %CODE%
