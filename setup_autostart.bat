@echo off
chcp 65001 >nul
REM คลิกขวา > Run as administrator  (ทำครั้งเดียว)
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_autostart.ps1"
pause
