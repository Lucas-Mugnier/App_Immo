@echo off
REM Double-clic ou "refresh" dans cmd : collecte + export + publication des annonces
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0refresh.ps1" %*
pause
