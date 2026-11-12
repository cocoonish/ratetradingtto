@echo off
rem TTO Masa dashboard - Windows baslatici.  Port 1057 (1055 ve 1056 kullanilmaz).
rem Bloomberg terminali aciksa canli veri, degilse Excel dosyasindaki son kayitli veri.
cd /d "%~dp0"
python -m tto %*
pause
