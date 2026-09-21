# Odoo 17.0 to 18.0 evidence

This pack uses the official Odoo Community repository snapshots acquired and
indexed locally. The snapshot metadata is reproducible and is not inferred
from a version label alone.

| snapshot | branch | commit |
| --- | --- | --- |
| source | `17.0` | `5553002ba26972ba855585bfa37b54d4fee1fc56` |
| target | `18.0` | `3c3e3b3d17cbd98584c7685e607d9085712adfe0` |

Every version-specific finding in this directory is tagged
`migration_step = "17_to_18"` and uses a rule ID ending in `.17_to_18`.

## Rules and source evidence

| rule | source state | target state | evidence | severity | action |
| --- | --- | --- | --- | --- | --- |
| `manifest.version.17_to_18` | Addon manifests in the pinned `17.0` tree use `17.0` major prefixes. | The corresponding target manifests use `18.0` prefixes; no universal manifest-key or dependency rename was found that is safe for arbitrary custom addons. | Source and target addon `__manifest__.py` files in commits `5553002ba26972ba855585bfa37b54d4fee1fc56` and `3c3e3b3d17cbd98584c7685e607d9085712adfe0`. | safe auto-fix | Change only the leading `17.0` in a valid version value to `18.0`; preserve the complete suffix. |
| `xml.view_root.tree_to_list.17_to_18` | Odoo 17 `odoo/addons/base/models/ir_ui_view.py:163` registers `tree` as the view type and `:1393` validates tree roots. Official `addons/sale/views/sale_order_views.xml:183-191` uses `<tree>`. | Odoo 18 `odoo/addons/base/models/ir_ui_view.py:153` registers `list` and `:1519` validates list roots. The same official sale view XML ID `sale.view_order_tree` uses `<list>` in `addons/sale/views/sale_order_views.xml:178-186`. | Exact source/target files in the pinned commits above. | safe auto-fix for direct `ir.ui.view` architecture tags | Parse XML and rename only `<tree>` elements within an `ir.ui.view` `arch` field. XPath expressions and business semantics are not guessed; affected inherited XPaths remain review findings. |
| `python.*.17_to_18` | Indexed models, `_inherit`, fields, methods, locations, and signatures are read from the source snapshot. | SourceDiff identifies objects absent or changed in the target snapshot. | `SourceDiff` compares the indexes built from the two exact commits; the pack delegates the parameterized source-aware Python analyzer. | blocker for a removed inherited standard model; review for removed/changed fields, methods, signatures, and uncertain static cases | analysis-only; no business-logic rewrite |
| `dependency.module_removed.17_to_18` | A custom manifest dependency is present in the source module index. | It is absent from the target module index and is not provided by another custom module. | Module manifests and module set difference from the two indexed snapshots. | BLOCKER | analysis-only; no replacement is inferred from name similarity |
| `xml.inherit.*.17_to_18` and `xml.xpath.*.17_to_18` | Inherited view XML IDs and XPath expressions are evaluated against the source architecture where available. | Target XML IDs and architecture are checked; unsupported XPath remains `UNKNOWN`. | Indexed view XML IDs/architectures plus the generic structured XPath evaluator. | REVIEW_REQUIRED for missing or unknown target references | analysis-only; unsupported XPath is never converted into a definite miss |
| `security.*.17_to_18` | Access CSV model/group references are resolved against indexed source/custom metadata. | References are checked against the target index. | Indexed model XML IDs, groups, and the generic access CSV analyzer. | BLOCKER for a missing model or malformed access data where installation cannot proceed; REVIEW_REQUIRED for missing groups | analysis-only; permissions are never modified |
| `frontend.legacy_dependency.removed.17_to_18` | A custom JS file actually imports a module name that exists in `source.js_modules`. | The exact imported module name is absent from `target.js_modules`. | JS dependency parsing ignores comments and strings; module identities and locations come from the indexed source trees. | REVIEW_REQUIRED | analysis-only; no module replacement is inferred |
| `frontend.asset_bundle.removed.17_to_18` | A custom manifest names an asset bundle present in source manifest indexes. | The exact bundle name is absent from target manifest indexes. For example, Odoo 17 `addons/web/__manifest__.py:235` defines `web.pdf_js_lib`; it is not defined by the pinned Odoo 18 manifests. | Dynamic source/target manifest asset-key comparison, not a hardcoded replacement map. | REVIEW_REQUIRED | analysis-only; no bundle rename is guessed |
| `report.template_missing.17_to_18` | Custom `inherit_id`/`t-inherit` references are checked against source report/QWeb XML IDs. | Target report/QWeb XML IDs are checked. Official sale keeps `sale.report_saleorder_document` in both snapshots. | Indexed XML IDs and the generic report analyzer. | REVIEW_REQUIRED | analysis-only; target report/layout behavior is not asserted from static presence alone |

## Frontend and view conclusions

The official Odoo 17 and 18 files
`addons/web/static/src/core/utils/patch.js` both export
`patch(objToPatch, extension)` at line 71. No 17-to-18 patch-signature rule is
therefore emitted. The earlier 16-to-17 patch API finding remains owned by the
`16_to_17` migration step.

The Odoo 17 view validator at
`odoo/addons/base/models/ir_ui_view.py:392-395` and the Odoo 18 validator at
`:385-388` both reject `attrs` and `states` with the message that they have
not been used since 17.0. Consequently this pack does not re-report those
attributes: direct 16-to-18 migrations attribute that finding to `16_to_17`.

The tree-to-list rule is deliberately limited to parsed `ir.ui.view` XML
architecture. It does not rewrite QWeb, arbitrary data XML, comments, text,
XPath expressions, action `view_mode` values, or frontend code. Those cases
remain analysis/review territory unless an exact structured transformation is
proven.

No hardcoded module-removal list is used. Removed dependency and asset findings
are derived from the indexed source/target snapshots and require the custom
addon to reference the removed object. Static success is not a claim of target
runtime compatibility.
