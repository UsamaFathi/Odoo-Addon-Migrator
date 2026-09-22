# Odoo Addon Migrator v1.0.0-rc.2

RC2 is a Windows desktop release candidate. It is not affiliated with Odoo S.A.

## Highlights

- Redesigned desktop shell with a focused Project → Analyze → Review → Migrate → Validate workflow.
- Compact source-status cards for verified Odoo 14–19 snapshots.
- Clear project metrics, detection states, automatic-fix preview, findings review, and migration results.
- Project-owned migration icon used by the desktop window and packaged application.
- Test settings are isolated from production QSettings; pytest temporary paths are rejected during restoration and persistence.
- User-facing version formatting is `v1.0.0-rc.2` while package metadata remains `1.0.0rc2`.

## Download choices after acceptance

- **Portable:** `OdooAddonMigrator-Windows` → extract and run `OdooAddonMigrator.exe`.
- **Installer:** `OdooAddonMigrator-Installer` → run `OdooAddonMigrator_Setup.exe`.

The unsigned RC may trigger Windows SmartScreen. Static validation is not runtime compatibility validation; install and test migrated addons on the target Odoo version before production use.
