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
