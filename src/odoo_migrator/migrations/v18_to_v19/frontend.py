from odoo_migrator.sources.indexer import OdooIndex
from odoo_migrator.migrations.rules.source_aware import analyze_frontend as analyze_source_frontend


def analyze(custom: OdooIndex, source: OdooIndex, target: OdooIndex):
    return analyze_source_frontend(custom, source, target, source_version=18, target_version=19,
                                   migration_step="18_to_19")
