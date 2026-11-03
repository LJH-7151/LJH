@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" goto check_launcher
".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>nul
if not errorlevel 1 goto run_local

:check_launcher
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>nul
if not errorlevel 1 goto run_launcher

python -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>nul
if not errorlevel 1 goto run_python

echo Python 3.12 or newer is required. Install Python, then run this script again.
exit /b 1

:run_local
".venv\Scripts\python.exe" main.py %*
exit /b %errorlevel%

:run_launcher
py -3 main.py %*
exit /b %errorlevel%

:run_python
python main.py %*
exit /b %errorlevel%
