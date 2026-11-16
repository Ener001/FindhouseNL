@echo off
chcp 65001 >nul
cd /d "%~dp0"
title FindHouseInNL - Kurulum
echo.
echo  ==============================================
echo     FindHouseInNL kurulumu
echo     Bu pencere isini bitirene kadar bekleyin.
echo  ==============================================
echo.

rem --- 1) Python var mi? ---
set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY (
  python -c "import sys" >nul 2>nul && set "PY=python"
)
if not defined PY goto :python_yok
echo [1/3] Python bulundu.
goto :paketler

:python_yok
echo [1/3] Python bulunamadi. Simdi otomatik kuruluyor, birkac dakika surebilir...
echo       Ekranda "izin verilsin mi?" diye sorarsa EVET deyin.
echo.
winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
if errorlevel 1 goto :python_elle
echo.
echo  ----------------------------------------------
echo   Python kuruldu.
echo   Simdi bu pencereyi kapatin ve KUR dosyasina
echo   BIR KEZ DAHA cift tiklayin.
echo  ----------------------------------------------
pause
exit /b 0

:python_elle
echo.
echo  Python otomatik kurulamadi.
echo  1. Acilan sayfadan sari "Download Python" dugmesine basin.
echo  2. Inen dosyayi acin, EN ALTTAKI "Add python.exe to PATH" kutusunu isaretleyin.
echo  3. "Install Now" deyin, bitince bu KUR dosyasina tekrar cift tiklayin.
start "" https://www.python.org/downloads/
pause
exit /b 1

:paketler
echo [2/3] Gerekli parcalar indiriliyor...
%PY% -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 goto :pip_hata

if not exist config.yaml copy config.example.yaml config.yaml >nul

echo [3/3] Masaustune kisayol olusturuluyor...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d=[Environment]::GetFolderPath('Desktop'); $s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'FindHouseInNL.lnk')); $s.TargetPath='%~dp0FindHouseInNL Baslat.bat'; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%SystemRoot%\System32\shell32.dll,150'; $s.Save()" >nul 2>nul

echo.
echo  ==============================================
echo     KURULUM BITTI!
echo     Masaustundeki "FindHouseInNL" simgesine
echo     cift tiklayarak programi acabilirsiniz.
echo  ==============================================
echo.
pause
exit /b 0

:pip_hata
echo.
echo  Parcalar indirilirken bir hata oldu.
echo  - Internet baglantinizi kontrol edin ve KUR dosyasini tekrar calistirin.
echo  - Yine olmazsa bu pencerenin fotografini cekip yardim isteyin.
pause
exit /b 1
