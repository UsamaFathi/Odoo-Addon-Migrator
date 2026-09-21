from odoo_migrator.analysis.compat import Finding
from odoo_migrator.sources.diff import SourceDiff
from odoo_migrator.sources.indexer import OdooIndex
from odoo_migrator.migrations.v15_to_v16.python import analyze as analyze_python


def analyze(custom: OdooIndex, source: OdooIndex, target: OdooIndex, diff: SourceDiff) -> list[Finding]:
    return analyze_python(custom, source, target, diff, target_version=17, migration_step="16_to_17")
