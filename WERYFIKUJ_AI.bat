@echo off
setlocal
chcp 65001 >nul
set "PY=%LOCALAPPDATA%\WeldVisionAI\venv\Scripts\python.exe"
if not exist "%PY%" (echo Najpierw Install_Base.bat&pause&exit /b 1)
"%PY%" "%~dp0weldvision_ai.py" --diagnose
pause
