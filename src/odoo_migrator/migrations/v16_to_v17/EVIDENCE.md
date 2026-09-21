# Odoo 16.0 to 17.0 evidence

The commits below are the canonical values from
`odoo_migrator.sources.registry.source_spec`, not an independent pin map.

This pack is pinned to the official Odoo Community repository:

| snapshot | branch | commit |
| --- | --- | --- |
| source | `16.0` | `2df25c68396510abdb85f9b94ae0ba73f8cb340d` |
| target | `17.0` | `5553002ba26972ba855585bfa37b54d4fee1fc56` |

The commits are recorded by the local source manager and are the only source
of version-specific compatibility knowledge used by this pack.

Every rule below compares source commit
`2df25c68396510abdb85f9b94ae0ba73f8cb340d` with target commit
`5553002ba26972ba855585bfa37b54d4fee1fc56`.

## Rules

| rule | source evidence | target state | severity | action |
| --- | --- | --- | --- | --- |
| `manifest.version.16_to_17` | addon `__manifest__.py` files in the pinned `16.0` and `17.0` trees | addon versions use the corresponding major prefix | safe auto-fix | change only `16.0` at the beginning of the `version` value to `17.0`, preserving the suffix |
| `python.*.16_to_17` | indexed Python models and signatures compared between the pinned trees | removed models are absent; removed members and changed signatures are source-diff changes | blocker for a removed inherited standard model; review for members/signatures | analysis-only; no business-logic rewrite |
| `xml.inherit.*.16_to_17` | `ir.ui.view` XML IDs and architectures in the pinned trees | inherited view IDs and XPath targets are compared in source and target | review required for missing/unknown targets | analysis-only; unsupported XPath is `UNKNOWN`, never a definite miss |
| `xml.view_modifier.legacy_attribute.16_to_17` | source `odoo/addons/base/models/ir_ui_view.py:80-96`: Odoo 16 `transfer_node_to_modifiers` parses `attrs` and `states`; target `odoo/addons/base/models/ir_ui_view.py:392-395` validates `//*[@attrs]`/`//*[@states]` and raises `ValidationError` stating that since 17.0 they are no longer used | `attrs` and `states` are rejected by the Odoo 17 view validator | review required | analysis-only; boolean expressions are not flattened or rewritten |
| `security.*.16_to_17` | indexed model/XML-ID state and access CSV references | target model/group references are checked against the target index | blocker for missing model; review for missing group; blocker for malformed CSV | analysis-only; permissions are never changed |
| `dependency.module_removed.16_to_17` | module manifests in the pinned source/target indexes | a custom dependency present in 16.0 but absent in 17.0 is removed | blocker | analysis-only; no replacement is inferred |
| `frontend.legacy_dependency.removed.16_to_17` | Odoo 16 `addons/web/static/src/legacy/js/chrome/abstract_action.js`, `views/abstract_model.js`, `views/form/form_controller.js`, and `views/list/list_controller.js` declare aliases `web.AbstractAction`, `web.AbstractModel`, `web.FormController`, and `web.ListController`; those declarations are absent from the pinned Odoo 17 web tree | exact imported legacy module is absent in target | review required | analysis-only; imports are not replaced automatically |
| `frontend.patch_signature.changed.16_to_17` | Odoo 16 `addons/web/static/src/core/utils/patch.js:16` exports `patch(obj, patchName, patchValue, options = {})`; Odoo 17 same file `:71` exports `patch(objToPatch, extension)` | the named patch argument is no longer part of the target API | review required | analysis-only; the call is not rewritten automatically |
| `report.template_missing.16_to_17` | indexed QWeb/report XML IDs from the pinned trees | inherited `inherit_id` and `t-inherit` target IDs are checked | review required | analysis-only |

The manifest diff contains no source-backed universal key rename or asset
bundle rewrite that can be applied to arbitrary custom modules. Existing
`depends` and `assets` declarations therefore remain unchanged; dependency
removals and frontend module/API changes are reported by their dedicated
analysis rules.

No rule assumes that a legacy `odoo.define`, `attrs`, `states`, or Owl usage is
wrong merely because it is old. Findings are emitted only for the exact
source/target state documented above. This pack does not claim runtime
compatibility from static analysis.
