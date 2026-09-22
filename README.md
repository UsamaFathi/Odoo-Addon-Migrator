# Odoo Addon Migrator

Odoo Addon Migrator is an independent, local-first desktop and CLI assistant for moving custom addons upward across Odoo 14–19. It composes adjacent, source-aware migration packs and keeps the original addon directory untouched by default.

Current release candidate: **v1.0.0-rc.2**. RC1 remains the historical public release; RC2 is prepared for Windows workflow acceptance before publication.

## Desktop workflow

Install the Windows application or run `odoo-migrator-ui`, choose a `custom_addons` folder, review the detected source version and registry-provided target versions, then analyze, review findings, migrate to a separate folder, validate statically, and open the report or diff.

The desktop UI and CLI use the same application services. Long operations run in workers, and the GUI reports blockers, review-required findings, warnings, automatic fixes, source commits, and validation status separately.

## Supported versions

Production adjacent packs are available for:

```text
14 → 15 → 16 → 17 → 18 → 19
```

Any upward path through Odoo 19 is composed from those adjacent packs. There is no Odoo 20 support.

## Trust and validation

Official Odoo Community snapshots are pinned centrally for reproducible analysis. Enterprise source is never downloaded or redistributed. Static analysis and static validation do not prove runtime compatibility; installation, database, browser, and business-workflow testing remain separate responsibilities.

Automatic changes are intentionally conservative. Blockers stop migration, while review-required findings remain visible for human decisions. The generated output contains `.odoo_migrator_run.json`, `migration_report.html`, and `migration.diff`.

## Developer setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest -q
```

For the desktop shell:

```bash
python -m pip install -e ".[desktop]"
odoo-migrator-ui
```

The CLI remains available for automation:

```bash
odoo-migrator plan --from 14 --to 19
odoo-migrator source ensure 18
odoo-migrator source info 18
odoo-migrator analyze ./custom_addons --from 16 --to 19
odoo-migrator migrate ./custom_addons ./custom_addons_19 --from 16 --to 19
```

## Windows packaging

On Windows, install Python, Git for Windows, and the project build extras. Then run:

```powershell
.\scripts\build_windows.ps1
.\scripts\build_installer.ps1  # requires Inno Setup
```

The reproducible PyInstaller onedir output is `dist\OdooAddonMigrator\OdooAddonMigrator.exe`. The installer is `dist\OdooAddonMigrator_Setup.exe` when Inno Setup is available. The application can still analyze cached sources offline; first-time source acquisition requires network access.

Release testers can choose either GitHub Actions artifact:

* **Portable:** download `OdooAddonMigrator-Windows`, extract it, and run `OdooAddonMigrator.exe`.
* **Installer:** download `OdooAddonMigrator-Installer` and run `OdooAddonMigrator_Setup.exe`.

The release candidate may be unsigned, so Windows SmartScreen may display a warning.

## Cache and logs

Source caches are stored under `%USERPROFILE%\.odoo-addon-migrator\sources`. Desktop logs are stored under `%LOCALAPPDATA%\OdooAddonMigrator\logs`. The About dialog provides an Open Logs Folder action.

## Troubleshooting

See [USER_GUIDE.md](docs/USER_GUIDE.md), [WINDOWS_INSTALL.md](docs/WINDOWS_INSTALL.md), and [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md). Common issues are a missing Git executable, an unavailable source snapshot, mixed addon manifest versions, a pre-existing output folder, or blocker findings.

Independent migration utility. Not affiliated with Odoo S.A.
