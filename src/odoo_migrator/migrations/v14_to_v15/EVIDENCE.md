# Odoo 14.0 to 15.0 evidence

The canonical source registry supplies the verified Community snapshots used
by this adjacent pack:

| snapshot | branch | commit |
| --- | --- | --- |
| source | `14.0` | `cc0060e889603eb2e47fa44a8a22a70d7d784185` |
| target | `15.0` | `3a28e5b0adbb36bdb1155a6854cdfbe4e7f9b187` |

The manifest rule changes only the deterministic Odoo major prefix. Other
findings are source-index comparisons and conservative structured analysis;
no business-logic replacement is inferred.
