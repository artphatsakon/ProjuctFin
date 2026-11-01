@echo off
chcp 65001 >nul
REM ยกเลิกการทำงานอัตโนมัติทั้งหมด (คลิกขวา > Run as administrator)
schtasks /End /TN "\ProjuctFin\Web" >nul 2>&1
schtasks /End /TN "\ProjuctFin\Tunnel" >nul 2>&1
schtasks /Delete /TN "\ProjuctFin\Update data (midnight)" /F
schtasks /Delete /TN "\ProjuctFin\Web" /F
schtasks /Delete /TN "\ProjuctFin\Tunnel" /F
taskkill /IM cloudflared.exe /F >nul 2>&1
echo ยกเลิกแล้ว
pause
