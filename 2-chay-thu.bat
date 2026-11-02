@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "CSV=%~1"
if "%CSV%"=="" set /p "CSV=Kéo file CSV vào đây rồi bấm Enter: "
set "CSV=%CSV:"=%"
python muse_auto.py run --csv "%CSV%" --dry
pause
