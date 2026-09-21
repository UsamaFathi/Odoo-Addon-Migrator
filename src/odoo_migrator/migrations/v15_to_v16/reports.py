from odoo_migrator.sources.indexer import OdooIndex
from odoo_migrator.migrations.v14_to_v15.reports import analyze as analyze_reports


def analyze(custom: OdooIndex, target: OdooIndex):
    return analyze_reports(custom, target, target_version=16, migration_step="15_to_16")
