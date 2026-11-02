@echo off
chcp 65001 >nul
cd /d "%~dp0"
python muse_auto.py login
pause
