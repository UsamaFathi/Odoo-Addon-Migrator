# Odoo 15 to 16 evidence

The commits below are the canonical values from
`odoo_migrator.sources.registry.source_spec`, not an independent pin map.

- Odoo 15 Community snapshot: `3a28e5b0adbb36bdb1155a6854cdfbe4e7f9b187` (`15.0`).
- Odoo 16 Community snapshot: `2df25c68396510abdb85f9b94ae0ba73f8cb340d` (`16.0`).
- Manifest version transformation is limited to the deterministic `15.0` to `16.0` prefix.
- Removed frontend dependencies were reproduced by comparing `addons/web/static/src/legacy/js` in both snapshots. In 15.0 the symbols are defined at `views/file_upload_mixin.js`, `report/client_action.js`, `services/report_service.js`, and `widgets/pie_chart.js`; the corresponding definitions are absent from the 16.0 web tree. Confirmed module names: `web.fileUploadMixin`, `report.client_action`, `web.ReportService`, and `web.PieChart`.
- The frontend analyzer parses actual `require(...)` and ES import statements, then requires the module to be present in the indexed 15.0 snapshot and absent from the indexed 16.0 snapshot. Comments and unrelated strings are ignored. Severity is REVIEW_REQUIRED because replacements depend on component behavior.
- ORM, view, XML-ID and dependency findings are computed from exact commit-indexed source diffs; no rename is inferred.
- Removed models and missing target dependencies are BLOCKER findings because no safe target object exists. Removed fields/methods, signature changes, missing view targets, XPath changes, and QWeb inheritance changes are REVIEW_REQUIRED because business intent cannot be inferred safely.
