from dataclasses import replace
from odoo_migrator.sources.indexer import OdooIndex
from odoo_migrator.migrations.v14_to_v15.reports import analyze as analyze_reports


def analyze(custom: OdooIndex, target: OdooIndex):
    return [replace(item, rule_id=(item.rule_id or item.code).replace("14_to_15", "15_to_16"), migration_step="15_to_16")
            for item in analyze_reports(custom, target)]
