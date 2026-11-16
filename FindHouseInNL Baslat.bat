@echo off
chcp 65001 >nul
cd /d "%~dp0"
title FindHouseInNL
if not exist config.yaml copy config.example.yaml config.yaml >nul
echo.
echo  FindHouseInNL calisiyor.
echo  Bu siyah pencereyi KAPATMAYIN (kucultebilirsiniz).
echo  Program birazdan internet tarayicinizda acilacak: http://127.0.0.1:8000
echo.
start "" /b cmd /c "timeout /t 4 >nul & start http://127.0.0.1:8000"
where py >nul 2>nul && (py run.py serve) || (python run.py serve)
echo.
echo  FindHouseInNL durdu. Yukarida kirmizi bir hata varsa fotografini cekip yardim isteyin.
echo  Ilk kez aciyorsaniz once KUR dosyasina cift tiklayin.
pause
