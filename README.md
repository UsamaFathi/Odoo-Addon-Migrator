# Odoo Addon Migrator — v0.1 foundation

A local-first developer tool for analysing and migrating **custom Odoo addons** between supported major versions.

## Product rules

- Source versions: **14.0 → 19.0**.
- Target can be **any supported version higher than source**.
- Multi-hop migrations are planned automatically, e.g. `15 → 18` becomes `15 → 16 → 17 → 18`.
- The original custom addon directory is never modified by default.
- Official Odoo Community source is cached locally from `https://github.com/odoo/odoo.git` and indexed per version.
- Each source cache records the exact Git commit used, so reports are reproducible.
- Enterprise source is not downloaded or redistributed; a later connector can index a developer-provided local Enterprise checkout.

## What v0.1 already contains

- Version validation and migration-path planner.
- Official Community source manager for Odoo 14.0–19.0.
- Source snapshot metadata with branch + commit hash.
- Odoo source indexer for modules, manifests, models, fields, methods and XML IDs.
- Custom-addon scanner.
- First compatibility checks: dependencies, inherited models, removed/renamed-method candidates.
- Migration engine with composable transition rules.
- Safe manifest-version rule as the first example transformation.
- CLI.
- PySide6 desktop shell.
- Unit tests for planner and safe-copy behaviour.

## CLI quick start

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"

odoo-migrator plan --from 15 --to 18
odoo-migrator source ensure 18
odoo-migrator source info 18
odoo-migrator analyze ./custom_addons --from 15 --to 18
```

Desktop UI:

```bash
pip install -e ".[desktop]"
odoo-migrator-ui
```

## Source-aware design

The tool does not treat migration as blind regex replacement. It compares the custom code against indexes generated from the actual Odoo source checkout used for the selected source and target versions. A later validation layer can boot the target version (e.g. via Docker) and install migrated modules in an empty database.

## Important

A successful static migration is **not** a guarantee of runtime correctness. The app should only show stronger confidence after installation/runtime tests also pass.
