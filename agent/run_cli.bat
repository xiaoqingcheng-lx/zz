@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py llm_cli.py
) else (
  python llm_cli.py
)
pause
