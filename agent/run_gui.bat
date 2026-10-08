@echo off
cd /d "%~dp0"
py -c "import tkinter" >nul 2>&1 && (start "" pyw llm_gui.py & exit /b)
python -c "import tkinter" >nul 2>&1 && (start "" pythonw llm_gui.py & exit /b)
echo [错误] 没找到带 tkinter 的 Python，无法打开窗口版。
echo 终端版可以直接用： python llm.py "你的提示词"
pause
