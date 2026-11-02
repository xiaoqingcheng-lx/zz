@echo off
title PeiHospitalMCP (127.0.0.1:8090)
chcp 65001 >nul
cd /d "D:\大语言模型\pethospitalMCP"
set MCP_HOST=127.0.0.1
set MCP_PORT=8090
set PET_HOSPITAL_BASE_URL=http://127.0.0.1:8080
echo 正在启动 PeiHospitalMCP：http://127.0.0.1:8090/mcp
echo 上游 REST 服务需先运行（pethospital.exe，默认 8080）
echo 关闭本窗口即停止 MCP 服务
echo.
".venv-mcp\Scripts\python.exe" -m pet_hospital_mcp
pause
