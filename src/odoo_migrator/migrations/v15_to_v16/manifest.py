from odoo_migrator.migrations.rules.manifest_version import ManifestVersionRule
from odoo_migrator.sources.registry import source_spec


class Manifest15To16Rule(ManifestVersionRule):
    """Update only the verified major-version prefix in addon manifests."""

    def __init__(self):
        super().__init__(15, 16)
        self.rule_id = "manifest.version.15_to_16"
        self.evidence = (
            "Canonical source registry verified commits "
            f"{source_spec(15).verified_commit} and {source_spec(16).verified_commit}; "
            "official addon manifests use their respective major prefixes."
        )
