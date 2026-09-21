from odoo_migrator.analysis.compat import Finding
from odoo_migrator.sources.diff import SourceDiff
from odoo_migrator.sources.indexer import OdooIndex
from odoo_migrator.migrations.v15_to_v16.xml import analyze as analyze_views


def analyze(custom: OdooIndex, source: OdooIndex, target: OdooIndex, diff: SourceDiff) -> list[Finding]:
    # Odoo 18 and 19 both use the already-migrated list architecture. In
    # particular, this pack deliberately does not re-run the 17->18 tree rule.
    return analyze_views(custom, source, target, target_version=19, migration_step="18_to_19")
