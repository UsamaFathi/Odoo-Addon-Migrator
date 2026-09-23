@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo        Odoo Addon Migrator - Local Windows Build
echo ============================================================
echo.
echo This build runs entirely on this PC.
echo GitHub Actions are NOT used.
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python was not found in PATH.
    echo Install Python 3.12 and enable "Add python.exe to PATH".
    pause
    exit /b 1
)

echo [1/5] Python version
python --version
if errorlevel 1 goto :failed

echo.
echo [2/5] Installing/updating local build dependencies...
python -m pip install --upgrade pip
if errorlevel 1 goto :failed
python -m pip install -e ".[desktop,dev,build]"
if errorlevel 1 goto :failed

echo.
echo [3/5] Running local test suite...
python -m pytest -q
if errorlevel 1 (
    echo.
    echo [ERROR] Tests failed. The EXE/installer will NOT be built.
    echo Fix the reported failure first, then run this file again.
    pause
    exit /b 1
)

echo.
echo [4/5] Building Windows portable application...
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\build_windows.ps1" -SkipTests
if errorlevel 1 goto :failed

echo.
echo [5/5] Building Windows Setup.exe...
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\build_installer.ps1"
if errorlevel 1 (
    echo.
    echo [ERROR] Installer build failed.
    echo If the message says ISCC.exe was not found, install Inno Setup 6
    echo and run BUILD_LOCAL_WINDOWS.bat again.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo BUILD COMPLETE
echo ============================================================
echo.
echo Setup:
echo   %CD%\dist\OdooAddonMigrator_Setup.exe
echo.
echo Portable EXE:
echo   %CD%\dist\OdooAddonMigrator\OdooAddonMigrator.exe
echo.

if exist "%CD%\dist\OdooAddonMigrator_Setup.exe" (
    explorer.exe /select,"%CD%\dist\OdooAddonMigrator_Setup.exe"
)

pause
exit /b 0

:failed
echo.
echo [ERROR] Local build failed.
echo Review the error above, then run this file again.
pause
exit /b 1
