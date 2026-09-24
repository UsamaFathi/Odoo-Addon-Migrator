# Migration Brain

Migration Brain is the reusable, source-free runtime for Odoo Addon
Migrator.  It separates expensive official-source research from normal addon
migrations:

```text
PUBLIC TRAINING (developer/release operation)
Community 14..19
    -> source indexes
    -> adjacent SourceDiff summaries
    -> grouped semantic dataset
    -> deterministic mappings + trained ranker
    -> migration_brain.omb

LOCAL ENTERPRISE TRAINING (authorized user operation)
migration_brain.omb + authorized local Enterprise 14..19
    -> composite source indexes and adjacent semantic diffs
    -> leakage audit
    -> base-bound enterprise_overlay.omb

RUNTIME (normal operation)
custom addons + source/target + migration_brain.omb
    + optional enterprise_overlay.omb
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

The redistributable Community pack is built with `BrainTrainer`. An authorized
user can then build an Enterprise overlay with `EnterpriseOverlayTrainer` from
either one repository containing version folders/branches (`enterprise_root`)
or a per-version mapping (`enterprise_roots`). The overlay is fingerprinted,
bound to one exact Community Brain fingerprint, and rejected if used with a
different base. It is labelled `local_authorized_use_only`; the application
does not present it as a redistributable public artifact.

Enterprise source is needed only while that local overlay is trained. After
training, runtime needs the Community `.omb`, the optional overlay `.omb`, and
the custom addon. Tests delete all Community and Enterprise training trees
before running a Brain migration to enforce this boundary.

The pack schema is versioned and fingerprinted. Schema v4 is allow-listed:
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

Community and Enterprise are composed as separate indexed layers during local
overlay training. Module provenance is retained in the index (`community`,
`enterprise`, or a composed layer), and exact per-version identities are
recorded. The overlay contains derived mappings, compatibility facts and model
coefficients, not indexed source, raw training examples, or source files. A
defense-in-depth leakage audit rejects verbatim long source fragments before
writing an Enterprise pack. This audit supplements rather than replaces the
authorized user's licensing obligations.

Adding Odoo 20 requires a new adjacent pack and a new training run; it does not
require changing the runtime architecture.

## Local commands

Build a full Community Brain:

```powershell
python -m odoo_migrator brain build --from 14 --to 19 --output .\migration_brain.omb
```

Build a local Enterprise overlay whose repository branches or version folders
are named `14.0` through `19.0`:

```powershell
python -m odoo_migrator brain build-enterprise-overlay `
  --base .\migration_brain.omb `
  --enterprise D:\Sources\odoo-enterprise `
  --history-repo D:\Sources\odoo-full-history `
  --output .\enterprise_overlay.omb
```

### Google Colab training

For an authorized Enterprise source set stored in Google Drive, use
[`notebooks/train_migration_brain_colab.ipynb`](notebooks/train_migration_brain_colab.ipynb).
The notebook checks out an exact Odoo Addon Migrator commit, acquires the
centrally pinned Community snapshots from the official Odoo GitHub repository,
validates separate Enterprise folders for 14.0 through 19.0, and runs the same
`BrainTrainer` and `EnterpriseOverlayTrainer` used by the desktop and CLI.

The recommended Drive layout is:

```text
My Drive/OdooEnterprise/
    14.0/
    15.0/
    16.0/
    17.0/
    18.0/
    19.0/
```

If the Enterprise root is shared with the Google account, add a shortcut to
My Drive so Colab's Drive mount can see it. The notebook optionally copies each
tree to disposable `/content` storage for faster indexing; it never writes to
the Drive source. It saves the Community Brain, base-bound Enterprise overlay,
training summary, SHA-256 checksums, and timing log back to Drive. Reruns reuse
valid existing packs unless explicitly disabled.

The notebook finishes with a 16-to-18 source-free smoke migration and verifies
that the input fixture remains unchanged. The Enterprise overlay remains
`local_authorized_use_only`: moving training to Colab does not change licensing
or distribution rights.

Inspect and run the source-free runtime:

```powershell
python -m odoo_migrator brain info .\migration_brain.omb
python -m odoo_migrator brain migrate ADDONS OUTPUT `
  --brain .\migration_brain.omb --from 16 --to 18

# With locally trained Enterprise knowledge:
python -m odoo_migrator brain migrate ADDONS OUTPUT `
  --brain .\migration_brain.omb `
  --overlay .\enterprise_overlay.omb --from 16 --to 18
```

The normal source-aware `analyze`/`migrate` commands remain available for
fallback and evaluation.  Brain mode is intentionally a separate path so a
normal migration does not unexpectedly use a stale or unrelated pack.

