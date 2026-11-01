@echo off
chcp 65001 >nul
REM เปิดลิงก์ออนไลน์ผ่าน Cloudflare Tunnel (ฟรี ไม่ต้องสมัคร) — ลิงก์อยู่ในไฟล์ tunnel_log.txt
cd /d "%~dp0"
:loop
cloudflared tunnel --no-autoupdate --url http://localhost:8501 > tunnel_log.txt 2>&1
timeout /t 10 /nobreak >nul
goto loop
