from odoo_migrator.sources.indexer import OdooIndex
from odoo_migrator.sources.diff import SourceDiff
from odoo_migrator.migrations.rules.source_aware import analyze_removed_dependencies


def analyze(custom: OdooIndex, source: OdooIndex, target: OdooIndex, diff: SourceDiff):
    return analyze_removed_dependencies(custom, diff, source_version=16, target_version=17,
                                        migration_step="16_to_17")
