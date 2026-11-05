@echo off
chcp 65001 >nul
title xAgent
cd /d "%~dp0"
py main.py
echo.
pause
