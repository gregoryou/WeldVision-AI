@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "INSTALL_DIR=%LOCALAPPDATA%\WeldVisionAI\venv"
set "SYSTEM_PY=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not exist "%INSTALL_DIR%\Scripts\python.exe" (
    echo Tworzenie izolowanego srodowiska na dysku lokalnym...
    if exist "%SYSTEM_PY%" (
        "%SYSTEM_PY%" -m venv "%INSTALL_DIR%"
    ) else (
        where py >nul 2>nul
        if errorlevel 1 (
            echo Nie znaleziono Python 3.13. Zainstaluj Python 3.13.
            pause
            exit /b 1
        )
        py -3.13 -m venv "%INSTALL_DIR%"
    )
    if errorlevel 1 (
        echo BLAD tworzenia srodowiska.
        pause
        exit /b 1
    )
)
set "VENV_PY=%INSTALL_DIR%\Scripts\python.exe"
"%VENV_PY%" -m pip install --upgrade pip
if errorlevel 1 (echo BLAD pip.& pause & exit /b 1)
"%VENV_PY%" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (echo BLAD instalacji pakietow.& pause & exit /b 1)
echo.
echo GOTOWE: srodowisko podstawowe WeldVision AI.
echo Dla AI na RTX uruchom Install_AI_NVIDIA_CUDA.bat
pause
