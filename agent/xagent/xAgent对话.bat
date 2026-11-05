@echo off
chcp 65001 >nul
title xAgent TUI
cd /d "%~dp0"
py tui_app.py
echo.
pause
