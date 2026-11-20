@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
echo ============================================================
echo  WELDVISION AI 3.5.0 - Instalacja Windows / RTX NVIDIA
 echo ============================================================
echo.
echo ETAP 1/2 - biblioteki programu i izolowane srodowisko Python
call "%~dp0Install_Base.bat"
if errorlevel 1 (
  echo Instalacja podstawowa nie powiodla sie.
  pause
  exit /b 1
)
echo.
echo ETAP 2/2 - AI / NVIDIA CUDA
call "%~dp0Install_AI_NVIDIA_CUDA.bat"
if errorlevel 1 (
  echo Instalacja AI nie powiodla sie.
  echo Program nadal mozna uruchomic bez SAM i wykonywac pomiary reczne.
  pause
  exit /b 1
)
echo.
echo Instalacja zakonczona. Uruchom Start_WeldVision_AI.bat lub Start_WeldVision_AI.vbs
pause
