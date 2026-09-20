# Codex Implementation Roadmap

## Phase 1 — Foundation hardening
- Normalize package layout and imports.
- Expand unit tests for migration planning across all valid/invalid source-target pairs.
- Add structured logging.
- Add immutable migration-run metadata: tool version, source version, target version, migration path, source snapshot SHAs.
- Ensure output-copy safety and collision handling.

## Phase 2 — Odoo Source Intelligence
- Fetch or register official Community branches 14.0–19.0.
- Record exact commit SHA for every verified snapshot.
- Build deterministic indexes for modules, manifests, models, fields, methods/signatures, XML IDs, views, dependencies, controllers, assets, reports, security metadata and JS metadata.
- Cache indexes locally and invalidate by source commit SHA.
- Allow authorized local Enterprise source registration without copying or publishing it.

## Phase 3 — Compatibility Analyzer
For a custom addon, compare source assumptions with target source reality:
- missing/renamed models
- missing/renamed fields
- overridden methods missing in target
- changed method signatures
- inherited view / XPath targets no longer present
- dependency changes
- manifest/assets changes
- JS/frontend architecture risks

Classify findings as INFO, WARNING, REVIEW, BLOCKER.

## Phase 4 — 14 -> 15 migration pack
Implement and test each rule family separately:
- manifest
- Python ORM/API
- XML/views/QWeb
- security/data CSV/XML
- JS/assets
- controllers/reports where needed

Every rule must have source evidence and fixtures.

## Phase 5 — Remaining adjacent packs
Repeat the same evidence-driven process for:
- 15 -> 16
- 16 -> 17
- 17 -> 18
- 18 -> 19

Add end-to-end composition tests such as 14->19, 15->18, 16->19.

## Phase 6 — Validation
- Python parse/compile checks
- XML validation
- manifest checks
- dependency graph checks
- source-aware semantic checks
- optional isolated target Odoo install validation
- optional test execution

## Phase 7 — Developer UX
Desktop workflow:
1. Select addon folder
2. Select source version
3. Select target version
4. Analyze
5. Review plan
6. Migrate
7. Review diff/findings
8. Validate
9. Open/export migrated output

CLI should expose equivalent commands for automation.

## Phase 8 — Packaging
- Windows executable/installer
- local settings and source-cache location
- update mechanism for tool/rule packs without uploading user code
- reproducible release builds

## Definition of done for v1.0
- supports source 14–18 and targets up to 19
- every valid upward path composes correctly
- source-aware analysis uses verified official Odoo snapshots
- automatic transformations have traceable reports and tests
- original addons are never modified by default
- Windows desktop app and CLI both work from the same core
- optional install validation works in an isolated local environment
