@echo off
chcp 65001 >nul
cd /d "%~dp0"
where pythonw >nul 2>nul
if not errorlevel 1 (
  start "" pythonw "%~dp0gui.py"
  exit /b 0
)
where python >nul 2>nul
if errorlevel 1 (
  echo 未找到 Python，请先安装 Python 3.9+ 并加入 PATH。
  pause
  exit /b 1
)
python "%~dp0gui.py"
if errorlevel 1 pause
