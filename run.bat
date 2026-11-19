@echo off
rem TTO Masa dashboard - Windows baslatici.  Port 1057 (5000 ve 5001 kullanilmaz).
rem Bloomberg terminali aciksa canli veri, degilse Excel dosyasindaki son kayitli veri.
rem Kurulum gerekmez: web paketleri kurulu degilse vendor\ klasorundeki kopyalar kullanilir.
rem Anaconda / Miniconda varsa once onu acar (Anaconda Prompt gibi: Scripts\activate.bat): komut penceresi
rem acilamayan makinede de cift tiklamak yeter.  Bilinen yerlerde degilse TTO_CONDA ortam degiskenine klasorunu yazin.
setlocal
set "TTO_ACT="
if defined TTO_CONDA if exist "%TTO_CONDA%\Scripts\activate.bat" set "TTO_ACT=%TTO_CONDA%"
if not defined TTO_ACT for %%R in ("%USERPROFILE%\Anaconda3" "%USERPROFILE%\Miniconda3" "%USERPROFILE%\miniforge3" "%LOCALAPPDATA%\anaconda3" "%LOCALAPPDATA%\Continuum\anaconda3" "%LOCALAPPDATA%\miniconda3" "%ProgramData%\Anaconda3" "%ProgramData%\Miniconda3") do if not defined TTO_ACT if exist "%%~R\Scripts\activate.bat" set "TTO_ACT=%%~R"
if not defined TTO_ACT goto findpython
echo Anaconda: %TTO_ACT%
call "%TTO_ACT%\Scripts\activate.bat" "%TTO_ACT%"
:findpython
cd /d "%~dp0"
python -c "import sys" >nul 2>nul
if not errorlevel 1 goto withpython
py -3 -c "import sys" >nul 2>nul
if not errorlevel 1 goto withpy
echo Python bulunamadi.  Anaconda baska bir klasordeyse TTO_CONDA ortam degiskenine o klasoru yazin ya da Anaconda
echo Prompt'ta bu klasore gelip:  python -m tto   README.md icindeki "Hicbir sey kurmadan" bolumune de bakin.
pause
exit /b 1
:withpython
python -m tto %*
pause
exit /b
:withpy
py -3 -m tto %*
pause
