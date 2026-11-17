@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PY=%LOCALAPPDATA%\WeldVisionAI\venv\Scripts\python.exe"
if not exist "%PY%" (
    echo Najpierw uruchom Install_Base.bat
    pause
    exit /b 1
)
echo Instalowanie PyTorch CUDA dla NVIDIA (CUDA 13.0)...
"%PY%" -m pip install --upgrade torch torchvision --index-url https://download.pytorch.org/whl/cu130
if errorlevel 1 (echo BLAD instalacji PyTorch CUDA.& pause & exit /b 1)
"%PY%" -m pip install -r "%~dp0requirements_ai.txt"
if errorlevel 1 (echo BLAD instalacji Transformers.& pause & exit /b 1)
echo.
echo Diagnostyka srodowiska:
"%PY%" "%~dp0weldvision_ai.py" --diagnose
echo.
echo Przy CUDA: True mozna wybrac GPU w aplikacji.
pause
