# User guide

1. Open Odoo Addon Migrator and select the folder containing custom addons. A folder can be dragged onto the picker.
2. Let the local scan finish. Review addon counts, file statistics, dependencies, and manifest version agreement.
3. Choose a source version if manifests are mixed or unknown. Targets are supplied by the migration-pack registry and are always higher than the source.
4. Select **Analyze Project**. Source preparation, indexing, compatibility analysis, and automatic-fix planning run outside the UI thread.
5. Review the dashboard and findings table. A **Blocker** prevents migration. **Review Required** needs developer attention but does not itself prevent migration. **Warning** is informational risk.
6. Review the Automatic Fixes list, then start migration. The output is a new directory; the selected input is not edited.
7. Review the generated report and unified diff. **Static Validated** means the structural checks passed, not that the addon has been installed or runtime-tested.
8. Open the output folder and perform target-server installation and business-workflow testing separately.

The report records source and target commits, migration path, rule IDs, findings, changed files, and validation state. A migration through multiple versions keeps each finding attached to its adjacent migration step.
