@echo off
chcp 65001 >nul
title Chat TUI - qwen
cd /d "%~dp0"
py main.py
echo.
pause
