@echo off
setlocal
chcp 65001 >nul
set "PY=%LOCALAPPDATA%\WeldVisionAI\venv\Scripts\python.exe"
if not exist "%PY%" (
    echo Najpierw uruchom Install_Base.bat
    pause
    exit /b 1
)
"%PY%" -m pip install pytest
if errorlevel 1 (pause & exit /b 1)
cd /d "%~dp0"
"%PY%" -m pytest -q tests
pause
