from odoo_migrator.migrations.rules.manifest_version import ManifestVersionRule
from odoo_migrator.sources.registry import source_spec


class Manifest17To18Rule(ManifestVersionRule):
    def __init__(self):
        super().__init__(17, 18)
        self.rule_id = "manifest.version.17_to_18"
        self.evidence = (
            "Canonical source registry verified commits "
            f"{source_spec(17).verified_commit} and {source_spec(18).verified_commit}; "
            "official addon manifests use their respective major prefixes."
        )
