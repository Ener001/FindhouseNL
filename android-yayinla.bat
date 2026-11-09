@echo off
rem Yeni Android surumunu siteye hazirlar: APK'yi kopyalar ve version.json'u gunceller.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\android-yayinla.ps1"
pause
