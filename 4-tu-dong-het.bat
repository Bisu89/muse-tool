@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "DIR=%~1"
if "%DIR%"=="" set /p "DIR=Kéo THƯ MỤC bộ video vào đây rồi bấm Enter: "
set "DIR=%DIR:"=%"
python muse_auto.py auto --dir "%DIR%"
pause
