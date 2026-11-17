@echo off
setlocal
set "VBS=%~dp0Start_WeldVision_AI.vbs"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$w=New-Object -ComObject WScript.Shell; $s=$w.CreateShortcut([IO.Path]::Combine([Environment]::GetFolderPath('Desktop'),'WeldVision AI.lnk')); $s.TargetPath=([IO.Path]::Combine($env:WINDIR,'System32','wscript.exe')); $s.Arguments=[char]34 + $env:VBS + [char]34; $s.WorkingDirectory='%~dp0'; $s.Save()"
if errorlevel 1 (echo Nie udalo sie utworzyc skrotu.& pause & exit /b 1)
echo Utworzono skrot WeldVision AI na pulpicie.
pause
