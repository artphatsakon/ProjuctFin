@echo off
chcp 65001 >nul
REM เปิดเว็บ Streamlit ที่พอร์ต 8501 — ถ้าเว็บหยุดทำงาน จะเปิดใหม่เองใน 10 วินาที
cd /d "%~dp0"
set PY=python
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
:loop
echo %date% %time% starting web >> web_log.txt
"%PY%" -m streamlit run app.py --server.port 8501 --server.headless true >> web_log.txt 2>&1
timeout /t 10 /nobreak >nul
goto loop
