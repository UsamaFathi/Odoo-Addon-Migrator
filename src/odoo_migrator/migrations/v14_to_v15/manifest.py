"""Manifest rule for 14.0 -> 15.0.

Evidence: the official Odoo repository uses major-prefixed addon versions on
the 14.0 and 15.0 branches. This rule changes only that prefix and preserves
the addon release suffix; it does not guess dependency changes.
"""
from odoo_migrator.migrations.rules.manifest_version import ManifestVersionRule


class Manifest14To15Rule(ManifestVersionRule):
    rule_id = "manifest.version.14_to_15"
    category = "manifest"
    classification = "safe_auto_fix"

    def __init__(self):
        super().__init__(14, 15)
        self.rule_id = "manifest.version.14_to_15"
