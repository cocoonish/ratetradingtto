@echo off
rem TTO Masa dashboard - Windows baslatici.  Port 1057 (5000 ve 5001 kullanilmaz).
rem Bloomberg terminali aciksa canli veri, degilse Excel dosyasindaki son kayitli veri.
cd /d "%~dp0"
python -m tto %*
pause
