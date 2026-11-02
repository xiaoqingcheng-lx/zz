@echo off
title xAgent 技能演示辅助
chcp 65001 >nul
cd /d "D:\大语言模型\agent\xagent"
echo ==============================================
echo   1 = 备份并清空（现场演示 createSkill 建技能）
echo   2 = 从备份还原
echo   3 = 只看状态
echo ==============================================
set /p c=请输入 1 / 2 / 3 后回车：
if "%c%"=="1" py demo_skill_reset.py --backup
if "%c%"=="2" py demo_skill_reset.py --restore
if "%c%"=="3" py demo_skill_reset.py --status
echo.
pause
