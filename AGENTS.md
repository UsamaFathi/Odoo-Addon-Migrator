# AGENTS.md — Odoo Addon Migrator

## Mission
Build a production-grade, local-first developer tool that upgrades custom Odoo addons between supported major versions.

Supported version range for the initial product: Odoo 14.0 through 19.0.
The user chooses any supported source version and any higher supported target version. The engine must calculate and execute the ordered migration path, e.g. 15 -> 16 -> 17 -> 18.

## Product constraints
- Local-first. Source code must not leave the developer's machine.
- Never modify the original project by default. Write migrated output to a separate directory.
- The source-aware engine must use official Odoo source indexes for training, fallback analysis, and evaluation. Normal Migration Brain runtime must not require or index official Odoo source once a valid `.omb` pack exists.
- Do not claim 100% compatibility from static rewriting alone.
- Every automated change must be explainable and auditable.
- Preserve a before/after diff and migration report.
- Community source can be fetched from the official Odoo repository.
- Enterprise source must only be indexed from a local path provided by an authorized user. Do not redistribute Enterprise source.
- Favor structured parsing (Python AST, XML parser, JS parser where practical) over regex-only rewrites.
- Migration packs must remain composable: only adjacent-version packs are implemented directly (14->15, 15->16, ...). Multi-version upgrades compose those packs.

## Core architecture
Keep clear boundaries between:
1. project scanner
2. migration planner
3. Odoo source manager and source registry
4. source indexer
5. compatibility analyzer
6. adjacent-version migration rule packs
7. transformation engine
8. validators
9. diff/reporting
10. desktop UI
11. CLI

## Version-source design
The tool should be able to keep verified Odoo source snapshots with exact commit SHAs. Results should be reproducible. Updating Odoo source snapshots must be an explicit operation.

Index useful source metadata such as:
- addon/module names and manifests
- dependencies
- models and inheritance
- fields and relevant field metadata
- methods and signatures
- XML IDs
- views and inheritance relationships
- controllers/routes
- assets
- security groups/access files
- reports/QWeb templates
- JS modules/imports and Owl-related structures where feasible

## Validation levels
Implement progressively:
- Level 1: static/source-aware validation
- Level 2: target Odoo install validation using an isolated local runtime/container
- Level 3: automated runtime/module tests

Reports must distinguish auto-fixed, warnings, manual-review items, and blockers.

## Development order
1. Stabilize architecture and tests.
2. Finish official Odoo source acquisition/indexing.
3. Implement a strong 14->15 migration pack first.
4. Add 15->16, 16->17, 17->18, 18->19 one by one with fixtures/tests.
5. Add multi-version composition tests.
6. Add deep validators and Docker-based installation validation.
7. Improve desktop UX and diff/review workflow.
8. Package a Windows installer/executable.

## Quality bar
For every migration rule:
- add positive fixtures
- add no-op fixtures
- add malformed/edge-case fixtures where relevant
- document why the rule exists
- identify whether it is safe-autofix, review-required, or blocker detection
- test idempotency where meaningful

Do not add a rule solely from memory. Verify it against official Odoo source/history/documentation or a reproducible source diff.

## Non-goals for early versions
- database/data migration
- arbitrary downgrade support
- silently rewriting ambiguous business logic
- pretending successful parsing means functional compatibility

## Commands
Use the existing project metadata and scripts as the starting point. Keep Windows local usage simple, and keep the core engine independent from the UI so CLI, desktop, and future CI integrations share one implementation.

Local verification commands:

```powershell
python -m pytest -q
python -m odoo_migrator plan --from 16 --to 18
python -m odoo_migrator brain info .\migration_brain.omb
python -m odoo_migrator brain migrate ADDONS OUTPUT --brain .\migration_brain.omb --from 16 --to 18
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\build_installer.ps1
```

The Windows build scripts and smoke tests must be run locally before release
work. Do not trigger GitHub Actions from a development task unless the user
explicitly requests it.

Migration Brain invariants:

- Training may read exact Community snapshots and an authorized local
  Enterprise checkout, but Enterprise source is never embedded in a brain pack
  or redistributed.
- Runtime Brain migration must not acquire, index, or require Odoo source;
  `source_code_indexed_at_runtime` remains false.
- ML predictions rank candidates only. Automatic Python changes require the
  deterministic AST/token guards and high-confidence margin checks; ambiguous
  changes stay in the report for review.
- Every Brain migration copies to a separate staging/output directory and
  fingerprints the original project. The input project is never modified.
- A `.omb` pack contains derived knowledge and model parameters only, never
  source file contents.


## Migration Brain hardening rules

- Brain schema v3 is allow-listed. New knowledge types require an explicit
  schema change and tests; arbitrary payload keys must never be serialized.
- Report production decision metrics at the same calibrated threshold/margin
  used for automatic method mappings. Baseline classifier accuracy at 0.5 is
  diagnostic only and must not be presented as auto-fix accuracy.
- Keep train/validation splits grouped by adjacent step + model + source API.
  Hard negatives for one decision must stay in the same split as its positive.
- Prefer Git-history rename evidence when a full local repository is available;
  otherwise use exact semantic rename evidence before lower-weight weak labels.
- Learned field rewrites may change declarations and proven `self.field`
  access only. Do not rewrite `other.field` without model proof.
- Signature auto-fixes are limited to parameter-name-only changes with identical
  shape, defaults and annotations and an exact custom source-signature match.
- Learned XML/QWeb, JavaScript, and asset mappings must be one-to-one and based
  on exact derived evidence before runtime transforms are allowed.
