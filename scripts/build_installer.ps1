[CmdletBinding()]
param()
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
if (-not $iscc) { throw "Inno Setup (ISCC.exe) was not found. Install Inno Setup before building the installer." }
$version = python -c "from importlib.metadata import version; print(version('odoo-addon-migrator'))"
& $iscc.Source "/DMyAppVersion=$version" packaging\OdooAddonMigrator.iss
Write-Host "Built dist\OdooAddonMigrator_Setup.exe"
