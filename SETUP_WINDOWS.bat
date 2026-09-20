@echo off
setlocal
cd /d "%~dp0"
if not exist .venv (
  py -3 -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -e ".[desktop,dev]"
echo.
echo Setup complete.
echo Run RUN_DESKTOP.bat
pause
