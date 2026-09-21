from odoo_migrator.migrations.rules.manifest_version import ManifestVersionRule
from odoo_migrator.sources.registry import source_spec


class Manifest16To17Rule(ManifestVersionRule):
    """Update only the deterministic Odoo major prefix in addon manifests."""

    def __init__(self):
        super().__init__(16, 17)
        self.rule_id = "manifest.version.16_to_17"
        self.evidence = (
            "Canonical source registry verified commits "
            f"{source_spec(16).verified_commit} and {source_spec(17).verified_commit}; "
            "official addon manifests use their respective major prefixes."
        )
