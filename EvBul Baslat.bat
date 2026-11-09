@echo off
chcp 65001 >nul
cd /d "%~dp0"
title EvBul
echo EvBul baslatiliyor... Bu pencereyi KAPATMA (kucultebilirsin).
echo Arayuz birazdan tarayicinda acilacak: http://127.0.0.1:8000
echo.
start "" /b cmd /c "timeout /t 4 >nul & start http://127.0.0.1:8000"
where py >nul 2>nul && (py run.py serve) || (python run.py serve)
echo.
echo EvBul durdu. Yukarida hata varsa ekran goruntusunu Claude'a at.
pause
