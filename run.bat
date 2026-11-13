@echo off
rem TTO Masa dashboard - Windows baslatici.  Port 1057 (5000 ve 5001 kullanilmaz).
rem Bloomberg terminali aciksa canli veri, degilse Excel dosyasindaki son kayitli veri.
rem Kurulum gerekmez: web paketleri kurulu degilse vendor\ klasorundeki kopyalar kullanilir.
cd /d "%~dp0"
python -c "import sys" >nul 2>nul
if not errorlevel 1 goto withpython
py -3 -c "import sys" >nul 2>nul
if not errorlevel 1 goto withpy
echo Python bulunamadi.  README.md icindeki "Hicbir sey kurmadan" bolumune bakin.
pause
exit /b 1
:withpython
python -m tto %*
pause
exit /b
:withpy
py -3 -m tto %*
pause
