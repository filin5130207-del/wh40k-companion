@echo off
REM Persistent ODPM start via WSL Debian. Does NOT use --db-drop.
setlocal
set "SCRIPT=/mnt/c/Users/Павел/wh40k-companion/scripts/odpm_up.sh"
wsl -d Debian -- bash -lc "bash '%SCRIPT%'"
exit /b %ERRORLEVEL%
