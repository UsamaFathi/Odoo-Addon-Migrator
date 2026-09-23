# Migration Brain

Migration Brain is the reusable, source-free runtime for Odoo Addon
Migrator.  It separates expensive official-source research from normal addon
migrations:

```text
TRAINING (developer/advanced operation)
Community 14..19 + authorized local Enterprise
    -> source indexes
    -> adjacent SourceDiff summaries
    -> grouped semantic dataset
    -> deterministic mappings + trained ranker
    -> migration_brain.omb

RUNTIME (normal operation)
custom addons + source/target + migration_brain.omb
    -> custom-addon index only
    -> deterministic transformations
    -> high-confidence mappings
    -> fixed-point static validation
    -> separate output + decision report
```

## Runtime boundary

`BrainRuntimeMigrator` never downloads, checks out, indexes, or reads Odoo
Community or Enterprise trees.  It may index the staged custom-addon tree so
that a learned method/model/field mapping is applied only to the correct model
class.  The original input tree is fingerprinted and never written.

The pack records `source_code_indexed_at_runtime: false` in its run metadata.
Every output contains:

- `.odoo_migration_brain_run.json`
- `migration.diff`
- `migration_report.html`

The report distinguishes automatic changes from unresolved blockers and review
items.  `passed` means Level-1 static validation passed; it is not proof that
the addon installs or behaves correctly at runtime.

## Training and evidence

Training uses exact source snapshots resolved by `SourceManager`.  Enterprise
is accepted only from an authorized local checkout or extracted local tree.
Enterprise source is read-only input and is never placed in a `.omb` pack,
build artifact, report, or repository.

`BrainTrainer.build()` accepts either one repository containing version
folders/branches (`enterprise_root`) or a per-version mapping
(`enterprise_roots`).  Pack metadata stores only derived identities such as
version, commit/ref, source mode, and whether Enterprise knowledge was
included.

The pack schema is versioned and fingerprinted. Schema v3 is allow-listed:
unknown top-level, step, mapping, transformation, or compatibility keys are
rejected before a pack can be written. Its archive contains only `brain.json`;
unexpected archive members and unsupported schema versions are rejected. The
schema contains:

- deterministic adjacent-step rule IDs and evidence;
- module/model/field/method/XML/JS/asset compatibility summaries;
- high-confidence dependency/model/field/method mappings;
- exact derived XML/QWeb ID, JavaScript module, and asset-bundle rename mappings;
- safe parameter-name-only signature adapters where shape/defaults/annotations
  are unchanged;
- learned ranker coefficients;
- grouped train/validation metrics plus calibrated production decision metrics
  (precision, recall, coverage, false-auto-fix rate, threshold, and margin).

The dataset split is grouped by migration step, model, and source API. This
keeps a source API and its hard negatives together and avoids reporting a
misleading validation result caused by equivalent examples appearing in both
training and holdout sets. The trainer calibrates the actual automatic-decision
gate on grouped holdout decisions and prefers zero false auto-fixes when the
holdout evidence supports it.

Training supervision is layered: stable APIs, exact semantic rename pairs,
optional Git-history rename hints from a full local repository, and lower-weight
conservative weak rename evidence. Git history is optional; normal training
still works when only pinned source snapshots are available.

## Automatic-change policy

ML is a candidate ranker, not a code generator. A method mapping requires the
calibrated high probability and minimum margin over the second candidate.
Mappings are applied through token/AST-aware transformations; arbitrary text
and business logic are never rewritten from a prediction. Learned field
rewrites are restricted to field declarations and proven `self.field` access.
Signature auto-fixes are limited to parameter-name-only changes whose source
signature matches exactly; arity/default/annotation changes remain review-only.

Deterministic rules include the verified adjacent-pack transformations, such
as manifest prefixes, `attrs`/`states`, Tree/List architecture and action
view modes, plus the Odoo 19 `_sql_constraints` to `models.Constraint` API
conversion for literal declarations.  Dynamic, ambiguous, or behaviorally
uncertain changes remain in the decision report.

## Enterprise and future versions

Community and Enterprise are composed as separate indexed layers during
training.  Module provenance is retained in the index (`community`,
`enterprise`, or a composed layer), and exact per-version identities are
recorded.  Adding Odoo 20 requires a new adjacent pack and a new training
run; it does not require changing the `.omb` format or runtime architecture.

## Local commands

Build a full Community Brain:

```powershell
python -m odoo_migrator brain build --from 14 --to 19 --output .\migration_brain.omb
```

Build with a local Enterprise repository whose branches or version folders
are named `14.0` through `19.0`:

```powershell
python -m odoo_migrator brain build --from 14 --to 19 `
  --enterprise D:\Sources\odoo-enterprise `
  --history-repo D:\Sources\odoo-full-history `
  --output .\migration_brain.omb
```

Inspect and run the source-free runtime:

```powershell
python -m odoo_migrator brain info .\migration_brain.omb
python -m odoo_migrator brain migrate ADDONS OUTPUT `
  --brain .\migration_brain.omb --from 16 --to 18
```

The normal source-aware `analyze`/`migrate` commands remain available for
fallback and evaluation.  Brain mode is intentionally a separate path so a
normal migration does not unexpectedly use a stale or unrelated pack.

