@echo off
chcp 65001 >nul
REM ดับเบิลคลิก หรือตั้งให้ Task Scheduler รันไฟล์นี้ทุกวัน
REM ถ้าอยากให้เทรนโมเดลใหม่ด้วย ให้เพิ่ม --train ต่อท้าย update_data.py
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" update_data.py
) else (
    python update_data.py
)
