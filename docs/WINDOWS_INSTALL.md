# Windows installation

The preferred distribution is `OdooAddonMigrator_Setup.exe`. It installs per-user under `%LOCALAPPDATA%\Programs\OdooAddonMigrator`, adds a Start Menu entry, and can create an optional desktop shortcut. It does not require administrator privileges.

The GitHub Actions artifacts provide two choices:

* **Portable:** download `OdooAddonMigrator-Windows`, extract it, and run `OdooAddonMigrator.exe`.
* **Installer:** download `OdooAddonMigrator-Installer` and run `OdooAddonMigrator_Setup.exe`.

Windows SmartScreen may show a warning for an unsigned build. Verify the artifact source before choosing **More info** and **Run anyway**. This project is independent and is not affiliated with Odoo S.A.

The application uses Git for exact Odoo Community source acquisition. Install Git for Windows and ensure `git.exe` is available on PATH, or pre-populate the source cache. The first analysis of a path may download the required official snapshots; later work can run offline from the cache.

Git is not required when every source version is supplied as a validated Local Exact Source. Select the local Odoo repository in the source card; the app reads `odoo/release.py`, records available Git metadata, and never changes that directory.

Maintainers can build the application with:

```powershell
.\scripts\build_windows.ps1
```

The optional installer requires Inno Setup and is built with:

```powershell
.\scripts\build_installer.ps1
```
