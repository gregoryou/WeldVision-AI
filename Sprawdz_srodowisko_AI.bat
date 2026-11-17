@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PY=%LOCALAPPDATA%\WeldVisionAI\venv\Scripts\python.exe"
if not exist "%PY%" (
    echo Brakuje srodowiska WeldVision AI. Uruchom Install_WeldVision_AI.bat
    pause
    exit /b 1
)
"%PY%" "%~dp0weldvision_ai.py" --diagnose
pause
