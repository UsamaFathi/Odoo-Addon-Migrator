[CmdletBinding()]
param()
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$candidates = @(
    (Get-Command ISCC.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
)
$isccPath = $candidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
if (-not $isccPath) { throw "Inno Setup (ISCC.exe) was not found. Install Inno Setup before building the installer." }
$version = python -c "from importlib.metadata import version; print(version('odoo-addon-migrator'))"
& $isccPath "/DMyAppVersion=$version" packaging\OdooAddonMigrator.iss
Write-Host "Built dist\OdooAddonMigrator_Setup.exe"
