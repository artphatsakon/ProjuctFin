@echo off
chcp 65001 >nul
REM แสดงลิงก์เว็บออนไลน์ปัจจุบัน
cd /d "%~dp0"
echo.
echo  ลิงก์เว็บออนไลน์:
powershell -NoProfile -Command "$m = Select-String -Path 'tunnel_log.txt' -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' -AllMatches -ErrorAction SilentlyContinue | Select-Object -Last 1; if ($m) { '  ' + $m.Matches[0].Value } else { '  (not found yet - wait 30 seconds and run show_url.bat again)' }"
echo.
pause
