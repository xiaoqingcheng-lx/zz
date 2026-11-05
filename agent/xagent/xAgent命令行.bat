@echo off
chcp 65001 >nul
title xAgent CLI
cd /d "%~dp0"
py main.py
echo.
pause
