@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run SETUP_WINDOWS.bat first.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
cmd /k "odoo-migrator --help"
