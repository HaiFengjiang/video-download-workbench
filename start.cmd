@echo off
chcp 65001 >nul
cd /d "%~dp0"
where pythonw >nul 2>nul
if errorlevel 1 goto use_python
start "" pythonw "%~dp0gui.py"
exit /b 0

:use_python
where python >nul 2>nul
if errorlevel 1 goto no_python
python "%~dp0gui.py"
exit /b 0

:no_python
echo Python not found. Please install Python 3.9+ and add it to PATH.
pause
exit /b 1
