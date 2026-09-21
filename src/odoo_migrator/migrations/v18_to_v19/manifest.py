from odoo_migrator.migrations.rules.manifest_version import ManifestVersionRule
from odoo_migrator.sources.registry import source_spec


class Manifest18To19Rule(ManifestVersionRule):
    def __init__(self):
        super().__init__(18, 19)
        self.rule_id = "manifest.version.18_to_19"
        self.evidence = (
            "Canonical source registry verified commits "
            f"{source_spec(18).verified_commit} and {source_spec(19).verified_commit}; "
            "official addon manifests use their respective major version prefixes. "
            "No universal manifest-key or dependency rename is safe for arbitrary custom addons."
        )
