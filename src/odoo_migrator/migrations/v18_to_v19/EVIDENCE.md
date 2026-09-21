# Odoo 18.0 to 19.0 evidence

The commits below are the canonical values from
`odoo_migrator.sources.registry.source_spec`, not an independent pin map.

This pack is based on the exact official Odoo Community snapshots below. The
source manager and index cache retain these commit values; no moving branch
head is substituted for them.

| snapshot | branch | commit |
| --- | --- | --- |
| source | `18.0` | `3c3e3b3d17cbd98584c7685e607d9085712adfe0` |
| target | `19.0` | `dd153b3cb418c2e4d4302ac62398ef95d51c9891` |

Every finding from this pack uses `migration_step = "18_to_19"`. Pack rule IDs
end in `.18_to_19`. Historical syntax changes are intentionally not repeated:
`attrs`/`states` belong to `16_to_17`, while Tree→List view architecture and
action `view_mode` conversion belong to `17_to_18`.

## Rules and source evidence

| rule | source state | target state | official evidence | severity | action |
| --- | --- | --- | --- | --- | --- |
| `manifest.version.18_to_19` | The pinned 18.0 addon manifests use `18.0` major prefixes. | The pinned 19.0 addon manifests use `19.0` major prefixes. No universal manifest-key or dependency rename was established. | Official addon `__manifest__.py` files in the two pinned snapshots. | safe auto-fix | Change only the leading major prefix in a valid version value and preserve the suffix. |
| `python.model.removed.18_to_19`, `python.method.*.18_to_19`, `python.field.*.18_to_19`, `python.signature.changed.18_to_19` | The source index contains the referenced standard model/member/signature. | `SourceDiff` shows a removed or changed target model/member/signature. | Exact indexed Python model definitions and signatures from the two pinned commits. | BLOCKER for a removed inherited model; REVIEW_REQUIRED for members/signatures | Analysis only; no business-logic rewrite. |
| `dependency.module_removed.18_to_19` | A custom manifest dependency is present in the indexed 18.0 module set. | The exact dependency is absent from the indexed 19.0 module set and is not supplied by a custom module. | Dynamic module-set difference from the pinned source trees. | BLOCKER | Analysis only; no name-similarity replacement is inferred. |
| `xml.inherit.*.18_to_19`, `xml.xpath.*.18_to_19` | Custom inherited view targets and XPath expressions are evaluated against indexed 18.0 IDs/architectures. | The same target IDs and supported XPath expressions are checked against indexed 19.0 state. | Indexed XML IDs/view architectures plus the conservative tri-state XPath evaluator. | REVIEW_REQUIRED for missing or unknown target references | Analysis only; unsupported XPath remains `UNKNOWN`. |
| `security.*.18_to_19` | Access CSV model/group references are resolved against custom and indexed source metadata. | References are checked against the target index. | Indexed model XML IDs, models, groups, and structured CSV parsing. | BLOCKER for missing models or malformed access data; REVIEW_REQUIRED for missing groups | Analysis only; permissions are never altered. |
| `frontend.legacy_dependency.removed.18_to_19` | A custom JavaScript file imports a module that exists in `source.js_modules`. | That exact imported module is absent from `target.js_modules`. | Structured JS dependency extraction and exact indexed module sets. | REVIEW_REQUIRED | Analysis only; comments and strings are ignored and no replacement is inferred. |
| `frontend.asset_bundle.removed.18_to_19` | A custom manifest names an asset bundle key present in 18.0 manifests. | The exact bundle key is absent from 19.0 manifests. | Dynamic asset-key comparison from the two pinned manifest indexes. | REVIEW_REQUIRED | Analysis only; no bundle rename is guessed. |
| `report.template_missing.18_to_19` | Custom report/QWeb `inherit_id` or `t-inherit` references are checked against source XML IDs. | Target report/QWeb XML IDs are checked in the 19.0 index. | Indexed XML IDs and the generic report analyzer. | REVIEW_REQUIRED | Analysis only; static presence is not runtime compatibility. |

## Source conclusions

The pinned `odoo/addons/base/models/ir_actions.py` files define
`ir.actions.act_window.view_mode` with default `list,form` in 18.0 (line 312)
and 19.0 (line 318). Both snapshots define `VIEW_TYPES` with `list` (18.0
lines 398-405; 19.0 lines 401-408), and both retain the same comma-separated
mode computation and validation. Therefore this pack has no action
`tree_to_list` rule. The related `ir.actions.act_window.view.view_mode` field
is also already list-based in both snapshots.

The pinned `ir_ui_view.py` files retain `list` as the view type in both
snapshots. No new deterministic root-tag or modifier conversion was proven
for 18.0→19.0, so this pack does not transform XML. XPath analysis remains
conservative and does not rewrite expressions.

No fixed list of removed modules, JavaScript imports, or asset bundles is used
in code. These findings are emitted only when the custom addon references an
object present in the exact 18.0 index and absent from the exact 19.0 index.
Static findings are not a claim of runtime installation compatibility.
