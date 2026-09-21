from odoo_migrator.sources.indexer import OdooIndex
from odoo_migrator.migrations.v14_to_v15.security import analyze as analyze_security


def analyze(custom: OdooIndex, target: OdooIndex):
    return analyze_security(custom, target, target_version=17, migration_step="16_to_17")
