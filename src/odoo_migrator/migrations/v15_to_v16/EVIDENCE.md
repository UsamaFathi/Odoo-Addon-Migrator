# Odoo 15 to 16 evidence

- Odoo 15 Community snapshot: `3a28e5b0adbb36bdb1155a6854cdfbe4e7f9b187` (`15.0`).
- Odoo 16 Community snapshot: `2df25c68396510abdb85f9b94ae0ba73f8cb340d` (`16.0`).
- Manifest version transformation is limited to the deterministic `15.0` to `16.0` prefix.
- Removed frontend dependencies were reproduced by comparing `addons/web/static/src/legacy/js` in both snapshots. Confirmed absent in 16.0: `web.fileUploadMixin`, `report.client_action`, `web.ReportService`, and `web.PieChart`.
- ORM, view, XML-ID and dependency findings are computed from exact commit-indexed source diffs; no rename is inferred.
