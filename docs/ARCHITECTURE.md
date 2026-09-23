# Architecture v1.0 release candidate

## Principle

The migrator is local-first and source-aware. A migration decision should be supported by one or more of:

1. the exact official Odoo Community source snapshot for the selected source version;
2. the exact official Odoo Community source snapshot for the selected target version;
3. a deterministic transition rule for each adjacent version hop;
4. later, target-version install/runtime validation.

## Pipeline

```text
Custom Addons
    |
    v
Project Scanner -----> Source Odoo Index
    |                         |
    |                         v
    +-----------------> Compatibility Analyzer <----- Target Odoo Index
                                  |
                                  v
                         Migration Planner
                                  |
                  +---------------+---------------+
                  |               |               |
                15->16          16->17          17->18
                  |               |               |
                  +---------------+---------------+
                                  |
                                  v
                          Migrated Copy
                                  |
                                  v
                       Static Validation
                                  |
                                  v
                  Future Runtime/Docker Validation
```

## Reproducibility

Every cached Odoo checkout records its Git branch, origin and exact commit hash in `.odoo_migrator_snapshot.json`. Analysis reports should later embed those commit hashes.

## Rule policy

- Rules are adjacent-version transformations only.
- `15 -> 18` is executed as `15 -> 16 -> 17 -> 18`.
- Auto-fixes must be deterministic and safe enough to explain in a diff.
- Ambiguous changes become review findings instead of silent edits.
- Original addons are never mutated by default.

## Migration Brain

The reusable Migration Brain is a separate training/runtime boundary, not a
replacement for the source-aware engine:

```text
PUBLIC TRAINING (developer/release use)
Official Community snapshots
    -> indexed adjacent source diffs
    -> grouped semantic dataset
    -> lightweight ranker + deterministic knowledge
    -> migration_brain.omb

LOCAL ENTERPRISE TRAINING (authorized user)
migration_brain.omb + local Enterprise source
    -> composite adjacent source diffs
    -> derived knowledge + leakage audit
    -> enterprise_overlay.omb (bound to the Community fingerprint)

RUNTIME (normal Brain use)
Custom addons + Community .omb + optional local Enterprise overlay
    -> custom-only index
    -> deterministic adjacent rules and guarded mappings
    -> fixed-point static validation
    -> separate output, diff, report, and decision metadata
```

The `.omb` archive contains one fingerprinted JSON member with derived
compatibility facts, model parameters, rule metadata, training identities and
evaluation metrics. It never contains Odoo source text or Enterprise source.
Runtime Brain migration does not acquire, checkout, or index Odoo Community or
Enterprise trees; `source_code_indexed_at_runtime` is recorded as false. A
public Brain must be Community-only. Enterprise knowledge is built locally as
a `local_authorized_use_only` overlay, may be used only with its exact base
fingerprint, and is never silently merged into a distributable Community pack.
The source-aware `AnalysisService` remains available for fallback and for
building or evaluating Brain packs.

Brain automatic changes are precision-first. The ranker proposes candidates,
but AST/token-aware deterministic transforms and confidence/margin gates decide
whether a Python mapping may be applied. Unresolved API, security, XML/QWeb,
frontend, and asset compatibility facts are retained as review findings.
