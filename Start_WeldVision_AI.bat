@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PY=%LOCALAPPDATA%\WeldVisionAI\venv\Scripts\python.exe"
if not exist "%PY%" (
    echo Brakuje srodowiska WeldVision AI.
    echo Uruchom najpierw Install_Base.bat
    pause
    exit /b 1
)
"%PY%" "%~dp0weldvision_ai.py"
if errorlevel 1 (
    echo.
    echo Program zakonczyl sie bledem. Sprawdz weldvision_start_error.log
    pause
)
