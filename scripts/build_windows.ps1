[CmdletBinding()]
param([switch]$SkipTests)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
if (-not $SkipTests) { python -m pytest -q }
python -m pip install -e ".[desktop,build]"
if (Test-Path build) { Remove-Item -Recurse -Force build }
if (Test-Path dist\OdooAddonMigrator) { Remove-Item -Recurse -Force dist\OdooAddonMigrator }
New-Item -ItemType Directory -Path build | Out-Null
$version = python -c "from importlib.metadata import version; print(version('odoo-addon-migrator'))"
$versionFile = Join-Path (Resolve-Path build) "version_info.txt"
$displayVersion = $version -replace "rc", "-rc."
(Get-Content packaging\version_info_template.txt -Raw).Replace("{{VERSION}}", $displayVersion) | Set-Content $versionFile -Encoding utf8
$env:ODOO_MIGRATOR_VERSION_FILE = $versionFile
python -m PyInstaller --noconfirm --clean packaging\OdooAddonMigrator.spec
& dist\OdooAddonMigrator\OdooAddonMigrator.exe --smoke-test
Write-Host "Built dist\OdooAddonMigrator\OdooAddonMigrator.exe"
