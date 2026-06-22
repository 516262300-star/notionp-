@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "weekly_report_app.pyw"
) else (
    start "" pythonw "weekly_report_app.pyw"
)
