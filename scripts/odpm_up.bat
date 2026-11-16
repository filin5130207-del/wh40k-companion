@echo off
REM Persistent ODPM start via WSL Debian. Does NOT use --db-drop.
REM odpm_keepalive.ps1 holds a hidden wsl.exe. Without it, WSL powers Debian
REM off when this one-shot command exits and Docker stops. Volume is kept.
setlocal
set "SCRIPT=/mnt/c/Users/Павел/wh40k-companion/scripts/odpm_up.sh"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0odpm_keepalive.ps1"
if errorlevel 1 exit /b %ERRORLEVEL%
wsl -d Debian -- bash -lc "bash '%SCRIPT%'"
exit /b %ERRORLEVEL%
